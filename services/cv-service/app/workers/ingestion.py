"""Persisted leased work; fenced publication and cleanup survive process restarts."""
import asyncio
import logging
import time
from copy import deepcopy
from uuid import UUID, uuid4
from pydantic import ValidationError
from app.domain.capabilities import effective_fingerprint
from app.domain.errors import Conflict, CvError
from app.domain.service import bump, now, PROCESSING_STAGES
from app.domain.storage import UploadCapacity
from app.domain.model_usage import ModelUsage, ModelAdmissionError
from app.domain.extraction_errors import ExtractionFailure, StaleExtraction
from app.domain.extraction_feedback import feedback_for
from app.domain.extraction_retry import REJECTED_OUTPUT, failure_for_model, should_auto_retry
from app.domain.reconciliation import candidate_for, affected_sources
from app.parsing.process import isolated_parse
from app.workflows.checkpoints import LatestStateSaver
from app.workflows.extraction import ExtractionHarness, WORKFLOW_VERSION
from app.domain.deletion import CvDeletion

logger = logging.getLogger(__name__)

# Only schema-owned locations and known error types may reach logs. Model output,
# including extra field names and Pydantic messages, is untrusted private data.
_ITEM_FIELDS = frozenset({'kind', 'title', 'description', 'explicit', 'evidence', 'skill_names',
    'category', 'proficiency', 'experience_months', 'start_date', 'end_date', 'ongoing',
    'context', 'supporting_items', 'uncertainties'})
_LIST_FIELDS = frozenset({'skill_names', 'supporting_items', 'uncertainties'})
_ERROR_TYPES = frozenset({'missing', 'extra_forbidden', 'literal_error', 'model_type', 'dict_type',
    'list_type', 'string_type', 'string_too_short', 'string_too_long', 'string_pattern_mismatch',
    'bool_type', 'int_type', 'float_type', 'greater_than_equal', 'less_than_equal',
    'finite_number', 'too_short', 'too_long', 'value_error'})
_MAX_DIAGNOSTIC_ERRORS = 16
# The saved state itself may be the cause, so these retries start from the document.
_RESTART_AFTER = frozenset({'unexpected_error'})


def _diagnostic_path(location, error_type):
    if error_type == 'extra_forbidden': return 'other'
    parts = tuple('[]' if type(part) is int else part for part in location)
    if parts == (): return '$'
    if parts == ('items',): return 'items'
    if parts == ('items', '[]'): return 'items[]'
    if len(parts) == 3 and parts[:2] == ('items', '[]') and parts[2] in _ITEM_FIELDS:
        return 'items[].' + parts[2]
    if len(parts) == 4 and parts[:2] == ('items', '[]') and parts[2] in _LIST_FIELDS and parts[3] == '[]':
        return 'items[].' + parts[2] + '[]'
    if parts == ('items', '[]', 'evidence', '[]'): return 'items[].evidence[]'
    if (len(parts) == 5 and parts[:4] == ('items', '[]', 'evidence', '[]')
            and parts[4] in {'block_id', 'excerpt'}):
        return 'items[].evidence[].' + parts[4]
    return 'other'


def _safe_uuid(value):
    try: return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError): return 'unknown'


def _log_invalid_extraction(error, claimed, repair_attempted=False):
    errors = error.errors(include_input=False, include_context=False, include_url=False)
    summary = [(_diagnostic_path(entry.get('loc', ()), entry.get('type')),
                entry.get('type') if entry.get('type') in _ERROR_TYPES else 'other')
               for entry in errors[:_MAX_DIAGNOSTIC_ERRORS]]
    logger.warning('CV extraction schema invalid cv_id=%s operation_id=%s errors=%s truncated=%s stage=extraction_validation category=schema_validation provider_status_code=None repair_attempted=%s',
                   _safe_uuid(claimed.get('_id')), _safe_uuid(claimed['operation'].get('id')),
                   summary, len(errors) > _MAX_DIAGNOSTIC_ERRORS, repair_attempted)


class IngestionWorker:
    def __init__(self, repository, files, settings, extractor, parser=isolated_parse, capacity=None, model_usage=None):
        self.repository, self.files, self.settings = repository, files, settings
        self.extractor, self.parser = extractor, parser
        self.capacity = capacity or UploadCapacity(repository, files, settings)
        self.model_usage = model_usage or ModelUsage(repository.model_usage, files.root, settings)
        self.deletion = CvDeletion(repository, files, self.capacity)
        self.processing_cursor = None
        self.cleanup_cursor = None

    def claim(self, candidate):
        document = deepcopy(candidate)
        operation = document['operation']
        if operation['attempt'] >= self.settings.max_attempts:
            operation.update(status='failed', error={'code': 'processing_interrupted',
                'message': 'Processing was repeatedly interrupted. Check status and retry this saved upload.', 'retryable': True})
            bump(document, operational=True)
            try: self.repository.replace(candidate, document)
            except Conflict: pass
            # Repeated interruptions may come from the saved state, so a retry starts clean.
            self.repository.extraction_states.discard(document['_id'])
            return None
        operation.pop('retry_at', None)
        operation.update(status='processing', stage='source_read', attempt=operation['attempt'] + 1,
                         lease_token=str(uuid4()), lease_until=now() + self.settings.lease_seconds, error=None)
        bump(document, operational=True)
        try: return self.repository.replace(candidate, document)
        except Conflict: return None

    def _erase_state_if_deleted(self, claimed):
        # The last save of a stale worker can land after the CV's deletion finished.
        if not self.repository.get(claimed['user_id'], claimed['_id']):
            self.repository.extraction_states.delete(claimed['_id'])

    def process(self, claimed):
        token = claimed['operation']['lease_token']
        stage = 'source_read'
        harness = None
        deadline = time.monotonic() + max(0, claimed['operation']['lease_until'] - now())
        previous_failure = claimed['operation'].get('last_failure')
        told = {'previous_failure': previous_failure} if previous_failure else {}
        issues = []

        def observe(value):
            nonlocal stage
            stage = value
            for _ in range(5):
                current = self.repository.get(claimed['user_id'], claimed['_id'])
                if (not current or current['operation']['lease_token'] != token
                        or current['operation']['status'] != 'processing'
                        or current['operation']['lease_until'] <= now()):
                    raise StaleExtraction()
                # Repair can revisit validation; never move the displayed progress backwards.
                previous = current['operation'].get('stage', 'source_read')
                if PROCESSING_STAGES[previous][0] >= PROCESSING_STAGES[value][0]: return
                updated = deepcopy(current)
                updated['operation']['stage'] = value
                bump(updated, operational=True)
                try:
                    self.repository.replace(current, updated)
                    return
                except Conflict: continue
            raise StaleExtraction()

        def holds_lease():
            current = self.repository.get(claimed['user_id'], claimed['_id'])
            return bool(current and current['operation']['lease_token'] == token and current['operation']['status'] == 'processing')

        def remaining_time():
            current = self.repository.get(claimed['user_id'], claimed['_id'])
            if (not current or current['operation']['lease_token'] != token
                    or current['operation']['status'] != 'processing'
                    or current['operation']['lease_until'] <= now()):
                raise StaleExtraction()
            remaining = min(deadline - time.monotonic(), current['operation']['lease_until'] - now())
            if remaining <= 10:
                raise ExtractionFailure('CV extraction has insufficient processing time remaining. Your upload is saved; retry later.',
                                        stage, 'timeout')
            return remaining - 10  # Leave time for validation and fenced publication.

        def call_model(blocks, candidate, feedback):
            remaining_time()  # Deny stale work before reserving a provider attempt.
            def invoke():
                timeout = remaining_time()  # Revalidate after admission/concurrency I/O.
                if feedback is not None:
                    return self.extractor.repair(blocks, candidate, feedback, timeout_seconds=timeout, **told)
                return self.extractor.extract(blocks, timeout_seconds=timeout, **told)
            return self.model_usage.run(claimed['user_id'], invoke,
                configured=getattr(self.extractor, 'configured', True))

        def verify_evidence(blocks, refs):
            remaining_time()
            def invoke():
                return self.extractor.verify_evidence(blocks, refs, timeout_seconds=remaining_time())
            return self.model_usage.run(claimed['user_id'], invoke,
                configured=getattr(self.extractor, 'configured', True))

        auto_retry_allowed = True
        try:
            remaining_time()
            if not claimed['original_available'] or not self.files.exists(claimed['_id']):
                raise ValueError('The private original has expired. Reupload the same file to preserve its corrections.')
            original = self.files.read(claimed['_id'])
            harness = ExtractionHarness(claimed['_id'],
                lambda data: self.parser(data, '.' + claimed['file_type'], self.settings.max_file_bytes),
                call_model, observe, verify_evidence=verify_evidence,
                checkpointer=LatestStateSaver(self.repository.extraction_states, claimed['_id'], claimed['user_id'], holds_lease),
                # A retry keeps the operation and resumes. A reupload or new workflow version starts fresh.
                thread_id=f"{claimed['operation']['id']}:{WORKFLOW_VERSION}",
                rewind_rejected=bool(previous_failure and previous_failure['category'] in REJECTED_OUTPUT))
            result = harness.run(original)
            parsed, items, metadata = result['parsed'], result['items'], result['metadata']
            observe('publication')
            error = None
        except StaleExtraction:
            self._erase_state_if_deleted(claimed)
            return False
        except ValidationError as exc:
            _log_invalid_extraction(exc, claimed, bool(harness and harness.repair_attempted))
            items, metadata, parsed = None, None, {}
            issues = feedback_for(exc)
            error = {'code': 'invalid_extraction', 'message': 'The model returned an invalid extraction. Retry this saved upload.', 'retryable': True,
                     'failure_stage': stage, 'failure_category': 'schema_validation'}
        except ExtractionFailure as exc:
            auto_retry_allowed = exc.auto_retry_allowed
            items, metadata, parsed = None, None, {}
            error = {'code': 'extraction_failed', 'message': str(exc), 'retryable': True,
                     'failure_stage': 'model_repair' if stage == 'model_repair' and exc.stage == 'model_request' else exc.stage,
                     'failure_category': exc.category,
                     'provider_status_code': exc.provider_status_code,
                     'provider_reason': exc.provider_reason, 'provider_parameter': exc.provider_parameter}
        except ModelAdmissionError as exc:
            items, metadata, parsed = None, None, {}
            error = {'code': 'extraction_failed', 'message': str(exc), 'retryable': True,
                     'failure_stage': stage, 'failure_category': 'model_admission'}
        except ValueError as exc:
            items, metadata, parsed = None, None, {}
            message = str(exc)
            if stage == 'extraction_validation': issues = feedback_for(exc)
            category = {'source_read': 'source_unavailable', 'document_parse': 'invalid_document',
                        'extraction_validation': 'evidence_validation'}.get(stage, 'unexpected_error')
            error = {'code': 'extraction_failed', 'message': message if len(message) <= 500 else 'CV extraction failed. Retry this saved upload.', 'retryable': True,
                     'failure_stage': stage, 'failure_category': category}
        except Exception:
            items, metadata, parsed = None, None, {}
            error = {'code': 'processing_failed', 'message': 'CV processing failed. Saved inputs are safe; retry this upload.', 'retryable': True,
                     'failure_stage': stage, 'failure_category': 'unexpected_error'}
        repair_attempted = bool(harness and harness.repair_attempted)
        if error: error['repair_attempted'] = repair_attempted
        # Re-read to apply retained overlays; only the currently live lease can publish.
        current = self.repository.get(claimed['user_id'], claimed['_id'])
        if not current or current['operation']['lease_token'] != token or current['operation']['status'] != 'processing' or current['operation']['lease_until'] <= now():
            self._erase_state_if_deleted(claimed)
            return False
        if error and error.get('failure_category') in _RESTART_AFTER:
            self.repository.extraction_states.discard(claimed['_id'])
        document = deepcopy(current)
        operation = document['operation']
        if not error:
            affected = affected_sources(document, items)
            if affected:
                # No fuzzy/name reassignment of user statements. Keep the usable prior
                # extraction and retain the candidate for an explicit new-source review.
                document['candidate'] = candidate_for(document, items, metadata, parsed.get('notices', []), other_information=result['other_information'])
                document['reconciliation'] = [{'item_id': identifier, 'reason': 'Source interpretation changed. Compare the preserved result and candidate before accepting it.'}
                    for identifier in affected]
                error = {'code': 'reconciliation_required', 'message': 'Reprocessing changed source identities. Your previous result is preserved. Review the saved comparison to continue.', 'retryable': False,
                         'failure_stage': 'publication', 'failure_category': 'source_changed', 'repair_attempted': repair_attempted}
            else:
                before = effective_fingerprint(document)
                if document['original_items']:
                    document['history'].append({'extraction_version': document['extraction_version'],
                                                'original_items': document['original_items'], 'other_information': document.get('other_information', []), 'at': now()})
                document['original_items'] = items
                document['other_information'] = result['other_information']
                document['extraction_version'] += 1
                document['extraction'] = metadata
                document['notices'] = parsed.get('notices', [])
                document['reconciliation'] = []
                if before != effective_fingerprint(document): document['effective_version'] += 1
                operation.update(status='ready', error=None)
                for field in ('last_failure', 'auto_retries', 'auto_retry_limit', 'retry_reason'):
                    operation.pop(field, None)
        if error:
            told_model = failure_for_model(error, issues)
            if told_model: operation['last_failure'] = told_model
            used = operation.get('auto_retries', 0)
            if auto_retry_allowed and should_auto_retry(error) and used < self.settings.extraction_auto_retries:
                delays = self.settings.extraction_retry_delays
                # Back to the queue with the saved state intact; the next run continues from it.
                operation.update(status='queued', error=None, attempt=0, auto_retries=used + 1,
                                 auto_retry_limit=self.settings.extraction_auto_retries,
                                 retry_reason=error.get('failure_category'),
                                 retry_at=now() + delays[min(used, len(delays) - 1)])
            else:
                operation.update(status='failed', error=error)
        operation.update(lease_token=None, lease_until=0)
        try:
            # Extraction/candidate/history content never consumes bookkeeping space.
            bump(document, operational=bool(error and items is None))
        except CvError:
            document = deepcopy(current)
            document['operation'].update(status='failed', lease_token=None, lease_until=0,
                error={'code': 'history_capacity', 'message': 'The extracted result exceeds this CV’s saved history capacity. Previous evidence is safe; keep this source for history and upload a new CV.', 'retryable': False,
                       'failure_stage': 'publication', 'failure_category': 'history_capacity', 'repair_attempted': repair_attempted})
            bump(document, operational=True)
        failure = document['operation'].get('error') or error
        if failure and failure.get('failure_category') != 'schema_validation':
            # Never log exception strings, prompts, provider bodies, URLs or CV text.
            logger.warning('CV extraction failed cv_id=%s operation_id=%s stage=%s category=%s provider_status_code=%s repair_attempted=%s provider_reason=%s provider_parameter=%s',
                _safe_uuid(claimed.get('_id')), _safe_uuid(claimed['operation'].get('id')),
                failure.get('failure_stage'), failure.get('failure_category'), failure.get('provider_status_code'), repair_attempted,
                failure.get('provider_reason'), failure.get('provider_parameter'))
        try:
            self.repository.replace(current, document)
            return True
        except Conflict: return False

    def cleanup(self):
        timestamp = now()
        candidates = self.repository.cleanup_candidates(timestamp, after=self.cleanup_cursor)
        if not candidates and self.cleanup_cursor is not None:
            self.cleanup_cursor = None
            candidates = self.repository.cleanup_candidates(timestamp)
        for candidate in candidates:
            self.cleanup_cursor = candidate['_id']
            try:
                with self.files.lock(candidate['_id'], blocking=False) as acquired:
                    if not acquired: continue
                    current = self.repository.get(candidate['user_id'], candidate['_id'])
                    if not current or not current['original_available'] or current['original_expires_at'] > timestamp: continue
                    if current['operation']['status'] == 'processing' and current['operation']['lease_until'] > timestamp: continue
                    claimed = deepcopy(current)
                    claimed['cleanup_token'] = str(uuid4())
                    if claimed['operation']['status'] in {'queued', 'processing'}:
                        claimed['operation'].update(status='failed', lease_token=None, lease_until=0,
                            error={'code': 'source_expired', 'message': 'The private original expired. Reupload the same file to continue.', 'retryable': False})
                    bump(claimed, operational=True)
                    claimed = self.repository.replace(current, claimed)
                    entry = self.capacity.entry(claimed['_id'])
                    size = self.files.size(claimed['_id'])
                    self.files.remove(claimed['_id'])
                    # Physical deletion precedes credit; a crash can overcount
                    # until recovery, but cannot admit unaccounted original bytes.
                    self.capacity.release_bytes(claimed['_id'], entry['generation'] if entry else None, size)
                    updated = deepcopy(claimed)
                    updated['original_available'] = False
                    updated.pop('cleanup_token', None)
                    bump(updated, operational=True)
                    self.repository.replace(claimed, updated)
            except Exception:
                # Advance the cursor even for malformed/oversized legacy records,
                # filesystem failures or CAS races, so another owner's expiry runs.
                continue
        self.capacity.cleanup_orphans(timestamp - 3600)

    def run_once(self):
        self.deletion.recover()
        self.capacity.recover()
        candidates = self.repository.candidates(now(), after=self.processing_cursor)
        if not candidates and self.processing_cursor is not None:
            self.processing_cursor = None
            candidates = self.repository.candidates(now())
        for candidate in candidates:
            self.processing_cursor = candidate['_id']
            try:
                current = self.repository.get(candidate['user_id'], candidate['_id'])
                if not current or current['operation']['status'] not in {'queued', 'processing'}: continue
                if current['operation']['status'] == 'processing' and current['operation']['lease_until'] > now(): continue
                claimed = self.claim(current)
                if claimed: self.process(claimed)
            except Exception:
                continue
        self.cleanup()

    async def run(self):
        while True:
            try: await asyncio.to_thread(self.run_once)
            except asyncio.CancelledError: raise
            except Exception:
                # Database/transient filesystem failures leave persisted leases for
                # recovery. Avoid logging CV content, response bodies or credentials.
                pass
            await asyncio.sleep(1)

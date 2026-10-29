"""Persisted leased work; fenced publication and cleanup survive process restarts."""
import asyncio
from copy import deepcopy
from uuid import uuid4
from pydantic import ValidationError
from app.domain.capabilities import validate_extraction, effective_fingerprint
from app.domain.errors import Conflict, CvError
from app.domain.service import bump, now
from app.domain.storage import UploadCapacity
from app.domain.model_usage import ModelUsage
from app.domain.reconciliation import candidate_for, affected_sources
from app.parsing.process import isolated_parse


class IngestionWorker:
    def __init__(self, repository, files, settings, extractor, parser=isolated_parse, capacity=None, model_usage=None):
        self.repository, self.files, self.settings = repository, files, settings
        self.extractor, self.parser = extractor, parser
        self.capacity = capacity or UploadCapacity(repository, files, settings)
        self.model_usage = model_usage or ModelUsage(repository.model_usage, files.root, settings)
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
            return None
        operation.update(status='processing', attempt=operation['attempt'] + 1,
                         lease_token=str(uuid4()), lease_until=now() + self.settings.lease_seconds, error=None)
        bump(document, operational=True)
        try: return self.repository.replace(candidate, document)
        except Conflict: return None

    def process(self, claimed):
        token = claimed['operation']['lease_token']
        try:
            if not claimed['original_available'] or not self.files.exists(claimed['_id']):
                raise ValueError('The private original has expired. Reupload the same file to preserve its corrections.')
            parsed = self.parser(self.files.read(claimed['_id']), '.' + claimed['file_type'], self.settings.max_file_bytes)
            output, metadata = self.model_usage.run(claimed['user_id'], self.extractor.extract, parsed['blocks'],
                configured=getattr(self.extractor, 'configured', True))
            items = validate_extraction(output, parsed['blocks'], claimed['_id'])
            error = None
        except ValidationError:
            items, metadata, parsed = None, None, {}
            error = {'code': 'invalid_extraction', 'message': 'The model returned an invalid extraction. Retry this saved upload.', 'retryable': True}
        except ValueError as exc:
            items, metadata, parsed = None, None, {}
            message = str(exc)
            error = {'code': 'extraction_failed', 'message': message if len(message) <= 500 else 'CV extraction failed. Retry this saved upload.', 'retryable': True}
        except Exception:
            items, metadata, parsed = None, None, {}
            error = {'code': 'processing_failed', 'message': 'CV processing failed. Saved inputs are safe; retry this upload.', 'retryable': True}
        # Re-read to apply retained overlays; only the currently live lease can publish.
        current = self.repository.get(claimed['user_id'], claimed['_id'])
        if not current or current['operation']['lease_token'] != token or current['operation']['status'] != 'processing' or current['operation']['lease_until'] <= now():
            return False
        document = deepcopy(current)
        operation = document['operation']
        if not error:
            affected = affected_sources(document, items)
            if affected:
                # No fuzzy/name reassignment of user statements. Keep the usable prior
                # extraction and retain the candidate for an explicit new-source review.
                document['candidate'] = candidate_for(document, items, metadata, parsed.get('notices', []))
                document['reconciliation'] = [{'item_id': identifier, 'reason': 'Source interpretation changed. Compare the preserved result and candidate before accepting it.'}
                    for identifier in affected]
                error = {'code': 'reconciliation_required', 'message': 'Reprocessing changed source identities. Your previous result is preserved. Review the saved comparison to continue.', 'retryable': False}
            else:
                before = effective_fingerprint(document)
                if document['original_items']:
                    document['history'].append({'extraction_version': document['extraction_version'],
                                                'original_items': document['original_items'], 'at': now()})
                document['original_items'] = items
                document['extraction_version'] += 1
                document['extraction'] = metadata
                document['notices'] = parsed.get('notices', [])
                document['reconciliation'] = []
                if before != effective_fingerprint(document): document['effective_version'] += 1
                operation.update(status='ready', error=None)
        if error: operation.update(status='failed', error=error)
        operation.update(lease_token=None, lease_until=0)
        try:
            # Extraction/candidate/history content never consumes bookkeeping space.
            bump(document, operational=bool(error and items is None))
        except CvError:
            document = deepcopy(current)
            document['operation'].update(status='failed', lease_token=None, lease_until=0,
                error={'code': 'history_capacity', 'message': 'The extracted result exceeds this CV’s saved history capacity. Previous evidence is safe; keep this source for history and upload a new CV.', 'retryable': False})
            bump(document, operational=True)
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

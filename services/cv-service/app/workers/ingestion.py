"""Persisted leased work; fenced publication and cleanup survive process restarts."""
import asyncio
from copy import deepcopy
from uuid import uuid4
from pydantic import ValidationError
from app.domain.capabilities import validate_extraction, effective_fingerprint
from app.domain.errors import Conflict
from app.domain.service import bump, now
from app.domain.reconciliation import candidate_for, affected_sources
from app.parsing.process import isolated_parse


class IngestionWorker:
    def __init__(self, repository, files, settings, extractor, parser=isolated_parse):
        self.repository, self.files, self.settings = repository, files, settings
        self.extractor, self.parser = extractor, parser

    def claim(self, candidate):
        document = deepcopy(candidate)
        operation = document['operation']
        if operation['attempt'] >= self.settings.max_attempts:
            operation.update(status='failed', error={'code': 'processing_interrupted',
                'message': 'Processing was repeatedly interrupted. Check status and retry this saved upload.', 'retryable': True})
            bump(document)
            try: self.repository.replace(candidate, document)
            except Conflict: pass
            return None
        operation.update(status='processing', attempt=operation['attempt'] + 1,
                         lease_token=str(uuid4()), lease_until=now() + self.settings.lease_seconds, error=None)
        bump(document)
        try: return self.repository.replace(candidate, document)
        except Conflict: return None

    def process(self, claimed):
        token = claimed['operation']['lease_token']
        try:
            if not claimed['original_available'] or not self.files.exists(claimed['_id']):
                raise ValueError('The private original has expired. Reupload the same file to preserve its corrections.')
            parsed = self.parser(self.files.read(claimed['_id']), '.' + claimed['file_type'], self.settings.max_file_bytes)
            output, metadata = self.extractor.extract(parsed['blocks'])
            items = validate_extraction(output, parsed['blocks'], claimed['_id'])
            error = None
        except ValidationError:
            items, metadata, parsed = None, None, {}
            error = {'code': 'invalid_extraction', 'message': 'The model returned an invalid extraction. Retry this saved upload.', 'retryable': True}
        except ValueError as exc:
            items, metadata, parsed = None, None, {}
            error = {'code': 'extraction_failed', 'message': str(exc), 'retryable': True}
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
        bump(document)
        try:
            self.repository.replace(current, document)
            return True
        except Conflict: return False

    def cleanup(self):
        timestamp = now()
        for candidate in self.repository.cleanup_candidates(timestamp):
            claimed = deepcopy(candidate)
            claimed['cleanup_token'] = str(uuid4())
            if claimed['operation']['status'] in {'queued', 'processing'}:
                claimed['operation'].update(status='failed', lease_token=None, lease_until=0,
                    error={'code': 'source_expired', 'message': 'The private original expired. Reupload the same file to continue.', 'retryable': False})
            bump(claimed)
            try: claimed = self.repository.replace(candidate, claimed)
            except Conflict: continue
            self.files.remove(claimed['_id'])
            # Record deletion after removing bytes; a crash here leaves a tracked,
            # retryable cleanup record, never an untracked private original.
            updated = deepcopy(claimed)
            updated['original_available'] = False
            updated.pop('cleanup_token', None)
            bump(updated)
            try: self.repository.replace(claimed, updated)
            except Conflict: pass
        self.files.cleanup_orphans(self.repository.tracked_paths(), timestamp - 3600)

    def run_once(self):
        for candidate in self.repository.candidates(now()):
            claimed = self.claim(candidate)
            if claimed: self.process(claimed)
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

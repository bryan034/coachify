from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from threading import BoundedSemaphore
from uuid import NAMESPACE_URL, uuid4, uuid5
from bson import BSON
from app.domain.capabilities import digest, effective_items, effective_fingerprint, skills_for, skill_id, normalized_name
from app.domain.errors import Conflict, CvError, Missing
from app.schemas.cv import validate_item_dates
from app.domain.attachments import source_fingerprint
from app.domain.storage import UploadCapacity
from app.domain.answer_capacity import reserved_bytes, release as release_answer_capacity, CAPACITY_MESSAGE
from app.domain.model_usage import ModelUsage


HISTORY_LIMIT_BYTES = 12 * 1024 * 1024
OPERATIONAL_ALLOWANCE_BYTES = 8 * 1024


def now(): return datetime.now(timezone.utc).timestamp()
def iso(value): return datetime.fromtimestamp(value, timezone.utc).isoformat()


def bump(document, visible=True, *, operational=False):
    document['revision'] += 1
    if visible: document['version'] += 1
    document['updated_at'] = now()
    # Fail before Mongo's document-size limit without truncating history or inputs.
    maximum = HISTORY_LIMIT_BYTES + (OPERATIONAL_ALLOWANCE_BYTES if operational else 0)
    size = len(BSON.encode(document))
    if size > maximum:
        raise CvError('This CV has reached its saved history limit. Keep this source for history and upload a new copy.', 409)
    if not operational and size + reserved_bytes(document) > HISTORY_LIMIT_BYTES:
        raise CvError(CAPACITY_MESSAGE, 409)


def summary(document):
    operation = document['operation']
    return {'id': document['_id'], 'file_name': document['file_name'], 'file_type': document['file_type'],
        'status': operation['status'], 'operation_id': operation['id'], 'version': document['version'],
        'extraction_version': document['extraction_version'], 'effective_version': document['effective_version'],
        'profile_version': document['profile_version'],
        'created_at': iso(document['created_at']), 'updated_at': iso(document['updated_at']),
        'error': operation.get('error'), 'source_available': document['original_available']}


def detail(document):
    items = effective_items(document)
    for item in items: item['source_fingerprint'] = source_fingerprint(item)
    return {**summary(document),
        'items': items, 'skills': skills_for(items), 'original_items': document['original_items'],
        'clarifications': document['clarifications'], 'extraction': document['extraction'],
        'notices': document.get('notices', []), 'reconciliation': document.get('reconciliation', []),
        'review_required': document['effective_version'] > 1,
        'reconciliation_candidate_id': document.get('candidate', {}).get('id')}


def selection_view(selection): return {'cv_id': selection['selected_cv_id'], 'version': selection['version']}


class CvService:
    def __init__(self, repository, files, settings):
        self.repository, self.files, self.settings = repository, files, settings
        self.capacity = UploadCapacity(repository, files, settings)
        self.model_usage = ModelUsage(repository.model_usage, files.root, settings)
        self.interpretation_slots = BoundedSemaphore(2)

    def get(self, owner, identifier):
        document = self.repository.get(owner, identifier)
        if not document: raise Missing()
        return document

    def operation(self, owner, identifier):
        document = self.repository.by_operation(owner, identifier)
        if not document: raise Missing()
        return document

    def upload(self, owner, profile_version, name, file_type, data, mutation_id, cv_id=None, expected_version=None):
        source_hash = hashlib.sha256(data).hexdigest()
        fingerprint = digest({'name': name, 'file_type': file_type, 'hash': source_hash,
                              'cv_id': cv_id, 'expected_version': expected_version})
        previous = None if cv_id else self.repository.by_upload_key(owner, mutation_id)
        identifier = cv_id or (previous['_id'] if previous else str(uuid5(NAMESPACE_URL, 'coachify:cv:' + owner + ':' + mutation_id)))
        with self.files.lock(identifier):
            self.capacity.recover_one(identifier)
            try:
                return self._upload(owner, profile_version, name, file_type, data, mutation_id,
                                    cv_id, expected_version, source_hash, fingerprint, identifier)
            except Exception:
                # An uncertain database commit must not delete its original. The
                # same recovery path verifies the durable record before release.
                try: self.capacity.recover_one(identifier)
                except Exception: pass
                raise

    def _upload(self, owner, profile_version, name, file_type, data, mutation_id,
                cv_id, expected_version, source_hash, fingerprint, identifier):
        if cv_id:
            previous = self.get(owner, cv_id)
            replay = previous['receipts'].get(mutation_id)
            if replay:
                if replay != fingerprint: raise Conflict('This mutation key was used for another request.')
                return previous
            if previous.get('cleanup_token'): raise Conflict('Original-file cleanup is running; retry reupload shortly.')
            if previous.get('candidate'): raise Conflict('Resolve the saved source comparison before reprocessing.')
            if previous['version'] != expected_version: raise Conflict()
            if source_hash != previous['source_hash']:
                raise Conflict('This file differs from the saved source. Upload it as a new CV; previous corrections remain with the original.')
            if previous['operation']['status'] in {'queued', 'processing'}:
                raise Conflict('This source is already processing. Check its saved status.')
            generation = self.capacity.reserve(owner, cv_id, len(data), mutation_id, fingerprint, existing=True)
            document = deepcopy(previous)
            document.update(original_available=True, original_expires_at=now() + self.settings.original_retention_hours * 3600,
                            source_bytes=len(data), storage_generation=generation)
            document['operation'] = self.new_operation()
            document['receipts'][mutation_id] = fingerprint
            bump(document)
            self.files.write(cv_id, data)
            saved = self.repository.replace(previous, document)
            self.capacity.commit(cv_id, generation)
            return saved
        previous = self.repository.by_upload_key(owner, mutation_id)
        if previous:
            if previous['upload_fingerprint'] != fingerprint: raise Conflict('This upload key was already used for a different file.')
            return previous
        generation = self.capacity.reserve(owner, identifier, len(data), mutation_id, fingerprint)
        timestamp = now()
        document = {'_id': identifier, 'user_id': owner, 'file_name': name, 'file_type': file_type,
            'source_hash': source_hash, 'upload_key': mutation_id, 'upload_fingerprint': fingerprint,
            'revision': 1, 'version': 1, 'effective_version': 0, 'extraction_version': 0,
            'profile_version': profile_version, 'created_at': timestamp, 'updated_at': timestamp,
            'original_available': True, 'original_expires_at': timestamp + self.settings.original_retention_hours * 3600,
            'source_bytes': len(data), 'storage_generation': generation,
            'operation': self.new_operation(), 'original_items': [], 'overlays': {}, 'clarifications': [],
            'extraction': None, 'receipts': {}, 'history': [], 'reconciliation': [], 'notices': [],
            'prepared_context': None}
        self.files.write(identifier, data)
        saved = self.repository.insert(document)
        if saved['_id'] != identifier:
            self.capacity.recover_one(identifier)
            return saved
        self.capacity.commit(identifier, generation)
        return saved

    @staticmethod
    def new_operation():
        return {'id': str(uuid4()), 'status': 'queued', 'attempt': 0, 'lease_token': None,
                'lease_until': 0, 'error': None}

    def mutate(self, owner, identifier, mutation, operation, transform, *, record_history=True):
        previous = self.get(owner, identifier)
        key = str(mutation.mutation_id)
        fingerprint = digest({'operation': operation, 'data': mutation.model_dump(mode='json', exclude_unset=True)})
        if key in previous['receipts']:
            if previous['receipts'][key] != fingerprint: raise Conflict('This mutation key was used for another request.')
            return previous
        if previous['version'] != mutation.expected_version: raise Conflict()
        if previous['operation']['status'] != 'ready':
            raise Conflict('Wait for this CV to finish processing before editing or clarifying it.')
        if previous.get('candidate'):
            raise Conflict('Resolve the saved source comparison before changing this CV.')
        document = deepcopy(previous)
        before = effective_fingerprint(document)
        transform(document)
        changed = document != previous
        after = effective_fingerprint(document)
        if before != after: document['effective_version'] += 1
        if changed and record_history:
            document['history'].append({'version': previous['version'], 'effective_version': previous['effective_version'],
                'operation': operation, 'overlays': deepcopy(previous['overlays']),
                'clarifications': deepcopy(previous['clarifications']),
                'prepared_context': deepcopy(previous.get('prepared_context')), 'at': now()})
        document['receipts'][key] = fingerprint
        bump(document, visible=changed)
        try: return self.repository.replace(previous, document)
        except Conflict:
            latest = self.get(owner, identifier)
            if latest['receipts'].get(key) == fingerprint: return latest
            raise

    def edit(self, owner, identifier, item_id, mutation):
        def transform(document):
            item = next((item for item in effective_items(document) if item['id'] == item_id), None)
            if item is None: raise Missing()
            if mutation.action == 'remove':
                if item['removed']: return
                patch = {'removed': True, 'provenance': 'user_corrected'}
            else:
                if item['removed']: raise Conflict('This item was removed. Its source and history are retained.')
                patch = mutation.model_dump(exclude_unset=True, exclude={'expected_version', 'mutation_id', 'action'})
                patch = {key: value for key, value in patch.items() if item.get(key) != value}
                if not patch: return
                try: validate_item_dates({**item, **patch})
                except ValueError as exc: raise CvError(str(exc), 422) from exc
                patch['provenance'] = 'user_corrected'
                if 'description' in patch:
                    patch['support_uncertain'] = True
                    patch['evidence'] = [{'id': 'correction:' + item_id, 'location': 'Your correction', 'excerpt': patch['description'][:500]}]
                if item['kind'] == 'skill' and 'title' in patch:
                    # Claim identity stays fixed; explicit renaming updates its canonical
                    # label while retaining distinct evidence/source IDs on a name match.
                    patch['skill_ids'] = [skill_id(patch['title'])]
                    patch['skill_names'] = [patch['title']]
                    patch['evidence'] = [{'id': 'correction:' + item_id, 'location': 'Your correction', 'excerpt': patch.get('description', patch['title'])[:500]}]
            overlay = document['overlays'].setdefault(item_id, {})
            overlay.update(patch)
            overlay.setdefault('_field_sequences', {}).update({field: document['version'] + 1 for field in patch})
            # Narrow factual edits do not invalidate an unrelated explanation of
            # personal contribution. Text/identity/removal changes affect the source.
            broad_change = bool(set(patch) & {'description', 'removed'}) or (
                'title' in patch and normalized_name(patch['title']) != normalized_name(item['title']))
            affected_uncertainties = set()
            if 'proficiency' in patch: affected_uncertainties.add('proficiency')
            if 'experience_months' in patch: affected_uncertainties.add('duration')
            if set(patch) & {'start_date', 'end_date', 'ongoing'}: affected_uncertainties.add('date')
            if broad_change or affected_uncertainties:
                document['prepared_context'] = None
            for question in document['clarifications']:
                if question['item_id'] == item_id and (broad_change or question['uncertainty'] in affected_uncertainties):
                    question['reconciliation_required'] = True
                    release_answer_capacity(question)
        return self.mutate(owner, identifier, mutation, 'item:' + item_id, transform)

    def retry(self, owner, operation_id, mutation):
        previous = self.operation(owner, operation_id)
        fingerprint = digest({'retry': operation_id, 'data': mutation.model_dump(mode='json')})
        key = str(mutation.mutation_id)
        if key in previous['receipts']:
            if previous['receipts'][key] != fingerprint: raise Conflict('This mutation key was used for another request.')
            return previous
        if previous['version'] != mutation.expected_version: raise Conflict()
        if previous.get('candidate'): raise Conflict('Review the saved comparison instead of retrying extraction.')
        if previous['operation']['status'] != 'failed': raise Conflict('Check saved status; only failed operations need retry.')
        if previous.get('cleanup_token'): raise Conflict('Original-file cleanup is running; retry shortly.')
        if not previous['original_available'] or not self.files.exists(previous['_id']):
            raise CvError('The private original has expired. Reupload the same file to this CV to preserve its corrections.', 409)
        document = deepcopy(previous)
        document['operation'].update(status='queued', attempt=0, lease_until=0, lease_token=None, error=None)
        document['receipts'][key] = fingerprint
        bump(document)
        return self.repository.replace(previous, document)

    def select(self, owner, mutation):
        previous = self.repository.selection(owner)
        key = str(mutation.mutation_id)
        fingerprint = digest(mutation.model_dump(mode='json'))
        if key in previous['receipts']:
            if previous['receipts'][key] != fingerprint: raise Conflict('This selection key was used for another request.')
            return previous
        if previous['version'] != mutation.expected_version: raise Conflict('Selection changed. Refresh before selecting a CV.')
        cv = self.get(owner, mutation.cv_id)
        if cv['operation']['status'] != 'ready' or not cv['original_items']:
            raise Conflict('Choose a successfully extracted CV before continuing.')
        document = deepcopy(previous)
        if previous['selected_cv_id'] != mutation.cv_id:
            document['selected_cv_id'] = mutation.cv_id
            document['version'] += 1
        document['receipts'][key] = fingerprint
        document['revision'] = previous.get('revision', 0) + 1
        try: return self.repository.select(previous, document)
        except Conflict:
            latest = self.repository.selection(owner)
            if latest['receipts'].get(key) == fingerprint: return latest
            raise

"""Recoverable owner-scoped erasure across CV records, files and conversations."""
from copy import deepcopy
from time import time
from app.domain.errors import Conflict, Missing


class CvDeletion:
    def __init__(self, repository, files, capacity):
        self.repository, self.files, self.capacity = repository, files, capacity
        self.cursor = None
        self.checkpoint_cursor = None

    def delete(self, owner, identifier, mutation):
        with self.files.lock(identifier):
            previous = self.repository.get_for_deletion(owner, identifier)
            if previous is None: raise Missing()
            if not previous.get('deletion'):
                if previous['version'] != mutation.expected_version: raise Conflict()
                previous = self.repository.replace(previous, {
                    '_id': identifier, 'user_id': owner, 'upload_key': previous['upload_key'],
                    'revision': previous['revision'] + 1, 'version': previous['version'] + 1,
                    'original_available': False,
                    'operation': {'id': previous['operation']['id'], 'status': 'deleted',
                                  'lease_token': None, 'lease_until': 0},
                    'deletion': {'state': 'pending', 'mutation_id': str(mutation.mutation_id), 'at': time()},
                })
            self._finish(previous)
            return {'cv_id': identifier, 'deleted': True,
                    'selection': self.repository.selection(owner)}

    def _finish(self, record):
        owner, identifier = record['user_id'], record['_id']
        self.capacity.mark_deleting(owner, identifier)
        self.repository.extraction_states.erase(identifier)
        if record['deletion']['state'] == 'pending':
            self.files.remove(identifier)
            self.repository.conversations.delete_for_cv(owner, identifier)
            self.repository.clear_selection(owner, identifier)
            complete = deepcopy(record)
            complete['deletion']['state'] = 'complete'
            complete['revision'] += 1
            self.repository.replace(record, complete)
        self.capacity.release_deleted_record(owner, identifier)

    def recover(self):
        self.recover_checkpoints()
        records = self.repository.deletions(self.cursor)
        if not records:
            self.cursor = None
            return
        for candidate in records:
            self.cursor = candidate['_id']
            try:
                with self.files.lock(candidate['_id'], blocking=False) as acquired:
                    if not acquired: continue
                    record = self.repository.get_for_deletion(candidate['user_id'], candidate['_id'])
                    if record and record.get('deletion'): self._finish(record)
            except Exception:
                continue

    def recover_checkpoints(self):
        states = self.repository.extraction_states
        page = states.page(self.checkpoint_cursor, 10)
        self.checkpoint_cursor = page[-1]['_id'] if len(page) == 10 else None
        identifiers = [row['_id'] for row in page if not row.get('erased')]
        if not identifiers: return
        live = self.repository.visible_ids(identifiers)
        for identifier in identifiers:
            if identifier in live: continue
            try:
                with self.files.lock(identifier, blocking=False) as acquired:
                    if not acquired: continue
                    parent = self.repository.capacity_record(identifier)
                    if parent is None: states.delete(identifier)
                    elif parent.get('deletion'): states.erase(identifier)
            except (OSError, ValueError):
                continue

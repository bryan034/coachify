"""In-memory repositories with the same compare-and-set boundaries, for tests that need no MongoDB."""
from app.domain.errors import Conflict
from app.repositories.cv import CAPACITY_FIELDS, SUMMARY_FIELDS
from copy import deepcopy
from threading import RLock


class MemoryConversationRepository:
    def __init__(self): self.records, self.lock = {}, RLock()

    def list(self, owner, cv_id):
        with self.lock:
            return sorted([deepcopy(d) for d in self.records.values() if d['user_id'] == owner and d['cv_id'] == cv_id],
                          key=lambda d: d['segment'], reverse=True)[:100]

    def latest(self, owner, cv_id):
        with self.lock:
            matching = (d for d in self.records.values() if d['user_id'] == owner and d['cv_id'] == cv_id)
            result = max(matching, key=lambda d: d['segment'], default=None)
            return deepcopy(result)

    def count(self, owner, cv_id):
        with self.lock:
            return min(100, sum(d['user_id'] == owner and d['cv_id'] == cv_id for d in self.records.values()))

    def summaries(self, owner, cv_id):
        with self.lock:
            records = sorted((d for d in self.records.values() if d['user_id'] == owner and d['cv_id'] == cv_id),
                             key=lambda d: d['segment'], reverse=True)[:100]
            return [{k: deepcopy(d[k]) for k in ('_id', 'cv_id', 'updated_at', 'message_count', 'at_capacity') if k in d} for d in records]

    def get(self, owner, identifier):
        with self.lock:
            document = self.records.get(identifier)
            return deepcopy(document) if document and document['user_id'] == owner else None

    def delete_for_cv(self, owner, cv_id):
        with self.lock:
            self.records = {identifier: doc for identifier, doc in self.records.items()
                if doc['user_id'] != owner or doc['cv_id'] != cv_id}

    def insert(self, document):
        with self.lock:
            match = next((d for d in self.records.values() if d['user_id'] == document['user_id'] and
                d['cv_id'] == document['cv_id'] and d['segment'] == document['segment']), None)
            if match: return deepcopy(match)
            self.records[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def replace(self, previous, document):
        with self.lock:
            current = self.get(previous['user_id'], previous['_id'])
            if current is None or current['revision'] != previous['revision']:
                raise Conflict('This conversation changed. Refresh to keep your draft and see the latest messages.')
            self.records[document['_id']] = deepcopy(document)
            return deepcopy(document)


class MemoryAdmissionLedger:
    def __init__(self):
        self.document = None
        self.lock = RLock()

    def read(self):
        with self.lock:
            return deepcopy(self.document)

    def replace(self, previous, document):
        with self.lock:
            if (self.document is None) != (previous is None): return False
            if previous is not None and self.document['revision'] != previous['revision']: return False
            self.document = deepcopy(document)
            return True


class MemoryModelUsageStore:
    def __init__(self):
        self.document = None
        self.lock = RLock()

    def read(self):
        with self.lock: return deepcopy(self.document)

    def replace(self, previous, document):
        with self.lock:
            if (self.document is None) != (previous is None): return False
            if previous is not None and self.document['revision'] != previous['revision']: return False
            self.document = deepcopy(document)
            return True


class MemoryExtractionStateStore:
    def __init__(self):
        self.documents = {}
        self.lock = RLock()

    def get(self, identifier):
        with self.lock:
            row = self.documents.get(identifier)
            if row and not row.get('erased'): return deepcopy(row)

    def save(self, document):
        with self.lock:
            if not self.documents.get(document['_id'], {}).get('erased'):
                self.documents[document['_id']] = deepcopy(document)

    def erase(self, identifier):
        with self.lock: self.documents[identifier] = {'_id': identifier, 'erased': True}

    def page(self, after, limit):
        with self.lock:
            ids = sorted(k for k in self.documents if after is None or k > after)[:limit]
            return [{'_id': k, 'erased': self.documents[k].get('erased', False)} for k in ids]

    def set_writes(self, identifier, checkpoint_id, writes):
        with self.lock:
            document = self.documents.get(identifier)
            if document and not document.get('erased') and document['checkpoint_id'] == checkpoint_id:
                document['writes'] = deepcopy(writes)

    def discard(self, identifier):
        with self.lock:
            document = self.documents.get(identifier)
            if document and not document.get('erased'): document['discarded'] = True

    def delete(self, identifier):
        with self.lock:
            if not self.documents.get(identifier, {}).get('erased'): self.documents.pop(identifier, None)


class MemoryCvRepository:
    """Deterministic test adapter implementing the same compare-and-set boundary."""
    def __init__(self):
        self.conversations = MemoryConversationRepository()
        self.admission = MemoryAdmissionLedger()
        self.model_usage = MemoryModelUsageStore()
        self.extraction_states = MemoryExtractionStateStore()
        self.documents, self.selections = {}, {}
        self.lock = RLock()

    def insert(self, document):
        with self.lock:
            previous = self.by_upload_key(document['user_id'], document['upload_key'])
            if previous:
                if previous.get('deletion'): raise Conflict('This upload was deleted. Start a new upload with a new request identity.')
                if previous['upload_fingerprint'] != document['upload_fingerprint']:
                    raise Conflict('This upload key was already used for a different file.')
                return previous
            self.documents[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def get(self, owner, identifier):
        with self.lock:
            doc = self.documents.get(identifier)
            return deepcopy(doc) if doc and doc['user_id'] == owner and not doc.get('deletion') else None

    def get_for_deletion(self, owner, identifier):
        with self.lock:
            doc = self.documents.get(identifier)
            return deepcopy(doc) if doc and doc['user_id'] == owner else None

    def by_upload_key(self, owner, key):
        with self.lock:
            return next((deepcopy(doc) for doc in self.documents.values()
                if doc['user_id'] == owner and doc['upload_key'] == key), None)

    def by_operation(self, owner, identifier):
        return next((doc for doc in self.list(owner) if doc['operation']['id'] == identifier), None)

    def list(self, owner):
        with self.lock:
            return sorted([deepcopy(doc) for doc in self.documents.values() if doc['user_id'] == owner and not doc.get('deletion')],
                          key=lambda doc: doc['created_at'], reverse=True)

    def page(self, owner, limit, after=None):
        with self.lock:
            records = [doc for doc in self.documents.values() if doc['user_id'] == owner and not doc.get('deletion')
                and (after is None or (doc['created_at'], doc['_id']) < after)]
            records.sort(key=lambda doc: (doc['created_at'], doc['_id']), reverse=True)
            return [{key: deepcopy(doc[key]) for key in SUMMARY_FIELDS if key in doc} for doc in records[:limit + 1]]

    def capacity_records(self, limit):
        with self.lock:
            return [{key: deepcopy(doc[key]) for key in CAPACITY_FIELDS if key in doc}
                for doc in self.documents.values() if doc.get('deletion', {}).get('state') != 'complete'][:limit]

    def capacity_record(self, identifier):
        with self.lock:
            doc = self.documents.get(identifier)
            return {key: deepcopy(doc[key]) for key in CAPACITY_FIELDS if key in doc} if doc else None

    def ever_saved(self, owner):
        with self.lock:
            return any(doc['user_id'] == owner for doc in self.documents.values())

    def visible_ids(self, identifiers):
        with self.lock:
            return {key for key in identifiers if key in self.documents and not self.documents[key].get('deletion')}

    def replace(self, previous, document):
        with self.lock:
            current = self.get_for_deletion(previous['user_id'], previous['_id'])
            if not current or current['revision'] != previous['revision']: raise Conflict()
            self.documents[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def candidates(self, now, after=None):
        with self.lock:
            return [{'_id': doc['_id'], 'user_id': doc['user_id']} for doc in sorted(self.documents.values(), key=lambda doc: doc['_id'])
                if (after is None or doc['_id'] > after) and ((doc['operation']['status'] == 'queued' and doc['operation'].get('retry_at', 0) <= now) or
                (doc['operation']['status'] == 'processing' and doc['operation']['lease_until'] <= now))][:10]

    def pending_auto_selections(self):
        with self.lock:
            return [{'_id': cv['_id'], 'user_id': cv['user_id']} for cv in self.documents.values()
                    if 'auto_selection_revision' in cv and not cv.get('deletion')][:10]

    def cleanup_candidates(self, now, after=None):
        with self.lock:
            return [{'_id': doc['_id'], 'user_id': doc['user_id']} for doc in sorted(self.documents.values(), key=lambda doc: doc['_id'])
                if (after is None or doc['_id'] > after) and doc['original_available'] and
                doc['original_expires_at'] <= now and (doc['operation']['status'] != 'processing' or
                doc['operation']['lease_until'] <= now)][:100]

    def deletions(self, after=None):
        with self.lock:
            return [{'_id': doc['_id'], 'user_id': doc['user_id']} for doc in sorted(self.documents.values(), key=lambda doc: doc['_id'])
                if doc.get('deletion', {}).get('state') == 'pending' and (after is None or doc['_id'] > after)][:10]

    def clear_selection(self, owner, identifier):
        with self.lock:
            previous = self.selections.get(owner)
            if previous and previous['selected_cv_id'] == identifier:
                previous['selected_cv_id'] = None
                previous['version'] += 1
                previous['revision'] = previous.get('revision', 0) + 1

    def selection(self, owner):
        with self.lock:
            return deepcopy(self.selections.get(owner, {'_id': owner, 'selected_cv_id': None, 'version': 0, 'revision': 0, 'receipts': {}}))

    def select(self, previous, document):
        with self.lock:
            if self.selection(previous['_id']).get('revision', 0) != previous.get('revision', 0): raise Conflict('Selection changed; refresh before selecting a CV.')
            self.selections[previous['_id']] = deepcopy(document)
            return deepcopy(document)

"""Whole-document CAS publication works on standalone MongoDB without transactions."""
from copy import deepcopy
from threading import RLock
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.domain.errors import Conflict


class CvRepository:
    def __init__(self, database):
        self.collection = database.cvs
        self.selections = database.cv_selections
        self.collection.create_index([('user_id', ASCENDING), ('upload_key', ASCENDING)], unique=True)
        self.collection.create_index([('operation.id', ASCENDING)], unique=True)
        self.collection.create_index([('operation.status', ASCENDING), ('operation.lease_until', ASCENDING)])
        self.collection.create_index([('user_id', ASCENDING), ('created_at', ASCENDING)])

    def insert(self, document):
        try:
            self.collection.insert_one(deepcopy(document))
            return deepcopy(document)
        except DuplicateKeyError:
            previous = self.by_upload_key(document['user_id'], document['upload_key'])
            if previous and previous['upload_fingerprint'] == document['upload_fingerprint']: return previous
            raise Conflict('This upload key was already used for a different file.')

    def get(self, owner, identifier):
        return self.collection.find_one({'_id': identifier, 'user_id': owner})

    def by_upload_key(self, owner, key):
        return self.collection.find_one({'user_id': owner, 'upload_key': key})

    def by_operation(self, owner, identifier):
        return self.collection.find_one({'user_id': owner, 'operation.id': identifier})

    def list(self, owner):
        return list(self.collection.find({'user_id': owner}).sort('created_at', -1))

    def replace(self, previous, document):
        result = self.collection.replace_one({'_id': previous['_id'], 'user_id': previous['user_id'],
                                              'revision': previous['revision']}, deepcopy(document))
        if not result.modified_count: raise Conflict()
        return deepcopy(document)

    def candidates(self, now):
        return list(self.collection.find({'$or': [{'operation.status': 'queued'},
            {'operation.status': 'processing', 'operation.lease_until': {'$lte': now}}]}).limit(10))

    def cleanup_candidates(self, now):
        return list(self.collection.find({'original_expires_at': {'$lte': now}, 'original_available': True,
            '$or': [{'operation.status': {'$ne': 'processing'}}, {'operation.lease_until': {'$lte': now}}]}).limit(100))

    def tracked_paths(self):
        return {doc['_id'] for doc in self.collection.find({'original_available': True}, {'_id': 1})}

    def selection(self, owner):
        return self.selections.find_one({'_id': owner}) or {'_id': owner, 'selected_cv_id': None, 'version': 0, 'revision': 0, 'receipts': {}}

    def select(self, previous, document):
        if previous['version'] == 0:
            try: self.selections.insert_one(deepcopy(document))
            except DuplicateKeyError as exc: raise Conflict('Selection changed; refresh before selecting a CV.') from exc
        elif not self.selections.replace_one({'_id': previous['_id'], 'revision': previous.get('revision', 0)}, deepcopy(document)).modified_count:
            raise Conflict('Selection changed; refresh before selecting a CV.')
        return deepcopy(document)


class MemoryCvRepository:
    """Deterministic test adapter implementing the same compare-and-set boundary."""
    def __init__(self):
        self.documents, self.selections = {}, {}
        self.lock = RLock()

    def insert(self, document):
        with self.lock:
            previous = self.by_upload_key(document['user_id'], document['upload_key'])
            if previous:
                if previous['upload_fingerprint'] != document['upload_fingerprint']:
                    raise Conflict('This upload key was already used for a different file.')
                return previous
            self.documents[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def get(self, owner, identifier):
        with self.lock:
            doc = self.documents.get(identifier)
            return deepcopy(doc) if doc and doc['user_id'] == owner else None

    def by_upload_key(self, owner, key):
        return next((doc for doc in self.list(owner) if doc['upload_key'] == key), None)

    def by_operation(self, owner, identifier):
        return next((doc for doc in self.list(owner) if doc['operation']['id'] == identifier), None)

    def list(self, owner):
        with self.lock:
            return sorted([deepcopy(doc) for doc in self.documents.values() if doc['user_id'] == owner],
                          key=lambda doc: doc['created_at'], reverse=True)

    def replace(self, previous, document):
        with self.lock:
            current = self.get(previous['user_id'], previous['_id'])
            if not current or current['revision'] != previous['revision']: raise Conflict()
            self.documents[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def candidates(self, now):
        with self.lock:
            return [deepcopy(doc) for doc in self.documents.values() if doc['operation']['status'] == 'queued' or
                (doc['operation']['status'] == 'processing' and doc['operation']['lease_until'] <= now)][:10]

    def cleanup_candidates(self, now):
        with self.lock:
            return [deepcopy(doc) for doc in self.documents.values() if doc['original_available'] and
                doc['original_expires_at'] <= now and (doc['operation']['status'] != 'processing' or
                doc['operation']['lease_until'] <= now)][:100]

    def tracked_paths(self):
        with self.lock: return {doc['_id'] for doc in self.documents.values() if doc['original_available']}

    def selection(self, owner):
        with self.lock:
            return deepcopy(self.selections.get(owner, {'_id': owner, 'selected_cv_id': None, 'version': 0, 'revision': 0, 'receipts': {}}))

    def select(self, previous, document):
        with self.lock:
            if self.selection(previous['_id']).get('revision', 0) != previous.get('revision', 0): raise Conflict('Selection changed; refresh before selecting a CV.')
            self.selections[previous['_id']] = deepcopy(document)
            return deepcopy(document)

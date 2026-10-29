"""Whole-document CAS publication works on standalone MongoDB without transactions."""
from copy import deepcopy
from threading import RLock
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.domain.errors import Conflict
from app.repositories.conversations import ConversationRepository, MemoryConversationRepository
from app.repositories.admission import AdmissionLedger, MemoryAdmissionLedger
from app.repositories.model_usage import ModelUsageStore, MemoryModelUsageStore


SUMMARY_FIELDS = {'_id': 1, 'file_name': 1, 'file_type': 1, 'operation': 1,
    'version': 1, 'extraction_version': 1, 'effective_version': 1, 'profile_version': 1,
    'created_at': 1, 'updated_at': 1, 'original_available': 1}
CAPACITY_FIELDS = {'_id': 1, 'user_id': 1, 'original_available': 1, 'storage_generation': 1}


class CvRepository:
    def __init__(self, database):
        self.conversations = ConversationRepository(database)
        self.admission = AdmissionLedger(database)
        self.model_usage = ModelUsageStore(database)
        self.collection = database.cvs
        self.selections = database.cv_selections
        self.collection.create_index([('user_id', ASCENDING), ('upload_key', ASCENDING)], unique=True)
        self.collection.create_index([('operation.id', ASCENDING)], unique=True)
        self.collection.create_index([('operation.status', ASCENDING), ('operation.lease_until', ASCENDING)])
        self.collection.create_index([('user_id', ASCENDING), ('created_at', ASCENDING)])
        self.collection.create_index([('user_id', ASCENDING), ('created_at', -1), ('_id', -1)])

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

    def page(self, owner, limit, after=None):
        query = {'user_id': owner}
        if after:
            timestamp, identifier = after
            query['$or'] = [{'created_at': {'$lt': timestamp}}, {'created_at': timestamp, '_id': {'$lt': identifier}}]
        return list(self.collection.find(query, SUMMARY_FIELDS).sort([('created_at', -1), ('_id', -1)]).limit(limit + 1))

    def capacity_records(self, limit):
        return self.collection.find({}, CAPACITY_FIELDS).limit(limit)

    def capacity_record(self, identifier):
        return self.collection.find_one({'_id': identifier}, CAPACITY_FIELDS)

    def replace(self, previous, document):
        result = self.collection.replace_one({'_id': previous['_id'], 'user_id': previous['user_id'],
                                              'revision': previous['revision']}, deepcopy(document))
        if not result.modified_count: raise Conflict()
        return deepcopy(document)

    def candidates(self, now, after=None):
        query = {'$or': [{'operation.status': 'queued'},
            {'operation.status': 'processing', 'operation.lease_until': {'$lte': now}}]}
        if after is not None: query['_id'] = {'$gt': after}
        return list(self.collection.find(query, {'_id': 1, 'user_id': 1}).sort('_id', 1).limit(10))

    def cleanup_candidates(self, now, after=None):
        query = {'original_expires_at': {'$lte': now}, 'original_available': True,
            '$or': [{'operation.status': {'$ne': 'processing'}}, {'operation.lease_until': {'$lte': now}}]}
        if after is not None: query['_id'] = {'$gt': after}
        return list(self.collection.find(query, {'_id': 1, 'user_id': 1}).sort('_id', 1).limit(100))

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
        self.conversations = MemoryConversationRepository()
        self.admission = MemoryAdmissionLedger()
        self.model_usage = MemoryModelUsageStore()
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

    def page(self, owner, limit, after=None):
        with self.lock:
            records = [doc for doc in self.documents.values() if doc['user_id'] == owner
                and (after is None or (doc['created_at'], doc['_id']) < after)]
            records.sort(key=lambda doc: (doc['created_at'], doc['_id']), reverse=True)
            return [{key: deepcopy(doc[key]) for key in SUMMARY_FIELDS if key in doc} for doc in records[:limit + 1]]

    def capacity_records(self, limit):
        with self.lock:
            return [{key: deepcopy(doc[key]) for key in CAPACITY_FIELDS if key in doc}
                for doc in list(self.documents.values())[:limit]]

    def capacity_record(self, identifier):
        with self.lock:
            doc = self.documents.get(identifier)
            return {key: deepcopy(doc[key]) for key in CAPACITY_FIELDS if key in doc} if doc else None

    def replace(self, previous, document):
        with self.lock:
            current = self.get(previous['user_id'], previous['_id'])
            if not current or current['revision'] != previous['revision']: raise Conflict()
            self.documents[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def candidates(self, now, after=None):
        with self.lock:
            return [{'_id': doc['_id'], 'user_id': doc['user_id']} for doc in sorted(self.documents.values(), key=lambda doc: doc['_id'])
                if (after is None or doc['_id'] > after) and (doc['operation']['status'] == 'queued' or
                (doc['operation']['status'] == 'processing' and doc['operation']['lease_until'] <= now))][:10]

    def cleanup_candidates(self, now, after=None):
        with self.lock:
            return [{'_id': doc['_id'], 'user_id': doc['user_id']} for doc in sorted(self.documents.values(), key=lambda doc: doc['_id'])
                if (after is None or doc['_id'] > after) and doc['original_available'] and
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

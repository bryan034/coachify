"""Whole-document CAS publication works on standalone MongoDB without transactions."""
from copy import deepcopy
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError
from app.domain.errors import Conflict
from app.repositories.conversations import ConversationRepository
from app.repositories.admission import AdmissionLedger
from app.repositories.model_usage import ModelUsageStore
from app.repositories.extraction_state import ExtractionStateStore


SUMMARY_FIELDS = {'_id': 1, 'file_name': 1, 'display_name': 1, 'file_type': 1, 'operation': 1,
    'version': 1, 'extraction_version': 1, 'effective_version': 1, 'profile_version': 1, 'profile_reviewed_effective_version': 1,
    'created_at': 1, 'updated_at': 1, 'original_available': 1}
CAPACITY_FIELDS = {'_id': 1, 'user_id': 1, 'original_available': 1, 'storage_generation': 1, 'deletion': 1}
VISIBLE = {'deletion': {'$exists': False}}


class CvRepository:
    def __init__(self, database):
        self.conversations = ConversationRepository(database)
        self.admission = AdmissionLedger(database)
        self.model_usage = ModelUsageStore(database)
        self.extraction_states = ExtractionStateStore(database)
        self.collection = database.cvs
        self.selections = database.cv_selections
        self.collection.create_index([('user_id', ASCENDING), ('upload_key', ASCENDING)], unique=True)
        self.collection.create_index([('operation.id', ASCENDING)], unique=True)
        self.collection.create_index([('operation.status', ASCENDING), ('operation.lease_until', ASCENDING)])
        self.collection.create_index('auto_selection_revision', sparse=True)
        self.collection.create_index([('user_id', ASCENDING), ('created_at', ASCENDING)])
        self.collection.create_index([('user_id', ASCENDING), ('created_at', -1), ('_id', -1)])

    def insert(self, document):
        try:
            self.collection.insert_one(deepcopy(document))
            return deepcopy(document)
        except DuplicateKeyError:
            previous = self.by_upload_key(document['user_id'], document['upload_key'])
            if previous and previous.get('deletion'): raise Conflict('This upload was deleted. Start a new upload with a new request identity.')
            if previous and previous['upload_fingerprint'] == document['upload_fingerprint']: return previous
            raise Conflict('This upload key was already used for a different file.')

    def get(self, owner, identifier):
        return self.collection.find_one({'_id': identifier, 'user_id': owner, **VISIBLE})

    def get_for_deletion(self, owner, identifier):
        return self.collection.find_one({'_id': identifier, 'user_id': owner})

    def by_upload_key(self, owner, key):
        return self.collection.find_one({'user_id': owner, 'upload_key': key})

    def by_operation(self, owner, identifier):
        return self.collection.find_one({'user_id': owner, 'operation.id': identifier, **VISIBLE})

    def list(self, owner):
        return list(self.collection.find({'user_id': owner, **VISIBLE}).sort('created_at', -1))

    def page(self, owner, limit, after=None):
        query = {'user_id': owner, **VISIBLE}
        if after:
            timestamp, identifier = after
            query['$or'] = [{'created_at': {'$lt': timestamp}}, {'created_at': timestamp, '_id': {'$lt': identifier}}]
        return list(self.collection.find(query, SUMMARY_FIELDS).sort([('created_at', -1), ('_id', -1)]).limit(limit + 1))

    def capacity_records(self, limit):
        return self.collection.find({'deletion.state': {'$ne': 'complete'}}, CAPACITY_FIELDS).limit(limit)

    def capacity_record(self, identifier):
        return self.collection.find_one({'_id': identifier}, CAPACITY_FIELDS)

    def visible_ids(self, identifiers):
        return {row['_id'] for row in self.collection.find({'_id': {'$in': identifiers}, **VISIBLE}, {'_id': 1})}

    def replace(self, previous, document):
        result = self.collection.replace_one({'_id': previous['_id'], 'user_id': previous['user_id'],
                                              'revision': previous['revision']}, deepcopy(document))
        if not result.modified_count: raise Conflict()
        return deepcopy(document)

    def candidates(self, now, after=None):
        query = {'$or': [{'operation.status': 'queued', 'operation.retry_at': {'$not': {'$gt': now}}},
            {'operation.status': 'processing', 'operation.lease_until': {'$lte': now}}]}
        if after is not None: query['_id'] = {'$gt': after}
        return list(self.collection.find(query, {'_id': 1, 'user_id': 1}).sort('_id', 1).limit(10))

    def pending_auto_selections(self):
        query = {'auto_selection_revision': {'$exists': True}, **VISIBLE}
        return list(self.collection.find(query, {'_id': 1, 'user_id': 1}).limit(10))

    def cleanup_candidates(self, now, after=None):
        query = {'original_expires_at': {'$lte': now}, 'original_available': True,
            '$or': [{'operation.status': {'$ne': 'processing'}}, {'operation.lease_until': {'$lte': now}}]}
        if after is not None: query['_id'] = {'$gt': after}
        return list(self.collection.find(query, {'_id': 1, 'user_id': 1}).sort('_id', 1).limit(100))

    def deletions(self, after=None):
        query = {'deletion.state': 'pending'}
        if after is not None: query['_id'] = {'$gt': after}
        return list(self.collection.find(query, {'_id': 1, 'user_id': 1}).sort('_id', 1).limit(10))

    def clear_selection(self, owner, identifier):
        self.selections.update_one({'_id': owner, 'selected_cv_id': identifier},
            {'$set': {'selected_cv_id': None}, '$inc': {'version': 1, 'revision': 1}})

    def selection(self, owner):
        return self.selections.find_one({'_id': owner}) or {'_id': owner, 'selected_cv_id': None, 'version': 0, 'revision': 0, 'receipts': {}}

    def select(self, previous, document):
        if previous['version'] == 0:
            try: self.selections.insert_one(deepcopy(document))
            except DuplicateKeyError as exc: raise Conflict('Selection changed; refresh before selecting a CV.') from exc
        elif not self.selections.replace_one({'_id': previous['_id'], 'revision': previous.get('revision', 0)}, deepcopy(document)).modified_count:
            raise Conflict('Selection changed; refresh before selecting a CV.')
        return deepcopy(document)

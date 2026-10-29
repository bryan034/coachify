"""Bounded operational history separate from authoritative CV evidence."""
from copy import deepcopy
from threading import RLock
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError
from app.domain.errors import Conflict


class ConversationRepository:
    def __init__(self, database):
        self.collection = database.cv_conversations
        self.collection.create_index([('user_id', ASCENDING), ('context_key', ASCENDING), ('segment', ASCENDING)], unique=True)
        self.collection.create_index([('user_id', ASCENDING), ('updated_at', ASCENDING)])

    def list(self, owner, cv_id):
        return list(self.collection.find({'user_id': owner, 'cv_id': cv_id}).sort('segment', -1).limit(100))

    def latest(self, owner, cv_id):
        return self.collection.find_one({'user_id': owner, 'cv_id': cv_id}, sort=[('segment', -1)])

    def count(self, owner, cv_id):
        return self.collection.count_documents({'user_id': owner, 'cv_id': cv_id}, limit=100)

    def summaries(self, owner, cv_id):
        return list(self.collection.find({'user_id': owner, 'cv_id': cv_id},
            {'_id': 1, 'cv_id': 1, 'updated_at': 1, 'message_count': 1, 'at_capacity': 1}).sort('segment', -1).limit(100))

    def get(self, owner, identifier):
        return self.collection.find_one({'user_id': owner, '_id': identifier})

    def insert(self, document):
        try: self.collection.insert_one(deepcopy(document))
        except DuplicateKeyError:
            return self.collection.find_one({'user_id': document['user_id'], 'context_key': document['context_key'], 'segment': document['segment']})
        return deepcopy(document)

    def replace(self, previous, document):
        if not self.collection.replace_one({'_id': previous['_id'], 'user_id': previous['user_id'],
                'revision': previous['revision']}, deepcopy(document)).modified_count:
            raise Conflict('This conversation changed. Refresh to keep your draft and see the latest messages.')
        return deepcopy(document)


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

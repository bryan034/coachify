"""Bounded operational history separate from authoritative CV evidence."""
from copy import deepcopy
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

    def delete_for_cv(self, owner, cv_id):
        self.collection.delete_many({'user_id': owner, 'cv_id': cv_id})

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

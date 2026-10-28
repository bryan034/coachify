"""Private CAS records. Authentication and consent belong to future API handlers."""
from bson import ObjectId
from bson.codec_options import CodecOptions
from pymongo.errors import DuplicateKeyError
from app.domain.analysis import ContractConflict
from app.schemas.analysis import mongo_document, object_id
from app.schemas.exploration import ExplorationSession, StoredOperation

TYPES = {'exploration_sessions': ExplorationSession, 'ai_operations': StoredOperation}


class ExplorationRepository:
    def __init__(self, database):
        self.database = database.with_options(codec_options=CodecOptions(tz_aware=True))

    def ensure_indexes(self):
        for collection in TYPES:
            self.database[collection].create_index([('user_id', 1), ('updated_at', -1)])

    def save(self, collection, data, owner, expected_version):
        record = TYPES[collection].model_validate(data)
        if record.user_id != owner or record.version != expected_version + 1:
            raise ContractConflict('Owner or version mismatch.')
        if collection == 'exploration_sessions' and record.selected_career_goal_id:
            if not self.database.career_goals.find_one({'_id': ObjectId(record.selected_career_goal_id), 'user_id': owner}):
                raise ContractConflict('Selected career goal is missing or belongs to another user.')
        if collection == 'ai_operations' and record.status == 'succeeded':
            result_collection = {'chat': 'exploration_sessions', 'extraction': 'career_goals',
                'guidance': 'career_goals', 'research': 'interview_research', 'gap_analysis': 'skill_gap_analyses'}[record.stage]
            query = {'_id': ObjectId(record.result_id)}
            if result_collection != 'interview_research':
                query['user_id'] = owner
            if not self.database[result_collection].find_one(query):
                raise ContractConflict('Completed operation must reference a saved result.')
        previous = self.get(collection, record.id, owner)
        if collection == 'ai_operations' and previous and previous.status in ('succeeded', 'cancelled', 'failed') and previous != record:
            raise ContractConflict('Terminal operations are immutable. Retry with a new operation ID.')
        if previous and record.created_at != previous.created_at:
            raise ContractConflict('Creation timestamp is immutable.')
        payload = mongo_document(record)
        if expected_version == 0:
            try:
                self.database[collection].insert_one(payload)
            except DuplicateKeyError:
                existing = self.get(collection, record.id, owner)
                if existing != record:
                    raise ContractConflict('Record changed. Reload before retrying.') from None
        else:
            changed = self.database[collection].replace_one({'_id': payload['_id'], 'user_id': owner,
                'version': expected_version}, payload).matched_count
            if not changed:
                existing = self.get(collection, record.id, owner)
                if existing != record:
                    raise ContractConflict('Record changed. Reload before retrying.')
        return record

    def get(self, collection, identifier, owner):
        data = self.database[collection].find_one({'_id': ObjectId(object_id(identifier)), 'user_id': owner})
        return TYPES[collection].model_validate(data) if data else None

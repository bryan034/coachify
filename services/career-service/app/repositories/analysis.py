"""Opt-in Career persistence boundary; not mounted by the preview API.

Only validated structured records cross this boundary; revisions are immutable.
"""
from bson.codec_options import CodecOptions
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import BSON, ObjectId
from app.domain.analysis import ContractConflict
from app.schemas.analysis import CareerGoal, InterviewResearch, mongo_document, object_id

COLLECTIONS = {'career_goals': CareerGoal, 'interview_research': InterviewResearch}


class AnalysisRepository:
    def __init__(self, database):
        self.database = database.with_options(codec_options=CodecOptions(tz_aware=True))

    def ensure_indexes(self):
        self.database.career_goals.create_index([('user_id', ASCENDING), ('created_at', DESCENDING)])
        self.database.interview_research.create_index([('context_key', ASCENDING), ('updated_at', DESCENDING)])
        self.database.interview_research.create_index([('context_key', ASCENDING), ('version', ASCENDING)], unique=True)

    def save_research(self, data, *, trusted_sources):
        """Only an internal retrieval worker may call this, after source verification."""
        record = InterviewResearch.model_validate(data)
        if any(source != trusted_sources.get(source.source_id) for source in record.sources):
            raise ContractConflict('Research sources must match verified public retrieval records.')
        return self._insert('interview_research', record)

    def _insert(self, name, record):
        payload = mongo_document(record)
        if name == 'interview_research':
            payload['context_key'] = record.context_key
            if record.intelligence:
                for key in ('process','skills','summaries','coverage'):payload.pop(key,None)
        try:
            self.database[name].insert_one(payload)
        except DuplicateKeyError:
            existing = self.database[name].find_one({'_id': payload['_id']})
            if existing is None or BSON.encode(existing) != BSON.encode(payload):
                raise ContractConflict('Revision ID already used with different content.') from None
        return record

    def get_private(self, collection, identifier, owner):
        if collection != 'career_goals':
            raise ValueError('Unsupported private collection.')
        data = self.database[collection].find_one({'_id': ObjectId(object_id(identifier)), 'user_id': owner})
        return COLLECTIONS[collection].model_validate({k:v for k,v in data.items() if k in COLLECTIONS[collection].model_fields or k=='_id'}) if data else None

    def get_research(self, identifier):
        data = self.database.interview_research.find_one({'_id': ObjectId(object_id(identifier))})
        if data:
            data.pop('context_key', None)
            return InterviewResearch.model_validate(data)
        return None

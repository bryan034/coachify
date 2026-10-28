"""Opt-in Career persistence boundary; not mounted by the preview API.

Only validated structured records cross this boundary. Stable revision IDs plus the unique
_id index make retries idempotent; revisions are immutable. Foreign
snapshots are supplied by the authenticated orchestration layer, never Mongo.
"""
from bson.codec_options import CodecOptions
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from app.domain.analysis import ContractConflict, validate_analysis
from app.schemas.analysis import CareerGoal, InterviewResearch, SkillGapAnalysis, mongo_document

COLLECTIONS = {'career_goals': CareerGoal, 'interview_research': InterviewResearch,
               'skill_gap_analyses': SkillGapAnalysis}


class AnalysisRepository:
    def __init__(self, database):
        self.database = database.with_options(codec_options=CodecOptions(tz_aware=True))

    def ensure_indexes(self):
        # _id identifies an immutable revision; logical ID/version pairing is
        # handled by callers selecting a new revision and pinning its exact ID.
        for name in ('career_goals', 'skill_gap_analyses'):
            self.database[name].create_index([('user_id', ASCENDING), ('created_at', DESCENDING)])
        self.database.interview_research.create_index([('context_key', ASCENDING), ('updated_at', DESCENDING)])
        self.database.interview_research.create_index([('context_key', ASCENDING), ('version', ASCENDING)], unique=True)

    def save_private(self, collection, data, owner, *, cv=None, goal=None, research=(), profile_version=None):
        if collection not in ('career_goals', 'skill_gap_analyses'):
            raise ValueError('Private writes cannot access shared collections.')
        record = COLLECTIONS[collection].model_validate(data)
        if record.user_id != owner:
            raise ContractConflict('Record ownership mismatch.')
        if collection == 'skill_gap_analyses':
            # Existence of Career-owned references is checked here, not inferred
            # from a caller-supplied DTO. Foreign CV/Profile snapshots come via APIs.
            stored_goal = self.get_private('career_goals', record.career_goal_id, owner)
            if stored_goal is None or goal != stored_goal:
                raise ContractConflict('Referenced career goal is missing or changed.')
            stored_research = [self.get_research(identifier) for identifier in record.research_ids]
            if any(r is None for r in stored_research) or list(research) != stored_research:
                raise ContractConflict('Referenced research is missing or changed.')
            validate_analysis(record, cv, stored_goal, stored_research, profile_version)
        return self._insert(collection, record)

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
            # BSON timestamps have millisecond precision.
            from bson import BSON
            if existing is None or BSON.encode(existing) != BSON.encode(payload):
                raise ContractConflict('Revision ID already used with different content.') from None
        return record

    def get_private(self, collection, identifier, owner):
        if collection not in ('career_goals', 'skill_gap_analyses'):
            raise ValueError('Unsupported private collection.')
        from bson import ObjectId
        from app.schemas.analysis import object_id
        data = self.database[collection].find_one({'_id': ObjectId(object_id(identifier)), 'user_id': owner})
        return COLLECTIONS[collection].model_validate({k:v for k,v in data.items() if k in COLLECTIONS[collection].model_fields or k=='_id'}) if data else None

    def get_research(self, identifier):
        from bson import ObjectId
        from app.schemas.analysis import object_id
        data = self.database.interview_research.find_one({'_id': ObjectId(object_id(identifier))})
        if data:
            data.pop('context_key', None)
            return InterviewResearch.model_validate(data)
        return None

    def reusable_research(self, context, researched_after, mapping_version):
        # Only verified successful/no-findings records qualify. Caller decides
        # the freshness threshold; this lookup never triggers public retrieval.
        if researched_after.tzinfo is None:
            raise ValueError('Freshness threshold must be timezone-aware.')
        data = self.database.interview_research.find_one({'context_key': context.reuse_key(),
            'research_status': {'$in': ['succeeded', 'no_findings']},
            'last_researched_at': {'$gte': researched_after}, 'skill_mapping_version': mapping_version},
            sort=[('version', -1)])
        if data:
            data.pop('context_key', None)
            return InterviewResearch.model_validate(data)
        return None

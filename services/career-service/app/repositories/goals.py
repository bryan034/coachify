"""J08/J09 atomic private draft updates and explicit, idempotent selection.

No MongoDB transactions/topology requirement. Confirmed revisions are inserted
before selection CAS; a losing writer may leave an unselected historical goal,
but can never replace the winner or erase its target.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from bson.codec_options import CodecOptions
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.schemas.analysis import CareerGoal, mongo_document
from app.schemas.goals import GoalDraft


class GoalError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def now():
    value = datetime.now(timezone.utc)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def stable_id(owner, key, prefix):
    return str(ObjectId(hashlib.sha256(f'{prefix}:{owner}:{key}'.encode()).hexdigest()[:24]))


class GoalStore:
    def __init__(self, database):
        self.db = database.with_options(codec_options=CodecOptions(tz_aware=True))
        self.goals, self.state = self.db.career_goals, self.db.career_state

    def ensure_indexes(self):
        self.goals.create_index([('user_id', 1), ('created_at', -1)])
        self.goals.create_index([('user_id', 1), ('record_type', 1), ('updated_at', -1)])

    def draft(self, identifier, owner):
        data = self.goals.find_one({'_id': ObjectId(identifier), 'user_id': owner, 'record_type': 'exploration_draft'})
        if not data:
            raise GoalError('Exploration was not found.', 404)
        for key in ('processing', 'receipts', 'start_hash', 'create_key'):
            data.pop(key, None)
        return GoalDraft.model_validate(data)

    def start(self, owner, key, body, cv):
        identifier = stable_id(owner, key, 'draft')
        digest = fingerprint(body)
        existing = self.goals.find_one({'_id': ObjectId(identifier), 'user_id': owner})
        if existing:
            if existing.get('start_hash') != digest:
                raise GoalError('This request key was already used with different details.')
            return self.draft(identifier, owner)
        stamp = now()
        data = GoalDraft(_id=identifier, user_id=owner, version=1, skill_mapping_version='skills-v1',
            created_at=stamp, updated_at=stamp, cv=cv)
        payload = mongo_document(data); payload.update(start_hash=digest, receipts=[])
        try:
            self.goals.insert_one(payload)
        except DuplicateKeyError:
            return self.start(owner, key, body, cv)
        return data

    def replay_turn(self, identifier, owner, key, digest):
        data = self.goals.find_one({'_id': ObjectId(identifier), 'user_id': owner, 'record_type': 'exploration_draft'})
        if not data:
            raise GoalError('Exploration was not found.', 404)
        receipt = next((r for r in data.get('receipts', []) if r['key'] == key), None)
        if receipt:
            if receipt['hash'] != digest:
                raise GoalError('This request key was already used for another answer.')
            return self.draft(identifier, owner)
        return None

    def claim_turn(self, identifier, owner, version, key, digest):
        lease = {'key': key, 'hash': digest, 'expires_at': now() + timedelta(seconds=75)}
        data = self.goals.find_one_and_update({'_id': ObjectId(identifier), 'user_id': owner,
            'record_type': 'exploration_draft', 'version': version,
            '$or': [{'processing': {'$exists': False}}, {'processing.expires_at': {'$lt': now()}}]},
            {'$set': {'processing': lease}}, return_document=ReturnDocument.AFTER)
        if not data:
            raise GoalError('This exploration changed or is processing. Reload before retrying.')
        return self.draft(identifier, owner)

    def release_turn(self, identifier, owner, key):
        self.goals.update_one({'_id': ObjectId(identifier), 'user_id': owner, 'processing.key': key}, {'$unset': {'processing': ''}})

    def finish_turn(self, draft, owner, expected, key, digest):
        payload = mongo_document(draft)
        payload.pop('_id')
        changed = self.goals.update_one({'_id': ObjectId(draft.id), 'user_id': owner,
            'version': expected, 'processing.key': key}, {'$set': payload, '$unset': {'processing': ''},
            '$push': {'receipts': {'$each': [{'key': key, 'hash': digest}], '$slice': -100}}}).modified_count
        if not changed:
            raise GoalError('A newer change arrived. Reload the exploration.')
        return draft

    def current(self, owner):
        state = self.state.find_one({'_id': owner}) or {'version': 0, 'goal_id': None}
        goal = self.goals.find_one({'_id': state.get('goal_id'), 'user_id': owner}) if state.get('goal_id') else None
        return {'selection_version': state['version'], 'goal': CareerGoal.model_validate({k:v for k,v in goal.items() if k in CareerGoal.model_fields or k=='_id'}) if goal else None,
                'dependent_results_need_review': state.get('dependent_results_need_review', False),
                'review_selection':state.get('selected_review') or ({'id':str(goal['source_review_id']),'version':goal['source_review_version']} if goal and goal.get('source_review_id') else None)}

    def list(self, owner):
        goals = list(self.goals.find({'user_id': owner, '_id': {'$type':'objectId'}, 'record_type': {'$nin': ['exploration_draft', 'requirement_review']}}).sort('created_at', -1).limit(50))
        drafts = list(self.goals.find({'user_id': owner, 'record_type': 'exploration_draft'}).sort('updated_at', -1).limit(10))
        return {'goals': [CareerGoal.model_validate({k:v for k,v in g.items() if k in CareerGoal.model_fields or k=='_id'}) for g in goals],
                'explorations': [self.draft(str(d['_id']), owner) for d in drafts]}

    def replay_confirmation(self, owner, key, data):
        state=self.state.find_one({'_id':owner})
        if not state: return None
        receipt=next((r for r in state.get('receipts',[]) if r['key']==key),None)
        if receipt:
            if receipt['hash']!=fingerprint(data.model_dump(mode='json')):
                raise GoalError('This request key was already used with different goal details.')
            return self.current(owner)
        return None

    def persist_target(self, goal):
        """Shared final persistence for JD, discovery and reviewed goal revisions."""
        payload=mongo_document(CareerGoal.model_validate(goal))
        draft=self.goals.find_one({'_id':payload['_id'],'user_id':goal.user_id,'record_type':'requirement_review'})
        if draft:
            # Promote the same record: source content is replaced by the canonical goal.
            payload.update({k:draft[k] for k in ('source_hash','receipts') if k in draft})
            result=self.goals.replace_one({'_id':payload['_id'],'user_id':goal.user_id,'record_type':'requirement_review','version':goal.version},payload)
            if not result.matched_count:raise GoalError('The goal changed while saving.')
            return payload
        try:self.goals.insert_one(payload)
        except DuplicateKeyError:
            existing=self.goals.find_one({'_id':payload['_id'],'user_id':goal.user_id})
            if not existing:raise GoalError('This target could not be recovered.')
            previous=CareerGoal.model_validate({k:v for k,v in existing.items() if k in CareerGoal.model_fields or k=='_id'})
            fields=set(CareerGoal.model_fields)-{'created_at','updated_at'}
            if any(getattr(previous,f)!=getattr(goal,f) for f in fields):
                raise GoalError('This request key was used for another target.')
            payload=mongo_document(previous)
        return payload

    def confirm(self, owner, key, data, prepared_goal=None):
        digest = fingerprint(data.model_dump(mode='json'))
        self.state.update_one({'_id': owner}, {'$setOnInsert': {'version': 0, 'goal_id': None, 'receipts': []}}, upsert=True)
        state = self.state.find_one({'_id': owner})
        receipt = next((r for r in state.get('receipts', []) if r['key'] == key), None)
        if receipt:
            if receipt['hash'] != digest:
                raise GoalError('This request key was already used with different goal details.')
            return self.current(owner)
        if state['version'] != data.expected_selection_version:
            raise GoalError('Your selected goal changed. Reload before confirming.')
        draft = self.draft(data.draft_id, owner) if data.draft_id else None
        if draft and draft.version != data.expected_draft_version:
            raise GoalError('The suggestions changed. Review the latest version.')
        if draft and draft.next_question():
            raise GoalError('Answer or skip each exploration question before confirming.')
        stamp = now()
        goal = prepared_goal if prepared_goal is not None else CareerGoal(_id=stable_id(owner, key, 'goal'), user_id=owner, version=1,
            skill_mapping_version='skills-v1', created_at=stamp, updated_at=stamp,
            target_type=data.target_type, field=data.field, role=data.role, company=data.company,
            location=data.location, seniority_level=data.seniority_level, job_url=data.job_url,employment_type=data.employment_type,
            interests=draft.interests if draft else [], preferences=draft.preferences if draft else [],
            skills=[], requirements_source='career_exploration' if data.target_type == 'career_exploration' else 'url_jd' if data.job_url else 'pasted_jd',
            generation_version='pending-skills', generation=draft.generation if draft else None, readiness='pending',
            exploration_draft_id=draft.id if draft else None, exploration_draft_version=draft.version if draft else None,
            source_cv_id=draft.cv.cv_id if draft else None, source_cv_version=draft.cv.version if draft else None,
            source_extraction_version=draft.cv.extraction_version if draft else None, source_profile_version=draft.cv.profile_version if draft else None)
        # Metadata-equivalent confirmation is a no-op, not a new selection/version.
        previous = self.current(owner)['goal']
        fields = ('discovery','target_type','field','role','employment_type','company','location','seniority_level','job_url','interests','preferences','source_cv_id','source_cv_version','source_extraction_version','source_profile_version','exploration_draft_id','exploration_draft_version','skills','non_skill_requirements','summary','responsibilities','readiness','requirements_need_review','skill_mapping_version')
        if previous and all(getattr(previous, f) == getattr(goal, f) for f in fields):
            receipt={'key':key,'hash':digest}
            changed=self.state.update_one({'_id':owner,'version':state['version'],'receipts.key':{'$ne':key}},
                {'$set':{'selected_review':{'id':goal.source_review_id,'version':goal.source_review_version} if goal.source_review_id else None},'$push':{'receipts':{'$each':[receipt],'$slice':-100}}}).modified_count
            if not changed and not self.state.find_one({'_id':owner,'receipts':{'$elemMatch':receipt}}):
                raise GoalError('Another goal was selected. Reload before retrying.')
            return self.current(owner)
        if state.get('goal_id') and not data.replace_current:
            raise GoalError('Confirm explicitly that you want to replace your selected goal.')
        payload = self.persist_target(goal)
        receipt = {'key': key, 'hash': digest}
        discovery_workspace={}
        if goal.discovery:
            discovery_workspace={'workspace':{'session_id':goal.source_review_id,'kind':'exploration','review_id':goal.source_review_id,'revision':goal.source_review_version,
                'run_id':str(ObjectId()),'phase':'ready','research_id':None,'coverage':[],'error':None,'error_code':None,'retry_after':None,'expires_at':now()+timedelta(hours=24)}}
        changed = self.state.update_one({'_id': owner, 'version': state['version']},
            {'$set': {**discovery_workspace,'goal_id': payload['_id'], 'dependent_results_need_review': bool(previous),
                       'selected_review':{'id':goal.source_review_id,'version':goal.source_review_version} if goal.source_review_id else None},
             '$inc': {'version': 1}, '$push': {'receipts': {'$each': [receipt], '$slice': -100}}}).modified_count
        if not changed:
            replay = self.state.find_one({'_id': owner, 'receipts': {'$elemMatch': receipt}})
            if not replay:
                raise GoalError('Another goal was selected. Reload before retrying.')
        return self.current(owner)

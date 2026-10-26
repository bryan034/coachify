"""Owner-scoped structured reviews. No JD buffers cross this persistence boundary."""
from datetime import timedelta
from uuid import uuid5, NAMESPACE_URL
from bson import ObjectId
from bson.codec_options import CodecOptions
from pymongo.errors import DuplicateKeyError
from pydantic import ValidationError
from app.domain.review import METADATA, MAPPING_VERSION, prepare
from app.repositories.goals import GoalError, fingerprint, now, stable_id
from app.schemas.analysis import CareerGoal, TargetSkill, mongo_document
from app.schemas.jd import JDExtraction, RequirementReview


class ReviewStore:
    def __init__(self, database):
        db=database.with_options(codec_options=CodecOptions(tz_aware=True))
        self.rows,self.state=db.career_goals,db.career_state

    def _row(self, identifier, owner):
        row = self.rows.find_one({'_id': ObjectId(identifier), 'user_id': owner})
        if not row or row.get('record_type') == 'exploration_draft':
            raise GoalError('Career goal review was not found.', 404)
        return row

    def get(self, identifier, owner):
        row = self._row(identifier, owner)
        if row.get('record_type') == 'requirement_review':
            return RequirementReview.model_validate({k:v for k,v in row.items() if k not in ('receipts','source_hash','processing')})
        goal = CareerGoal.model_validate(row)
        source_review = self.get(goal.source_review_id, owner) if goal.source_review_id else None
        baseline = source_review.baseline if source_review else None
        baseline_origins = source_review.baseline_origins if source_review else {f:'user' for f in METADATA}
        content = JDExtraction(role=goal.role, field=goal.field, company=goal.company, location=goal.location,
            seniority_level=goal.seniority_level, employment_type=goal.employment_type, job_url=goal.job_url, summary=goal.summary, responsibilities=goal.responsibilities,
            skills=[s.model_dump(mode='json') for s in goal.skills], non_skill_requirements=goal.non_skill_requirements)
        for index,skill in enumerate(content.skills):
            if not skill.item_id: skill.item_id=str(uuid5(NAMESPACE_URL,f'coachify:{goal.id}:skill:{index}'))
        return RequirementReview(_id=goal.id, user_id=owner, version=goal.version, skill_mapping_version=goal.skill_mapping_version,
            created_at=goal.created_at, updated_at=goal.updated_at, target_type=goal.target_type,
            source_kind={'pasted_jd':'text','url_jd':'url','document_jd':'document','career_exploration':'career_exploration'}[goal.requirements_source],
            content=content, baseline=baseline or content, generation=goal.generation,
            requirements_need_review=goal.requirements_need_review, base_goal_id=goal.id,
            baseline_origins=baseline_origins,
            metadata_origins={f:baseline_origins.get(f,'extracted') if getattr(content,f)==getattr(baseline or content,f) else 'user' for f in METADATA})

    def replay_extraction(self, owner, key, digest):
        row = self.rows.find_one({'_id': ObjectId(stable_id(owner,key,'jd-review')), 'user_id':owner})
        if not row: return None
        if row.get('source_hash') != digest:
            raise GoalError('This extraction key was used for a different description.')
        return self.get(str(row['_id']),owner)

    def create(self, owner, key, digest, content, generation, source_kind):
        replay = self.replay_extraction(owner,key,digest)
        if replay: return replay
        stamp = now()
        prepared = prepare(content, extracted=True)
        draft = RequirementReview(_id=stable_id(owner,key,'jd-review'), user_id=owner, version=1,
            skill_mapping_version=MAPPING_VERSION, created_at=stamp, updated_at=stamp,
            source_kind=source_kind, content=prepared, baseline=prepared, generation=generation,
            metadata_origins={field:'extracted' for field in METADATA},baseline_origins={field:'extracted' for field in METADATA})
        payload = mongo_document(draft); payload.update(source_hash=digest, receipts=[])
        try: self.rows.insert_one(payload)
        except DuplicateKeyError: return self.replay_extraction(owner,key,digest)
        return draft

    def version(self, identifier, owner):
        return self._row(identifier,owner)['version']

    def _fork_replay(self, owner, identifier, key, digest):
        state=self.state.find_one({'_id':owner}) or {}
        receipt=next((r for r in state.get('review_receipts',[]) if r['source']==identifier and r['key']==key),None)
        if receipt:
            if receipt['hash']!=digest: raise GoalError('This save key was used with different edits.')
            return self.get(receipt['result'],owner)
        return None

    def _record_fork(self, owner, identifier, key, digest, result):
        self.state.update_one({'_id':owner},{'$setOnInsert':{'version':0,'goal_id':None,'receipts':[]}},upsert=True)
        self.state.update_one({'_id':owner,'review_receipts':{'$not':{'$elemMatch':{'source':identifier,'key':key}}}},
            {'$push':{'review_receipts':{'$each':[{'source':identifier,'key':key,'hash':digest,'result':result.id}],'$slice':-100}}})
        return self._fork_replay(owner,identifier,key,digest)

    def save(self, identifier, owner, key, body):
        row = self._row(identifier, owner)
        digest = fingerprint(body.model_dump(mode='json'))
        if row.get('record_type')!='requirement_review':
            replay=self._fork_replay(owner,identifier,key,digest)
            if replay:return replay
        for receipt in row.get('receipts',[]):
            if receipt['key'] == key:
                if receipt['hash'] != digest: raise GoalError('This save key was used with different edits.')
                return self.get(identifier,owner)
        draft = self.get(identifier,owner)
        if draft.version != body.expected_version:
            raise GoalError('This review changed in another request. Reload it before saving.')
        if body.reset:
            content = draft.baseline.model_copy(deep=True) if body.reset == 'all' else draft.content.model_copy(update={f:getattr(draft.baseline,f) for f in METADATA},deep=True)
        else: content = body.content
        content = prepare(content, draft.content)
        if draft.target_type == 'career_exploration' and (any(s.origin == 'employer' for s in content.skills) or any(r.origin == 'employer' for r in content.non_skill_requirements)):
            raise GoalError('Exploration considerations must be user declarations or suggested guidance.',422)
        contextual = any(getattr(content,f) != getattr(draft.content,f) for f in METADATA)
        needs_review = (draft.requirements_need_review or contextual) and not body.acknowledge_context and body.reset != 'all'
        originals={s.item_id:s.model_dump(mode='json') for s in draft.baseline.skills}
        originals.update({r.requirement_id:r.model_dump(mode='json') for r in draft.baseline.non_skill_requirements})
        for item in [*content.skills,*content.non_skill_requirements]:
            identity=item.item_id if hasattr(item,'item_id') else item.requirement_id
            original=originals.get(identity,{})
            comparable=lambda value:{k:v for k,v in value.items() if k not in ('correction','priority_origin')}
            if comparable(item.model_dump(mode='json'))==comparable(original):
                item.priority_origin=original.get('priority_origin')
            if {k:v for k,v in item.model_dump(mode='json').items() if k!='correction'} == {k:v for k,v in original.items() if k!='correction'}:
                item.correction=original.get('correction','extracted')
        if content==draft.baseline: needs_review=False
        origins = {f:draft.baseline_origins.get(f,'extracted') if getattr(content,f) == getattr(draft.baseline,f) else 'user' for f in METADATA}
        changed = content != draft.content or needs_review != draft.requirements_need_review
        receipt = {'key':key,'hash':digest}
        # Editing an immutable confirmed goal forks a review, never mutates history.
        if row.get('record_type') != 'requirement_review':
            if not changed: return self._record_fork(owner,identifier,key,digest,draft)
            fork_id = stable_id(owner,key,'review-fork')
            existing = self.rows.find_one({'_id':ObjectId(fork_id),'user_id':owner})
            if existing:
                if existing.get('source_hash') != digest: raise GoalError('This save key was used with different edits.')
                return self._record_fork(owner,identifier,key,digest,self.get(fork_id,owner))
            stamp=now()
            fork=RequirementReview(**{**draft.model_dump(mode='python',exclude={'id'}),'_id':fork_id,'version':1,
                'content':content,'metadata_origins':origins,'requirements_need_review':needs_review,
                'created_at':stamp,'updated_at':stamp})
            payload=mongo_document(fork);payload.update(source_hash=digest,receipts=[receipt])
            try: self.rows.insert_one(payload)
            except DuplicateKeyError: return self.save(identifier,owner,key,body)
            return self._record_fork(owner,identifier,key,digest,fork)
        values = {'content':content.model_dump(mode='python'),'metadata_origins':origins,'requirements_need_review':needs_review}
        if changed: values.update(version=draft.version+1,updated_at=now())
        try:
            # Validate the whole resulting document, including its baseline,
            # before a successful write can replace the previous valid review.
            RequirementReview.model_validate({**draft.model_dump(mode='python'),**values})
        except ValidationError:
            raise GoalError('This review is too large or inconsistent. Shorten the edited context and retry.',422) from None
        result = self.rows.update_one({'_id':ObjectId(identifier),'user_id':owner,'version':body.expected_version,
            '$or':[{'processing':{'$exists':False}},{'processing.expires_at':{'$lt':now()}}]},
            {'$set':values,'$push':{'receipts':{'$each':[receipt],'$slice':-100}}})
        if not result.matched_count:
            latest=self._row(identifier,owner)
            if receipt not in latest.get('receipts',[]): raise GoalError('This review changed or is being confirmed. Reload before retrying.')
        return self.get(identifier,owner)

    def goal(self, draft, owner, key, data, *, allow_pending_context=False):
        if draft.version != data.expected_review_version: raise GoalError('The review changed. Reload before confirming.')
        if draft.requirements_need_review and not allow_pending_context: raise GoalError('Review the requirements for the edited role before confirming.',422)
        content=draft.content
        if any(getattr(data,f) != getattr(content,f) for f in METADATA) or data.target_type != draft.target_type:
            raise GoalError('Confirm the saved review values. Save your edits first.',422)
        if not content.role or not content.field: raise GoalError('Fill in the role and field before confirming.',422)
        stamp=now()
        skills=[TargetSkill.model_validate(s.model_dump()) for s in content.skills]
        ready=bool(skills) and not draft.requirements_need_review and draft.generation is not None and all(s.skill_id and s.priority!='conflicting' and (s.origin!='employer' or s.evidence) for s in skills) and all(r.priority!='conflicting' for r in content.non_skill_requirements)
        base=CareerGoal.model_validate(self._row(draft.base_goal_id,owner)) if draft.base_goal_id else None
        inherited={f:getattr(base,f) for f in ('interests','preferences','exploration_draft_id','exploration_draft_version','source_cv_id','source_cv_version','source_extraction_version','source_profile_version')} if base else {}
        return CareerGoal(**inherited,_id=stable_id(owner,key,'goal'),user_id=owner,version=1,skill_mapping_version=MAPPING_VERSION,
            created_at=stamp,updated_at=stamp,target_type=draft.target_type,**{f:getattr(content,f) for f in METADATA},
            skills=skills,non_skill_requirements=content.non_skill_requirements,summary=content.summary,responsibilities=content.responsibilities,
            requirements_source={'text':'pasted_jd','url':'url_jd','document':'document_jd','career_exploration':'career_exploration'}[draft.source_kind],
            generation_version=draft.generation.prompt_version if draft.generation else 'pending-skills',generation=draft.generation,
            readiness='ready' if ready else 'pending',requirements_need_review=draft.requirements_need_review,source_review_id=draft.id,source_review_version=draft.version)

    def claim_confirmation(self, identifier, owner, version, key):
        result=self.rows.update_one({'_id':ObjectId(identifier),'user_id':owner,'record_type':'requirement_review','version':version,
            '$or':[{'processing':{'$exists':False}},{'processing.expires_at':{'$lt':now()}}]},
            {'$set':{'processing':{'key':key,'expires_at':now()+timedelta(seconds=75)}}})
        if not result.matched_count: raise GoalError('This review changed or is being confirmed. Reload before confirming.')
        return self.get(identifier,owner)

    def release_confirmation(self,identifier,owner,key):
        self.rows.update_one({'_id':ObjectId(identifier),'user_id':owner,'processing.key':key},{'$unset':{'processing':''}})


    def create_guidance(self, owner, key, digest, goal, content, generation):
        identifier=stable_id(owner,key,'guidance-review')
        existing=self.rows.find_one({'_id':ObjectId(identifier),'user_id':owner})
        if existing:
            if existing.get('source_hash')!=digest: raise GoalError('This guidance key was used for different details.')
            return self.get(identifier,owner)
        stamp=now();prepared=prepare(content,extracted=True)
        draft=RequirementReview(_id=identifier,user_id=owner,version=1,skill_mapping_version=MAPPING_VERSION,
            created_at=stamp,updated_at=stamp,target_type='career_exploration',source_kind='career_exploration',
            base_goal_id=goal.id,content=prepared,baseline=prepared,generation=generation,
            metadata_origins={f:'user' for f in METADATA},baseline_origins={f:'user' for f in METADATA})
        payload=mongo_document(draft);payload.update(source_hash=digest,receipts=[])
        try:self.rows.insert_one(payload)
        except DuplicateKeyError:return self.create_guidance(owner,key,digest,goal,content,generation)
        return draft

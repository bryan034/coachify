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
        # Retired reset copies are removed on upgrade; effective content and receipts stay intact.
        self.rows.update_many({'$or':[{'baseline':{'$exists':True}},{'baseline_origins':{'$exists':True}}]},
            {'$unset':{'baseline':'','baseline_origins':''}})

    def _row(self, identifier, owner):
        row = self.rows.find_one({'_id': ObjectId(identifier), 'user_id': owner})
        if not row or row.get('record_type') == 'exploration_draft':
            raise GoalError('Career goal review was not found.', 404)
        return row

    def get(self, identifier, owner):
        row = self._row(identifier, owner)
        if row.get('record_type') == 'requirement_review':
            return RequirementReview.model_validate({k:v for k,v in row.items() if k in RequirementReview.model_fields or k=='_id'})
        goal = CareerGoal.model_validate({k:v for k,v in row.items() if k in CareerGoal.model_fields or k=='_id'})
        content = JDExtraction(role=goal.role, field=goal.field, company=goal.company, location=goal.location,
            seniority_level=goal.seniority_level, employment_type=goal.employment_type, job_url=goal.job_url, summary=goal.summary, responsibilities=goal.responsibilities,
            skills=[s.model_dump(mode='json') for s in goal.skills], non_skill_requirements=goal.non_skill_requirements)
        for index,skill in enumerate(content.skills):
            if not skill.item_id: skill.item_id=str(uuid5(NAMESPACE_URL,f'coachify:{goal.id}:skill:{index}'))
        return RequirementReview(_id=goal.id, user_id=owner, version=goal.version, skill_mapping_version=goal.skill_mapping_version,
            created_at=goal.created_at, updated_at=goal.updated_at, target_type=goal.target_type,
            source_kind={'pasted_jd':'text','url_jd':'url','document_jd':'document','career_exploration':'career_exploration'}[goal.requirements_source],
            content=content, generation=goal.generation,discovery=goal.discovery,
            requirements_need_review=goal.requirements_need_review, base_goal_id=goal.id,
            metadata_origins={f:'user' for f in METADATA})

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
        if any(v.origin=='market_research' for v in [*content.skills,*content.non_skill_requirements]):raise GoalError('Market evidence must come from career discovery.',422)
        prepared = prepare(content, extracted=True)
        draft = RequirementReview(_id=stable_id(owner,key,'jd-review'), user_id=owner, version=1,
            skill_mapping_version=MAPPING_VERSION, created_at=stamp, updated_at=stamp,
            source_kind=source_kind, content=prepared, generation=generation,
            metadata_origins={field:'extracted' for field in METADATA})
        payload = mongo_document(draft); payload.update(source_hash=digest, receipts=[])
        try: self.rows.insert_one(payload)
        except DuplicateKeyError: return self.replay_extraction(owner,key,digest)
        return draft

    def version(self, identifier, owner):
        return self._row(identifier,owner)['version']

    def save(self, identifier, owner, key, body, *, chat_receipt=None):
        row = self._row(identifier, owner)
        digest = fingerprint(body.model_dump(mode='json'))
        for receipt in row.get('receipts',[]):
            if receipt['key'] == key:
                if receipt['hash'] != digest: raise GoalError('This save key was used with different edits.')
                return self.get(identifier,owner)
        draft = self.get(identifier,owner)
        if draft.version != body.expected_version:
            raise GoalError('This review changed in another request. Reload it before saving.')
        content = prepare(body.content, draft.content)
        if draft.target_type == 'career_exploration' and (any(s.origin == 'employer' for s in content.skills) or any(r.origin == 'employer' for r in content.non_skill_requirements)):
            raise GoalError('Exploration considerations must be user declarations or suggested guidance.',422)
        contextual = any(getattr(content,f) != getattr(draft.content,f) for f in METADATA)
        needs_review = (draft.requirements_need_review or contextual) and not body.acknowledge_context
        origins = {f:draft.metadata_origins.get(f,'extracted') if getattr(content,f)==getattr(draft.content,f) else 'user' for f in METADATA}
        changed = content != draft.content or needs_review != draft.requirements_need_review
        receipt = {'key':key,'hash':digest,**({'chat_hash':chat_receipt['hash']} if chat_receipt else {})}
        # The selected goal is edited in place with owner/version CAS. No review fork.
        if row.get('record_type') != 'requirement_review':
            selected=self.state.find_one({'_id':owner}) or {}
            if selected.get('goal_id')!=ObjectId(identifier):raise GoalError('This goal is no longer current.')
            if not changed:
                self.rows.update_one({'_id':ObjectId(identifier),'user_id':owner,'version':body.expected_version},{'$push':{'receipts':{'$each':[receipt],'$slice':-100}}})
                return self.get(identifier,owner)
            values=content.model_dump(mode='python')
            values.update(requirements_need_review=needs_review,readiness='pending',updated_at=now(),version=draft.version+(1 if changed else 0))
            try:CareerGoal.model_validate({**{k:v for k,v in row.items() if k in CareerGoal.model_fields or k=='_id'},**values})
            except ValueError:raise GoalError('The edited career goal is inconsistent.',422) from None
            result=self.rows.update_one({'_id':ObjectId(identifier),'user_id':owner,'version':body.expected_version},
                {'$set':values,'$push':{'receipts':{'$each':[receipt],'$slice':-100}}})
            if not result.matched_count:
                latest=self._row(identifier,owner)
                if receipt not in latest.get('receipts',[]):raise GoalError('Your career goal changed. Reload before retrying.')
            return self.get(identifier,owner)
        values = {'content':content.model_dump(mode='python'),'metadata_origins':origins,'requirements_need_review':needs_review}
        if changed: values.update(version=draft.version+1,updated_at=now())
        try:
            # Validate the whole resulting document, including its provenance,
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
        base=CareerGoal.model_validate({k:v for k,v in self._row(draft.base_goal_id,owner).items() if k in CareerGoal.model_fields or k=='_id'}) if draft.base_goal_id else None
        inherited={f:getattr(base,f) for f in ('interests','preferences','exploration_draft_id','exploration_draft_version','source_cv_id','source_cv_version','source_extraction_version','source_profile_version')} if base else {}
        return CareerGoal(**inherited,discovery=draft.discovery,_id=draft.id,user_id=owner,version=draft.version,skill_mapping_version=MAPPING_VERSION,
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
            base_goal_id=goal.id,content=prepared,generation=generation,
            metadata_origins={f:'user' for f in METADATA})
        payload=mongo_document(draft);payload.update(source_hash=digest,receipts=[])
        try:self.rows.insert_one(payload)
        except DuplicateKeyError:return self.create_guidance(owner,key,digest,goal,content,generation)
        return draft

    def create_discovery(self, owner, key, content, generation, evidence):
        """Same review model and goal() builder as JD extraction; no selected goal yet."""
        identifier=stable_id(owner,key,'discovery-review')
        existing=self.rows.find_one({'_id':ObjectId(identifier),'user_id':owner})
        if existing:return self.get(identifier,owner)
        stamp=now()
        prepared=prepare(content,extracted=True)
        # Trusted server aggregation supplies these URLs; generic preview prepare()
        # deliberately strips client-supplied evidence URLs on new items.
        for old,new in zip(content.skills,prepared.skills):new.source_urls=old.source_urls
        for old,new in zip(content.non_skill_requirements,prepared.non_skill_requirements):new.source_urls=old.source_urls
        review=RequirementReview(_id=identifier,user_id=owner,version=1,skill_mapping_version=MAPPING_VERSION,
            created_at=stamp,updated_at=stamp,target_type='career_exploration',source_kind='career_exploration',
            content=prepared,generation=generation,discovery=evidence,
            metadata_origins={f:'user' for f in METADATA})
        try:self.rows.insert_one({**mongo_document(review),'receipts':[]})
        except DuplicateKeyError:return self.get(identifier,owner)
        return review

"""Shared immutable public research and private per-goal references."""
from datetime import timedelta
from uuid import uuid4
from bson import ObjectId
from bson.codec_options import CodecOptions
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.repositories.analysis import AnalysisRepository
from app.repositories.goals import GoalError, now
from app.domain.review import MAPPING_VERSION
from app.schemas.analysis import ResearchContext

POLICY='public-interview-brave-process-v4:answers'
FRESHNESS=timedelta(days=7)

class ResearchStore:
    def __init__(self,database):
        db=database.with_options(codec_options=CodecOptions(tz_aware=True))
        self.cache,self.state=db.research_contexts,db.career_state
        self.policy=POLICY
        self.records=AnalysisRepository(db)

    def ensure_indexes(self):self.records.ensure_indexes()

    def goal(self,owner,goal_id,version=None):
        goal=self.records.get_private('career_goals',goal_id,owner)
        if not goal:raise GoalError('Confirmed career goal was not found.',404)
        if version is not None and goal.version!=version:
            raise GoalError('Your career goal changed. Reload before using its research.')
        return goal

    def context_keys(self,goal):
        from app.workflows.opportunity.domain import public_opportunity
        context=ResearchContext(**{key:getattr(goal,key,None) for key in ResearchContext.model_fields})
        return {context.reuse_key(),public_opportunity(goal)[1].reuse_key()}

    def linked(self,owner,goal_id,*,current=False,goal_version=None):
        row=self.state.find_one({'_id':owner}) or {}
        linked=row.get('research_links',{}).get(goal_id,[])
        if not current:return linked
        goal=self.goal(owner,goal_id,goal_version);keys=self.context_keys(goal)
        metadata=row.get('research_link_meta',{}).get(goal_id,{})
        result=[]
        for identifier in linked:
            meta=metadata.get(identifier,{})
            # Pre-upgrade links have no revision stamp. Only an unchanged first
            # revision can be proven current; all other history stays readable
            # explicitly and can be attached afresh through normal acquisition.
            if meta.get('goal_version',1)!=goal.version:continue
            context_key=meta.get('context_key')
            if context_key is None:
                old=self.records.database.interview_research.find_one({'_id':ObjectId(identifier)},{'context_key':1}) or {}
                context_key=old.get('context_key')
            if context_key in keys:result.append(identifier)
        return result

    def read(self,owner,goal_id,research_id=None,*,current=False,goal_version=None):
        current=current or research_id is None
        goal=self.goal(owner,goal_id,goal_version) if current else None
        linked=self.linked(owner,goal_id,current=current,goal_version=goal.version if goal else None)
        if research_id and research_id not in linked:
            if current and research_id in self.linked(owner,goal_id):
                raise GoalError('This research belongs to an earlier goal revision. Refresh research for the current goal.')
            raise GoalError('Research reference was not found for this goal.',404)
        record=self.records.get_research(research_id or linked[-1]) if linked else None
        if goal:self.goal(owner,goal_id,goal.version)
        return record

    def begin(self,context,refresh):
        key=context.reuse_key()
        latest=self.records.database.interview_research.find_one({'context_key':key},sort=[('version',-1)])
        try:self.cache.update_one({'_id':key},{'$setOnInsert':{'version':latest['version'] if latest else 0,'status':'missing'}},upsert=True)
        except DuplicateKeyError:pass
        row=self.cache.find_one({'_id':key})
        current=self.records.get_research(row['result']) if row.get('result') else None
        if current and current.skill_mapping_version==MAPPING_VERSION and row.get('policy')==self.policy and current.last_researched_at>=now()-FRESHNESS and not refresh:
            return {'record':current,'reused':True}
        token=uuid4().hex
        lease=self.cache.find_one_and_update({'_id':key,'$or':[{'lease':{'$exists':False}},{'lease.expires_at':{'$lt':now()}}]},
            {'$set':{'lease':{'token':token,'expires_at':now()+timedelta(seconds=100)},'status':'processing'},'$inc':{'version':1}},return_document=ReturnDocument.AFTER)
        if not lease:return {'processing':True}
        return {'token':token,'version':lease['version']}

    def finish(self,context,token,record):
        if not self.cache.find_one({'_id':context.reuse_key(),'lease.token':token,'lease.expires_at':{'$gt':now()}}):
            raise GoalError('Research lease expired. Retry to load the latest result.')
        record=self.records.save_research(record,trusted_sources={s.source_id:s for s in record.sources})
        updated=self.cache.update_one({'_id':context.reuse_key(),'lease.token':token},
            {'$set':{'result':record.id,'status':record.research_status,'policy':self.policy},'$unset':{'lease':''}})
        if not updated.matched_count:raise GoalError('Newer research superseded this request.')
        return record

    def fail(self,context,token,status):
        self.cache.update_one({'_id':context.reuse_key(),'lease.token':token},{'$set':{'status':status},'$unset':{'lease':''}})

    def was_reused(self,owner,goal_id,record):
        row=self.state.find_one({'_id':owner}) or {}
        return bool(record and row.get('research_link_meta',{}).get(goal_id,{}).get(record.id,{}).get('reused'))

    def attach(self,owner,goal_id,selection,key,digest,record,*,goal_version,reused=False):
        if type(goal_version) is not int or goal_version<1:
            raise GoalError('The research revision is unavailable. Refresh the current goal.')
        goal=self.goal(owner,goal_id,goal_version)
        if record.context_key not in self.context_keys(goal):
            raise GoalError('The public research context changed. Research was retained as history.')
        receipt={'key':key,'hash':digest,'goal_id':goal_id,'goal_version':goal_version,'research_id':record.id}
        matched=self.state.update_one({'_id':owner,'version':selection,'goal_id':ObjectId(goal_id)},
            {'$set':{'research_link_meta.'+goal_id+'.'+record.id:{'reused':reused,'goal_version':goal_version,'context_key':record.context_key}},'$addToSet':{'research_links.'+goal_id:record.id},'$push':{'research_receipts':{'$each':[receipt],'$slice':-100}}})
        if not matched.matched_count:raise GoalError('The selected goal changed. Research was not attached to your goal.')
        # MongoDB is standalone: a concurrent edit may land between the goal
        # check and state CAS. Its stamped link is historical, never current.
        self.goal(owner,goal_id,goal_version)

    def replay(self,owner,key,digest):
        row=self.state.find_one({'_id':owner}) or {}
        receipt=next((r for r in row.get('research_receipts',[]) if r['key']==key),None)
        if receipt:
            if receipt['hash']!=digest:raise GoalError('This research key was used for different details.')
            return self.read(owner,receipt['goal_id'],receipt['research_id'],current=True,goal_version=receipt.get('goal_version',1))

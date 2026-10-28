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

POLICY='public-interview-brave-process-v4:answers'
FRESHNESS=timedelta(days=7)

class ResearchStore:
    def __init__(self,database):
        db=database.with_options(codec_options=CodecOptions(tz_aware=True))
        self.cache,self.state=db.research_contexts,db.career_state
        self.policy=POLICY
        self.records=AnalysisRepository(db)

    def ensure_indexes(self):self.records.ensure_indexes()

    def linked(self,owner,goal_id):
        return (self.state.find_one({'_id':owner}) or {}).get('research_links',{}).get(goal_id,[])

    def read(self,owner,goal_id,research_id=None):
        linked=self.linked(owner,goal_id)
        if research_id and research_id not in linked:raise GoalError('Research reference was not found for this goal.',404)
        return self.records.get_research(research_id or linked[-1]) if linked else None

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

    def attach(self,owner,goal_id,selection,key,digest,record,*,reused=False):
        receipt={'key':key,'hash':digest,'goal_id':goal_id,'research_id':record.id}
        matched=self.state.update_one({'_id':owner,'version':selection,'goal_id':ObjectId(goal_id)},
            {'$set':{'research_link_meta.'+goal_id+'.'+record.id:{'reused':reused}},'$addToSet':{'research_links.'+goal_id:record.id},'$push':{'research_receipts':{'$each':[receipt],'$slice':-100}}})
        if not matched.matched_count:raise GoalError('The selected goal changed. Research was not attached to your goal.')

    def replay(self,owner,key,digest):
        row=self.state.find_one({'_id':owner}) or {}
        receipt=next((r for r in row.get('research_receipts',[]) if r['key']==key),None)
        if receipt:
            if receipt['hash']!=digest:raise GoalError('This research key was used for different details.')
            return self.records.get_research(receipt['research_id'])

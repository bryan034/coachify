"""Durable private jobs in research_contexts; immutable public reports reuse interview_research."""
from datetime import timedelta
from bson.codec_options import CodecOptions
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.repositories.goals import GoalError,fingerprint,now
from app.repositories.research import ResearchStore
from app.schemas.opportunity import CATEGORIES,CategoryResult
from app.clients.search_sources import OPPORTUNITY_SOURCE_LIMIT
from .domain import public_opportunity

class OpportunityStore:
    def __init__(self,db,settings):
        db=db.with_options(codec_options=CodecOptions(tz_aware=True));self.db=db;self.rows=db.research_contexts;self.settings=settings
        self.research=ResearchStore(db);self.research.policy='opportunity-intelligence-structured-findings-v6'
        self.rows.create_index([('kind',1),('finished',1),('next_attempt_at',1)])
        self.rows.create_index([('owner',1),('goal_id',1),('created_at',-1)])
        self.rows.create_index([('owner',1),('goal_id',1),('run',1)],unique=True,partialFilterExpression={'kind':'opportunity_job','finished':False})

    def cached(self,context):
        row=self.rows.find_one({'_id':context.reuse_key(),'policy':self.research.policy}) or {}
        record=self.research.records.get_research(row['result']) if row.get('result') else None
        return record if record and record.intelligence else None

    def start(self,owner,goal,selection,session,run,key,command,seed=None):
        public,context=public_opportunity(goal);digest=fingerprint(command)
        identifier='oi-job:'+fingerprint({'owner':owner,'key':key})
        receipt_id='oi-command:'+fingerprint({'owner':owner,'key':key})
        receipt=self.rows.find_one({'_id':receipt_id})
        if receipt:
            if receipt['digest']!=digest or receipt['goal_id']!=goal.id:raise GoalError('This research request key was already used for different details.')
            return self.rows.find_one({'_id':receipt['job_id']})
        old=self.rows.find_one({'_id':identifier})
        if old:
            if old['digest']!=digest or old['goal_id']!=goal.id:raise GoalError('This research request key was already used for different details.')
            return old
        active=self.rows.find_one({'kind':'opportunity_job','owner':owner,'goal_id':goal.id,'run':run,'finished':False})
        if active:
            requested=[command['category']] if command.get('category') else list(CATEGORIES)
            if (command.get('refresh') or command.get('category')) and not set(requested)<=set(active.get('requested',CATEGORIES)):raise GoalError('Another category refresh is running. Retry this refresh after it finishes.')
            try:self.rows.insert_one({'_id':receipt_id,'kind':'opportunity_command','owner':owner,'goal_id':goal.id,'digest':digest,'job_id':active['_id']})
            except DuplicateKeyError:
                receipt=self.rows.find_one({'_id':receipt_id})
                if receipt['digest']!=digest:raise GoalError('This research key was used for different details.') from None
            return active
        cached=self.cached(context);categories={k:CategoryResult().model_dump(mode='json') for k in CATEGORIES}
        sources=[]
        if cached:
            categories={k:v.model_dump(mode='json') for k,v in cached.intelligence.categories.items()};sources=[s.model_dump(mode='json') for s in cached.sources]
        requested=[command['category']] if command.get('category') else list(CATEGORIES)
        for category in requested:
            result=CategoryResult.model_validate(categories[category])
            if command.get('refresh') or command.get('category') or result.status in ('failed','partial','pending','running') or not result.expires_at or result.expires_at<=now():
                categories[category]={**categories[category],'status':'pending','error_code':None,'outcome':None}
        pending=[k for k,v in categories.items() if v['status']=='pending']
        summary_pending=bool(cached and any(w.startswith('Overall summary unavailable;') for w in cached.intelligence.warnings))
        retained={category:[s for s in sources if s['source_id'] in set(value.get('source_ids',[]))|{sid for finding in value['findings'] for sid in finding['source_ids']}][:OPPORTUNITY_SOURCE_LIMIT] for category,value in categories.items()}
        row={'_id':identifier,'kind':'opportunity_job','owner':owner,'goal_id':goal.id,'selection':selection,'session':session,'run':run,
             'digest':digest,'public':public,'context':context.model_dump(mode='json'),'status':'pending' if pending or summary_pending else cached.intelligence.status,
             'finished':not (pending or summary_pending),'prefetched':bool(seed),'queries_planned':bool((seed or {}).get('queries_planned')),'categories':categories,'sources':sources,'queries':(seed or {}).get('queries',{}),'evidence':(seed or {}).get('evidence',{}),'history':(seed or {}).get('history',{}),
             'retained_sources':retained,'requested':pending,'research_id':cached.id if cached else None,'created_at':now(),'updated_at':now(),'next_attempt_at':now(), 'summary':cached.intelligence.summary.model_dump() if cached else {}}
        waits=(seed or {}).get('waits',{})
        if waits and pending:
            active_waits={category:until for category,until in waits.items() if category in pending and until>now()}
            if active_waits:
                row.update(next_attempt_at=max(active_waits.values()),error_code='source_rate_limited',provider='brave',limit_scope='provider')
                for category in active_waits:row['categories'][category]['error_code']='source_rate_limited'
        try:self.rows.insert_one(row)
        except DuplicateKeyError:
            existing=self.rows.find_one({'_id':identifier})
            if existing:
                if existing['digest']!=digest:raise GoalError('Concurrent research request changed.') from None
                return existing
            return self.start(owner,goal,selection,session,run,key,command)
        return row

    def latest(self,owner,goal_id):
        return self.rows.find_one({'kind':'opportunity_job','owner':owner,'goal_id':goal_id},sort=[('created_at',-1)])

    def claim(self,identifier,token):
        return self.rows.find_one_and_update({'_id':identifier,'finished':False,'next_attempt_at':{'$lte':now()},
             '$or':[{'worker_until':{'$exists':False}},{'worker_until':{'$lte':now()}}]},
             {'$set':{'worker_token':token,'worker_until':now()+timedelta(seconds=self.settings.run_seconds+60),'status':'running','updated_at':now()}},return_document=ReturnDocument.AFTER)

    def update(self,identifier,token,**values):
        values['updated_at']=now()
        retry=values.pop('next_attempt_at',None)
        update={'$set':values}
        if retry:update['$max']={'next_attempt_at':retry}
        result=self.rows.update_one({'_id':identifier,'worker_token':token},update)
        if not result.matched_count:raise GoalError('A newer worker replaced this research run.')

    def release(self,identifier,token):
        self.rows.update_one({'_id':identifier,'worker_token':token},{'$unset':{'worker_until':'','worker_token':''}})

    def due(self):
        return list(self.rows.find({'kind':'opportunity_job','finished':False,'next_attempt_at':{'$lte':now()},
            '$or':[{'worker_until':{'$exists':False}},{'worker_until':{'$lte':now()}}]}, {'_id':1}).limit(20))

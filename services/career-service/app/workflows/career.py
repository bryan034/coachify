"""LangGraph orchestration. Raw JD extraction has NO durable checkpointer.

The resumable graph contains only owner-scoped record references and bounded
public evidence. No secrets, raw documents or chat transcripts enter checkpoints.
"""
import asyncio
import operator
import logging
from pymongo.errors import PyMongoError
from datetime import timedelta
from typing import Annotated,TypedDict
from bson import ObjectId
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.mongodb import MongoDBSaver
from langsmith import tracing_context
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.waiting import quota_progress
from app.ai.recovery import recover_responses,validation_progress,validation_budget
from app.workflows.structured import structured_node
from app.workflows import research_search
from app.ai.jd_scope import identify_job
from app.workflows.activity import activity,activity_observer
from app.workflows.jd_prefetch import prefetch,matches
from app.ai.contracts import AIInput
from app.api.v1.jd import validate_extraction
from app.api.v1.research import context_for
from app.clients.research import normalize_sources,normalize_batch
from app.domain.interview import topics_from
from app.domain.review import MAPPING_VERSION
from app.repositories.goals import GoalError,now
from app.schemas.analysis import Generation,InterviewResearch

class Progress(TypedDict,total=False):
    owner:str
    session:str
    run:str
    goal_id:str
    revision:int
    selection:int
    round:int
    opportunity_deferred:bool
    smart_search:bool
    planned_queries:list[str]
    query_history:list[str]
    useful_source_ids:list[str]
    latest_source_ids:list[str]
    assessed_source_ids:list[str]
    stalled_rounds:int
    search_exhausted:bool
    sources:Annotated[list[dict],operator.add]
    coverage:Annotated[list[dict],operator.add]
    summaries:Annotated[list[dict],operator.add]
    source_error:str|None
    cache:dict
    research_id:str




class CareerWorkflow:
    def __init__(self,app,database):
        self.app=app;self.db=database;self.tasks={};self.early={};self.seeds={};self.stopping=False
        saver=MongoDBSaver(database.client,db_name=database.name,checkpoint_collection_name='career_checkpoints',writes_collection_name='career_checkpoint_writes',ttl=86400)
        graph=StateGraph(Progress)
        for name,fn in [('guidance',self.guidance),('cache',self.cache),('plan_search',self.plan_search),('brave',self.brave),('assess',self.assess),('synthesize',self.synthesize),('publish',self.publish)]:graph.add_node(name,structured_node(fn) if name in ('guidance','plan_search','assess','synthesize') else fn)
        graph.add_edge(START,'guidance');graph.add_edge('guidance','cache')
        graph.add_conditional_edges('cache',lambda s:[END] if s.get('opportunity_deferred') else ['publish'] if s.get('research_id') else ['plan_search'] if s.get('smart_search') else ['brave'])
        graph.add_edge('plan_search','brave')
        graph.add_edge('brave','assess')
        graph.add_conditional_edges('assess',self.after_assess)
        graph.add_edge('synthesize','publish');graph.add_edge('publish',END)
        self.graph=graph.compile(checkpointer=saver)

    @property
    def workspaces(self):return self.app.state.workspace_store

    async def extract(self,body,account,key,*,early=True):
        # Scope/identity is transient and cannot save a goal by itself.
        identity=await identify_job(self.app.state.ai,body.text,account)
        engine=getattr(self.app.state,'opportunities',None)
        if early and engine is not None and engine.available and identity.role:
            entry={'identity':identity,'activities':[]};observer=activity_observer.get()
            def observed(stage):
                if stage not in entry['activities']:entry['activities'].append(stage)
                if observer:observer(stage)
            token=activity_observer.set(observed)
            try:entry['task']=asyncio.create_task(prefetch(engine,identity,account,key))
            finally:activity_observer.reset(token)
            self.early[(account,key)]=entry
        activity('extracting_requirements')
        # Full source text and failed model output stay in worker memory only.
        async def interpret(state):
            if recover_responses.get():
                row=await thread(self.workspaces.row,account)
                if row.get('incoming',{}).get('key')!=key:
                    raise GoalError('A newer description replaced this input.')
            result=await self.app.state.ai.generate(AIInput(stage='jd_extraction',source_text=body.text,source_urls=[body.source_url] if body.source_url else []),
                Operation(account,'transient','jd_extraction'),current_revision=lambda:'transient',validate_output=lambda o:validate_extraction(o,body.source_url))
            return {'result':result}
        def validate(state):
            validate_extraction(state['result'].data,body.source_url)
            if not state['result'].data.role or not state['result'].data.field:raise GoalError('Include an identifiable job role and field in the description.',422)
            return state
        graph=StateGraph(dict);graph.add_node('interpret_jd',structured_node(interpret));graph.add_node('validate_structure',validate)
        graph.add_edge(START,'interpret_jd');graph.add_edge('interpret_jd','validate_structure');graph.add_edge('validate_structure',END)
        try:
            with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
            return result['result']
        except BaseException:
            await self.cancel_prefetch(account,key)
            raise

    async def cancel_prefetch(self,owner,key):
        entry=self.early.pop((owner,key),None)
        if entry:
            entry['task'].cancel()
            await asyncio.gather(entry['task'],return_exceptions=True)

    def adopt_prefetch(self,owner,key,row):
        entry=self.early.pop((owner,key),None)
        if entry:
            workspace=row['workspace']
            self.seeds[(owner,workspace['session_id'],workspace['run_id'])]=entry

    def early_activities(self,owner,session,run):
        entry=self.seeds.get((owner,session,run))
        return list(entry['activities']) if entry else []

    async def valid(self,state):
        row=await thread(self.workspaces.check,state['owner'],state['session'],state['revision'])
        if row['workspace'].get('expires_at',now())<=now():raise GoalError('Temporary workflow expired; resume the saved goal.')
        if row['workspace']['run_id']!=state['run'] or str(row['goal_id'])!=state['goal_id']:raise GoalError('A newer goal replaced this workflow.')
        return row

    async def goal(self,state):
        await self.valid(state)
        return (await thread(self.app.state.goal_store.current,state['owner']))['goal']

    def unique(self,state):
        if state.get('smart_search'):
            useful=set(state.get('useful_source_ids',[]))
            return [source for source in research_search.candidates(state) if source.source_id in useful][:6]
        values=[];ids=set()
        for value in state.get('sources',[]):
            if value['source_id'] not in ids:values.append(value);ids.add(value['source_id'])
        return normalize_sources(values[:6]) if values else []

    async def guidance(self,state):
        goal=await self.goal(state)
        if goal.target_type!='career_exploration' or goal.skills:return {}
        from app.domain.review import METADATA
        import json
        context={**{f:getattr(goal,f) for f in METADATA},'interests':goal.interests,'preferences':goal.preferences}
        def validate(output):
            if not output.skills or output.non_skill_requirements or any(s.origin!='generated_guidance' or s.priority!='suggested' or s.evidence or s.priority_evidence for s in output.skills):
                raise AIError('invalid_output',True,reason='provenance')
            for f in METADATA:setattr(output,f,getattr(goal,f))
        result=await self.app.state.ai.generate(AIInput(stage='role_guidance',context=json.dumps(context)),
            Operation(state['owner'],goal.id,'role_guidance'),current_revision=lambda:goal.id,validate_output=validate)
        validate(result.data);await self.valid(state)
        review=await thread(self.app.state.review_store.create_guidance,state['owner'],state['run'],state['run'],goal,result.data,result.generation)
        row=await thread(self.workspaces.activate,state['owner'],state['session'],review,keep_run=True)
        return {'goal_id':str(row['goal_id']),'revision':row['workspace']['revision'],'selection':row['version']}

    async def cache(self,state):
        goal=await self.goal(state);repo=self.app.state.research_store
        opportunity=getattr(self.app.state,'opportunities',None)
        if opportunity is not None and opportunity.available:
            identity_key=(state['owner'],state['session'],state['run'])
            entry=self.seeds.get(identity_key);seed=None
            try:
                if entry:
                    if matches(entry['identity'],goal):seed=await entry['task']
                    else:
                        entry['task'].cancel()
                        await asyncio.gather(entry['task'],return_exceptions=True)
                await self.valid(state)
                await opportunity.start(state['owner'],goal,state['selection'],state['session'],state['run'],'auto:'+state['run'],{'refresh':False,'category':None},seed=seed)
            finally:self.seeds.pop(identity_key,None)
            return {'opportunity_deferred':True}
        smart=research_search.enabled(self)
        cache=await thread(repo.begin,context_for(goal),False)
        if cache.get('processing'):raise GoalError('Matching public research is already running. Retry shortly.',503)
        if cache.get('record'):
            record=cache.pop('record');return {'cache':{'reused':True},'research_id':record.id,'coverage':[c.model_dump() for c in record.coverage]}
        return {'cache':cache,'round':0,'smart_search':smart}

    async def plan_search(self,state):return await research_search.plan(self,state)

    async def platform(self,state,platform):
        goal=await self.goal(state);provider=self.app.state.research_client
        try:
            if state.get('smart_search'):
                await research_search.renew(self,state)
                query=research_search.next_query(state,context_for(goal))
                if query is None:raise GoalError('No additional distinct interview searches could be planned.',503)
                sources=await asyncio.wait_for(provider.collect_query(context_for(goal),query),40)
            elif hasattr(provider,'collect_platform'):sources=await asyncio.wait_for(provider.collect_platform(context_for(goal),platform,state.get('round',0)),40)
            elif platform=='brave':sources=await asyncio.wait_for(provider.collect(context_for(goal)),40)
            batch=normalize_batch(sources);sources=batch.sources
            if state.get('smart_search'):
                return {'sources':[s.model_dump(mode='json') for s in sources],
                        'query_history':[*state.get('query_history',[]),query],
                        'latest_source_ids':[s.source_id for s in sources], 'source_error':None}
            return {'sources':[s.model_dump(mode='json') for s in sources], 'summaries':[v.model_dump(mode='json') for v in batch.summaries], 'source_error':None, 'coverage':[{'platform':platform,'status':'succeeded' if sources else 'no_findings','round':state.get('round',0)}]}
        except (GoalError,TimeoutError,ValueError) as error:
            message=error.message if isinstance(error,GoalError) else ('Brave research timed out. Retry shortly.' if isinstance(error,TimeoutError) else 'Brave returned research data that could not be validated. Retry interview research.')
            return {'source_error':message,'coverage':[{'platform':platform,'status':'unavailable','round':state.get('round',0)}]}

    async def brave(self,state):return await self.platform(state,'brave')

    def after_assess(self,state):
        if state.get('smart_search'):
            more=not state.get('search_exhausted') and state['round']<research_search.MAX_SEARCHES and len(state.get('useful_source_ids',[]))<research_search.TARGET_SOURCES
        else:
            more=state['round']==1 and len(self.unique(state))<2 and not any(v.get('claims') for v in state.get('summaries',[]))
        return ['brave'] if more else ['synthesize']

    async def assess(self,state):
        await self.valid(state)
        if state.get('smart_search'):return await research_search.assess(self,state)
        if not any(v['status'] in ('succeeded','no_findings') for v in state.get('coverage',[])):
            raise GoalError(state.get('source_error') or 'Interview research is unavailable. Retry shortly.',503)
        return {'round':state.get('round',0)+1}

    async def synthesize(self,state):
        goal=await self.goal(state);sources=self.unique(state);stamp=now()
        from app.schemas.research import ResearchBatch
        ids={v.source_id for v in sources};kept=[]
        for value in state.get('summaries',[]):
            references=[s for s in value['source_ids'] if s in ids]
            if references:kept.append({**value,'source_ids':references,'claims':[{**c,'source_ids':[s for s in c['source_ids'] if s in ids]} for c in value.get('claims',[]) if any(s in ids for s in c['source_ids'])]})
        batch=normalize_batch(ResearchBatch(sources=sources,summaries=kept))
        summaries=batch.summaries
        from app.schemas.analysis import InterviewProcess
        process=InterviewProcess()
        if sources:
            result=await self.app.state.ai.generate(AIInput(stage='interview_synthesis',public_context=context_for(goal),sources=sources,summaries=summaries),
                Operation(state['owner'],state['goal_id'],'interview_synthesis'),current_revision=lambda:state['goal_id'])
            skills=topics_from(result.data,sources,summaries);generation=result.generation;process=result.data.process
        else:skills=[];generation=Generation(provider='retrieval',model='none',prompt_version='no-findings-v1',generated_at=stamp)
        record=InterviewResearch(_id=str(ObjectId()),version=state['cache']['version'],skill_mapping_version=MAPPING_VERSION,
            created_at=stamp,updated_at=stamp,**context_for(goal).model_dump(),sources=sources,summaries=summaries,skills=skills,process=process,
            research_status='succeeded' if skills or process.stages or process.round_count is not None else 'no_findings',last_researched_at=stamp,generation=generation,coverage=state.get('coverage',[]))
        record=await thread(self.app.state.research_store.finish,context_for(goal),state['cache']['token'],record)
        return {'research_id':record.id}

    async def publish(self,state):
        await self.valid(state)
        record=await thread(self.app.state.research_store.records.get_research,state['research_id'])
        # Only public, source-validated research reaches the explanation gate.
        if not record or record.research_status not in ('succeeded','no_findings'):raise GoalError('Interview research needs retry.',503)
        await thread(self.app.state.research_store.attach,state['owner'],state['goal_id'],state['selection'],state['run'],state['run'],record,reused=state.get('cache',{}).get('reused',False))
        await thread(self.workspaces.phase,state['owner'],state['session'],state['run'],'ready',coverage=state.get('coverage',[]),research_id=record.id,error=None,error_code=None,retry_after=None)

    def config(self,owner,workspace):
        return {'configurable':{'thread_id':owner+':'+workspace['session_id']+':'+workspace['run_id']},'recursion_limit':40,'callbacks':[]}

    def launch(self,owner,replace=False):
        if self.stopping:return
        old=self.tasks.get(owner)
        if old and not old.done():
            if not replace:return
            old.cancel()
        async def start():
            # Research owns its durable checkpoint/lease pause handling; do not
            # inherit a foreground operation's in-memory quota callback.
            quota_progress.set(None)
            validation_progress.set(None)
            if old and not old.done():await asyncio.gather(old,return_exceptions=True)
            await self.run(owner)
        task=asyncio.create_task(start());self.tasks[owner]=task
        def finished(done):
            if not done.cancelled() and done.exception() is not None:
                logging.getLogger('uvicorn.error').warning('Career workflow stopped; reload the workspace to retry.')
            if self.tasks.get(owner) is done:self.tasks.pop(owner,None)
        task.add_done_callback(finished)

    async def run(self,owner):
        while not self.stopping:
            if not await self._run_once(owner):break

    async def _run_once(self,owner):
        row=await thread(self.workspaces.row,owner);w=row.get('workspace',{})
        if not w.get('review_id') or w.get('phase')=='ready' or w.get('expires_at',now())<=now():return
        opportunity=getattr(self.app.state,'opportunities',None)
        if opportunity is not None and opportunity.available:
            job=await thread(opportunity.store.latest,owner,str(row.get('goal_id')))
            if job and job['run']==w.get('run_id'):
                if job.get('research_id'):await opportunity.attach(job)
                if not job['finished']:opportunity.launch(job['_id'])
                return  # The durable worker owns its wait/status; polling must not restart the legacy graph.
        config=self.config(owner,w);session=w['session_id'];run=w['run_id']
        # A database lease prevents duplicate graph execution by API replicas.
        leased=await thread(self.db.career_state.update_one,{'_id':owner,'workspace.run_id':run,'$or':[{'workspace.worker_until':{'$exists':False}},{'workspace.worker_until':{'$lt':now()}}]},
            {'$set':{'workspace.worker_until':now()+timedelta(seconds=180)}})
        if not leased.matched_count:return
        try:
            await thread(self.workspaces.phase,owner,session,run,'researching',error=None)
            state=await self.graph.aget_state(config)
            token=(state.values.get('cache') or {}).get('token') if state.values else None
            if token and not state.values.get('research_id'):
                lease=await thread(self.db.research_contexts.find_one,{'lease.token':token,'lease.expires_at':{'$gt':now()}})
                if not lease:
                    await thread(self.workspaces.phase,owner,session,run,'research_pending',run_id=str(ObjectId()))
                    return
            value=None if state.values and state.next else {'owner':owner,'session':session,'run':run,'goal_id':str(row['goal_id']),'revision':w['revision'],'selection':row['version'],'sources':[],'summaries':[],'coverage':[]}
            async def repairing(feedback):
                if feedback is None:return
                # Every corrective call gets a fresh model deadline. Keep both
                # leases alive and reject superseded work before spending again.
                latest=await thread(self.workspaces.check,owner,session,w['revision'])
                if latest['workspace']['run_id']!=run:raise GoalError('A newer goal replaced this work.')
                if latest['workspace'].get('expires_at',now())<=now():raise GoalError('Temporary workflow expired.')
                await thread(self.db.career_state.update_one,{'_id':owner,'workspace.run_id':run},
                    {'$set':{'workspace.worker_until':now()+timedelta(seconds=180)}})
                snapshot=await self.graph.aget_state(config)
                token=(snapshot.values.get('cache') or {}).get('token')
                if token:await thread(self.db.research_contexts.update_one,{'lease.token':token},
                    {'$set':{'lease.expires_at':now()+timedelta(seconds=180)}})
            recovery=recover_responses.set(True);observer=validation_progress.set(repairing)
            try:
                with tracing_context(enabled=False):
                    seconds=180 if research_search.enabled(self) or state.values.get('smart_search') else 60
                    async with asyncio.timeout(seconds) as budget:
                        timer=validation_budget.set(budget)
                        try:await self.graph.ainvoke(value,config=config,durability='sync')
                        finally:validation_budget.reset(timer)
            finally:
                validation_progress.reset(observer);recover_responses.reset(recovery)
        except asyncio.CancelledError:
            raise
        except (AIError,GoalError,TimeoutError,ValueError,PyMongoError) as error:
            try:
                await thread(self.workspaces.check,owner,session,w['revision'])
                quota=isinstance(error,AIError) and error.code=='rate_limited'
                retry=max(1,int(error.retry_after or 61)) if quota else None
                if quota:
                    checkpoint=await self.graph.aget_state(config)
                    token=(checkpoint.values.get('cache') or {}).get('token')
                    if token:
                        await thread(self.db.research_contexts.update_one,{'lease.token':token},{'$set':{'lease.expires_at':now()+timedelta(seconds=retry+120)}})
                message=f'The AI provider quota was reached. Resuming automatically in {retry} seconds.' if quota else error.message if isinstance(error,GoalError) else f'The input leaves insufficient output room in the configured model context ({error.input_count} estimated). Shorten the saved career context before retrying.' if isinstance(error,AIError) and error.code=='input_limit' else 'Research could not finish. Your latest career goal is saved; retry research.'
                await thread(self.workspaces.phase,owner,session,run,'waiting_quota' if quota else 'research_failed',error=message,error_code=error.code if isinstance(error,AIError) else 'research_unavailable',retry_after=retry)
                if quota:
                    await thread(self.db.career_state.update_one,{'_id':owner,'workspace.run_id':run},{'$set':{'workspace.worker_until':now()+timedelta(seconds=retry+180)}})
                    await asyncio.sleep(retry)
                    # Release lease before resuming the saved failed node.
                    await thread(self.db.career_state.update_one,{'_id':owner,'workspace.run_id':run},{'$unset':{'workspace.worker_until':''}})
                    return not self.stopping
                else:
                    goal=(await thread(self.app.state.goal_store.current,owner))['goal']
                    state=await self.graph.aget_state(config)
                    token=(state.values.get('cache') or {}).get('token')
                    if token and goal:await thread(self.app.state.research_store.fail,context_for(goal),token,'unavailable')
            except GoalError:pass
        finally:
            if asyncio.current_task().cancelling() and not self.stopping:
                # Cancellation can also arrive inside the quota-wait handler.
                try:
                    checkpoint=await self.graph.aget_state(config)
                    token=(checkpoint.values.get('cache') or {}).get('token')
                    if token and not checkpoint.values.get('research_id'):
                        old_goal=await thread(self.app.state.research_store.records.get_private,'career_goals',checkpoint.values.get('goal_id',str(row['goal_id'])),owner)
                        if old_goal:await thread(self.app.state.research_store.fail,context_for(old_goal),token,'unavailable')
                except (GoalError,PyMongoError,ValueError):pass
            await thread(self.db.career_state.update_one,{'_id':owner,'workspace.run_id':run},{'$unset':{'workspace.worker_until':''}})
            # Refresh replacement JD may have arrived while the older run was active.
            latest=await thread(self.workspaces.row,owner)
            if not self.stopping and latest.get('workspace',{}).get('run_id')!=run:
                if self.tasks.get(owner) is asyncio.current_task():
                    self.tasks.pop(owner,None);self.launch(owner)

    async def close(self):
        self.stopping=True
        tasks=[*self.tasks.values(),*[v['task'] for v in self.early.values()],*[v['task'] for v in self.seeds.values()]]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

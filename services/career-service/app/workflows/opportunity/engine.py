"""Checkpointed fan-out/fan-in research with durable jobs and independently saved branches."""
import asyncio
import json
import logging
import time
import tiktoken
from datetime import timedelta
from typing import Annotated,TypedDict
from uuid import uuid4
from bson import ObjectId
from langgraph.graph import StateGraph,START,END
from langgraph.types import Send
from langgraph.checkpoint.mongodb import MongoDBSaver
from langsmith import tracing_context
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput
from app.ai.recovery import recover_responses,validation_feedback
from app.ai.waiting import quota_progress
from app.ai.metrics import usage_observer
from app.clients.search_sources import SourceRateLimit
from app.repositories.goals import GoalError,now,fingerprint
from app.schemas.analysis import ResearchContext,ResearchSource,InterviewResearch,Generation
from app.schemas.opportunity import CATEGORIES,FIELDS,CategoryResult,OpportunityReport,Summary
from .store import OpportunityStore
from .sources import pool
from app.domain.review import MAPPING_VERSION
from .domain import public_opportunity,validate_claims,compatibility,summary_input,dedupe_findings,supported_claims

logger=logging.getLogger('uvicorn.error.opportunity')

def availability_issues(settings,ai,source):
    """Capability codes only: never expose settings values or provider credentials."""
    if not settings.enabled:return ['research_disabled']
    issues=[]
    if not getattr(getattr(ai,'settings',None),'enabled',False):issues.append('reasoning_disabled')
    if not getattr(ai,'context_enabled',False):issues.append('gemini_not_configured')
    if not callable(getattr(source,'collect_opportunity_query',None)) or not getattr(source,'configured',True):issues.append('brave_not_configured')
    if getattr(source,'brave_mode','')!='llm_context':issues.append('brave_llm_context_required')
    return issues

def merge(left,right):return {**left,**right}
class State(TypedDict,total=False):
    job_id:str
    results:Annotated[dict,merge]
    summary:dict
    category:str
    research_id:str

class OpportunityEngine:
    def __init__(self,app,db,settings,ai):
        self.app=app;self.settings=settings;self.ai=ai;self.store=OpportunityStore(db,settings);self.db=self.store.db
        self.tasks={};self.stopping=False;self.slots=asyncio.Semaphore(settings.concurrency)
        source=app.state.research_client
        self.source=source.for_opportunity() if callable(getattr(source,'for_opportunity',None)) else source
        self.availability_issues=availability_issues(settings,ai,self.source)
        self.available=not self.availability_issues
        graph=StateGraph(State)
        for name,node in [('load_context',self.load),('cache_and_plan',self.plan),('research_category',self.branch),('quality',self.quality),('summarize',self.summarize),('validate_persist',self.persist)]:graph.add_node(name,node)
        graph.add_edge(START,'load_context');graph.add_edge('load_context','cache_and_plan')
        graph.add_conditional_edges('cache_and_plan',self.fanout);graph.add_edge('research_category','quality');graph.add_edge('quality','summarize');graph.add_edge('summarize','validate_persist');graph.add_edge('validate_persist',END)
        saver=MongoDBSaver(db.client,db_name=db.name,checkpoint_collection_name='career_checkpoints',writes_collection_name='career_checkpoint_writes',ttl=86400)
        self.graph=graph.compile(checkpointer=saver)
        self.sweeper=asyncio.create_task(self.recover())

    async def job(self,state):return await thread(self.store.rows.find_one,{'_id':state['job_id']})
    async def load(self,state):
        job=await self.job(state)
        if not job:raise GoalError('Research run is no longer available.',404)
        return {'results':{k:v for k,v in job['categories'].items() if v['status'] not in ('pending','running')}}

    async def generate(self,job,stage,data,validate=None):
        # Bounded schema repair for this pipeline; never inherit unbounded legacy recovery.
        step=stage+'_'+fingerprint(data)[:24]
        prior=job.get('model_recovery',{}).get(step,{})
        invalids=prior.get('invalid_responses',0)
        recovery=recover_responses.set(False);feedback=validation_feedback.set(prior.get('feedback'));waiting=quota_progress.set(None)
        started=time.monotonic();usage=[];attempts=0;observer=usage_observer.set(usage.append)
        try:
            if invalids>self.settings.schema_repairs:raise AIError('invalid_output',reason=prior.get('feedback',{}).get('reason'))
            for attempt in range(self.settings.schema_repairs+1-invalids):
                try:
                    attempts+=1
                    result=await self.ai.generate(AIInput(stage=stage,context=json.dumps(data,separators=(',',':'),ensure_ascii=False)),
                        Operation(job['owner'],job['goal_id'],stage),current_revision=lambda:job['goal_id'],validate_output=validate)
                    if validate:validate(result.data)
                    return result.data
                except AIError as error:
                    logger.warning('node=%s attempt=%s error_code=%s reason=%s limit_scope=%s',stage,attempt+1,error.code,error.reason,error.limit_scope)
                    if error.code not in ('invalid_output','incomplete_output'):raise
                    invalids+=1
                    correction={'reason':error.reason or 'schema_validation','fields':list(error.fields)}
                    await thread(self.store.update,job['_id'],job['worker_token'],**{
                        'model_recovery.'+step:{'invalid_responses':invalids,'feedback':correction}})
                    if invalids>self.settings.schema_repairs:raise
                    validation_feedback.set(correction)
        finally:
            usage_observer.reset(observer);quota_progress.reset(waiting);validation_feedback.reset(feedback);recover_responses.reset(recovery)
            increments={f'metrics.{stage}.model_calls':attempts,f'metrics.{stage}.latency_ms':int((time.monotonic()-started)*1000)}
            for name in ('prompt_tokens','completion_tokens','total_tokens'):
                count=sum(v.get(name,0) for v in usage)
                if count:increments[f'metrics.{stage}.{name}']=count
            await asyncio.shield(thread(self.store.rows.update_one,{'_id':job['_id'],'worker_token':job['worker_token']},{'$inc':increments}))
            logger.info('node=%s latency_ms=%s',stage,int((time.monotonic()-started)*1000))

    async def plan(self,state):
        job=await self.job(state)
        if job['queries']:return {}
        plan=await self.generate(job,'opportunity_plan',{'opportunity':job['public'],'recruitment_year':now().year})
        queries={};seen=set()
        for category in CATEGORIES:
            values=[]
            if job['public']['company'] or category=='interview_intelligence':
                for value in getattr(plan,category):
                    query=' '.join(value.split())[:180];key=query.casefold()
                    if 3<=len(query) and key not in seen:values.append(query);seen.add(key)
            if not values and (job['public']['company'] or category=='interview_intelligence'):
                focus={'interview_intelligence':'interview process assessment questions','internship_insights':'internship compensation experience mentorship','company_intelligence':'products technology stack recent developments'}[category]
                base=' '.join(str(job['public'].get(k) or '') for k in ('company','role','location'))
                values=[(base+' '+str(now().year)+' '+focus)[:180]]
            queries[category]=values[:self.settings.max_searches]
        await thread(self.store.update,job['_id'],job['worker_token'],queries=queries)
        return {}

    def fanout(self,state):return [Send('research_category',{'job_id':state['job_id'],'category':category}) for category in CATEGORIES]

    async def branch(self,state):
        category=state['category'];job=await self.job(state);old=CategoryResult.model_validate(job['categories'][category])
        if old.status not in ('pending','running'):return {'results':{category:old.model_dump(mode='json')}}
        started=time.monotonic();stamp=now();queries=job['queries'].get(category,[]);history=job.get('history',{}).get(category,[])
        evidence=[ResearchSource.model_validate(v) for v in job.get('evidence',{}).get(category,[])]
        evaluated=list(job.get('evaluated',{}).get(category,[]))
        findings=old.findings;rejected=0;model_calls=0;error_code=None;pending=False
        if not job['public']['company'] and category!='interview_intelligence':
            result=CategoryResult(status='not_applicable',missing_fields=list(FIELDS[category]),warnings=['No company is specified; employer-specific claims were not researched.'],researched_at=stamp,expires_at=stamp+timedelta(hours=self.settings.freshness_hours))
            await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{category}':result.model_dump(mode='json')})
            return {'results':{category:result.model_dump(mode='json')}}
        await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{category}.status':'running'})
        try:
            rounds=0 if job.get('evaluation_complete',{}).get(category) else min(self.settings.max_searches,1+self.settings.max_followups)
            for index in range(rounds):
                # A paid retrieval is saved before evaluation, so quota/restart retries reuse it.
                if index>=len(history):
                    query=queries[index] if index<len(queries) else None
                    if not query:break
                    sources=None
                    for attempt in range(self.settings.retries+1):
                        try:
                            async with self.slots:
                                async with asyncio.timeout(self.settings.timeout_seconds):
                                    sources=await self.source.collect_opportunity_query(ResearchContext.model_validate(job['context']),query)
                            break
                        except (GoalError,TimeoutError) as error:
                            # Retry only transient network/server errors, never credentials/parameters/billing.
                            retryable=isinstance(error,TimeoutError) or any(v in str(error).casefold() for v in ('timed out','connect','temporarily unavailable'))
                            if not retryable or attempt==self.settings.retries:raise
                            await asyncio.sleep(.5*2**attempt)
                    history.append(query)
                    evidence=pool([s.model_dump(mode='json') for s in [*(sources or []),*evidence]])[:self.settings.max_searches*5]
                    await thread(self.store.update,job['_id'],job['worker_token'],**{f'evidence.{category}':[s.model_dump(mode='json') for s in evidence],f'history.{category}':history})
                # Quota pauses resume the unfinished evaluation, not earlier successful ones.
                if history[index] in evaluated:continue
                if not evidence:continue
                # Complete bounded excerpts; schema/prompt must also fit Groq's unchanged 4k cap.
                selected=[];encoding=tiktoken.get_encoding('o200k_harmony')
                for source in evidence[:self.settings.max_searches*5]:
                    candidate=[*selected,source]
                    if len(encoding.encode(json.dumps([s.model_dump(mode='json') for s in candidate]),disallowed_special=()))<=self.settings.evidence_tokens:selected=candidate
                if not selected:break
                def validate(output):supported_claims(output,category,selected,job['public'])
                model_calls+=1
                output=await self.generate(job,'opportunity_evaluate',{'opportunity':job['public'],'category':category,'allowed_fields':FIELDS[category],
                    'existing_findings':[{'field':f.field,'value':f.value[:120],'scope':f.scope} for f in findings[:8]],
                    'sources':[{'ref':i,'title':s.title,'url':s.url,'excerpt':s.evidence,'published_date':s.published_date.isoformat() if s.published_date else None,'reliability':s.reliability} for i,s in enumerate(selected)]},validate)
                current,discarded=supported_claims(output,category,selected,job['public']);rejected+=discarded
                findings=dedupe_findings(category,[*findings,*current])
                present={f.field for f in findings}
                adequate=set(FIELDS[category])<=present and all(f.confidence in ('high','medium') and f.scope=='exact' and not f.conflict_group for f in findings)
                query=' '.join((output.follow_up_query or '').split())[:180]
                complete=adequate or not query or query.casefold() in {q.casefold() for q in history} or index+1>=rounds
                if not complete:
                    if len(queries)<=index+1:queries.append(query)
                    else:queries[index+1]=query
                evaluated.append(history[index])
                # Findings, next query and evaluation cursor commit together before any next call.
                await thread(self.store.update,job['_id'],job['worker_token'],**{
                    f'categories.{category}.findings':[f.model_dump(mode='json') for f in findings],
                    f'evaluated.{category}':evaluated,f'evaluation_complete.{category}':complete,f'queries.{category}':queries})
                if complete:break
        except AIError as error:
            error_code=error.code
            logger.warning('category=%s error_code=%s reason=%s limit_scope=%s',category,error.code,error.reason,error.limit_scope)
            if error.code=='rate_limited':
                pending=True
                await thread(self.store.update,job['_id'],job['worker_token'],next_attempt_at=now()+timedelta(seconds=max(1,min(3600,error.retry_after or 60))),limit_scope=error.limit_scope,provider=error.provider)
        except SourceRateLimit as error:
            error_code='source_rate_limited'
            waits=job.get('source_waits',{}).get(category,0)
            if waits<self.settings.retries:
                pending=True
                await thread(self.store.update,job['_id'],job['worker_token'],next_attempt_at=now()+timedelta(seconds=error.retry_after),**{f'source_waits.{category}':waits+1})
        except (GoalError,TimeoutError,ValueError) as error:
            error_code='source_timeout' if isinstance(error,TimeoutError) else 'source_unavailable'
            logger.warning('category=%s error_code=%s exception_type=%s',category,error_code,type(error).__name__)
        missing=[field for field in FIELDS[category] if field not in {f.field for f in findings}]
        status='pending' if pending else 'partial' if error_code and findings else 'failed' if error_code else 'completed'
        warnings=[]
        if rejected:warnings.append('Unsupported claims were excluded; only independently validated citations are shown.')
        if missing:warnings.append('Some requested information has no supported evidence.')
        if any(f.confidence in ('low','insufficient_evidence') for f in findings):warnings.append('Some findings have limited confidence; inspect their sources before relying on them.')
        if any(f.scope!='exact' for f in findings):warnings.append('Some reports concern related roles, locations or employment types.')
        if any(f.conflict_group for f in findings):warnings.append('Conflicting reports are preserved separately; figures are not averaged.')
        result=CategoryResult(status=status,findings=findings,missing_fields=missing,warnings=warnings,error_code=error_code,
            researched_at=stamp,expires_at=stamp+timedelta(hours=self.settings.incomplete_hours if missing or error_code else self.settings.freshness_hours),
            searches=len(history),model_calls=min(20,old.model_calls+model_calls),latency_ms=int((time.monotonic()-started)*1000))
        await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{category}':result.model_dump(mode='json')})
        logger.info('category=%s status=%s searches=%s model_calls=%s latency_ms=%s',category,status,result.searches,result.model_calls,result.latency_ms)
        return {'results':{category:result.model_dump(mode='json')}}

    async def quality(self,state):
        # Revalidate persisted branch values; missing citations can never reach summary/storage.
        job=await self.job(state);categories={k:CategoryResult.model_validate(v) for k,v in job['categories'].items()}
        sources={s.source_id:s for s in pool([*job.get('sources',[]),*[s for values in job.get('evidence',{}).values() for s in values]])}
        for key,result in categories.items():
            valid=[f for f in result.findings if all(s in sources and q in (sources[s].evidence or '') for s,q in zip(f.source_ids,f.quotes))]
            if len(valid)!=len(result.findings):
                result.findings=valid;result.warnings=(result.warnings+['Some claims exceeded the bounded evidence budget.'])[:10]
                result.missing_fields=[f for f in FIELDS[key] if f not in {v.field for v in valid}]
            await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{key}':result.model_dump(mode='json')})
        return {'results':{k:v.model_dump(mode='json') for k,v in categories.items()}}

    async def summarize(self,state):
        job=await self.job(state);categories={k:CategoryResult.model_validate(v) for k,v in state['results'].items()};facts=summary_input(categories)
        if not facts or any(v.status=='pending' for v in categories.values()):return {'summary':{}}
        ids={v['id'] for v in facts}
        def validate(output):
            if any(ref not in ids for refs in output.model_dump().values() for ref in refs):raise AIError('invalid_output',True,reason='provenance')
        try:summary=await self.generate(job,'opportunity_summary',{'validated_findings':facts},validate)
        except AIError:
            await thread(self.store.update,job['_id'],job['worker_token'],summary_error=True)
            return {'summary':{}}
        return {'summary':summary.model_dump()}

    async def persist(self,state):
        job=await self.job(state);identifier=job['_id'];token=job['worker_token'];cache=job['cache'];context=ResearchContext.model_validate(job['context'])
        categories={k:CategoryResult.model_validate(v) for k,v in job['categories'].items()}
        pending=any(v.status=='pending' for v in categories.values());applicable=[v for v in categories.values() if v.status!='not_applicable'];failed=bool(applicable) and all(v.status=='failed' for v in applicable)
        complete=all(v.status in ('completed','not_applicable') for v in categories.values())
        status='failed' if failed else 'completed' if complete else 'partial'
        stamp=now();sources=pool([*job.get('sources',[]),*[s for values in job.get('evidence',{}).values() for s in values]])
        primary=getattr(self.ai,'primary',self.ai);coordinator=getattr(self.ai,'context',None)
        models={k:v for k,v in {'reasoning':getattr(getattr(primary,'settings',None),'model',None),'coordination':getattr(getattr(coordinator,'settings',None),'model',None)}.items() if v}
        report=OpportunityReport(models=models,fingerprint=context.details_fingerprint,opportunity_id=context.details_fingerprint if context.company else None,
            employment_type=job['public']['employment_type'],job_url=job['public']['job_url'],categories=categories,summary=Summary.model_validate(state.get('summary',{})),status=status,
            researched_at=stamp,expires_at=min(v.expires_at or stamp for v in categories.values()),warnings=['Summary uses only validated cited extracts.']+(['Overall summary unavailable; validated category findings remain available.'] if job.get('summary_error') else []))
        skills,process=compatibility(categories,sources)
        record=InterviewResearch(_id=str(ObjectId()),version=cache['version'],skill_mapping_version=MAPPING_VERSION,created_at=stamp,updated_at=stamp,
            **context.model_dump(),intelligence=report,sources=sources,skills=skills,process=process,
            research_status='failed' if failed else 'succeeded' if skills or process.stages else 'no_findings',last_researched_at=stamp,
            generation=Generation(provider=getattr(getattr(primary,'settings',None),'provider','unreported'),model=models.get('reasoning','unreported'),prompt_version='opportunity-v1',generated_at=stamp))
        record=await thread(self.store.research.finish,context,cache['token'],record)
        await thread(self.store.update,identifier,token,research_id=record.id,status='pending' if pending else status,finished=not pending,summary=report.summary.model_dump())
        await self.attach({**job,'research_id':record.id,'status':status,'finished':not pending})
        return {'research_id':record.id}

    def launch(self,identifier):
        if not self.available or self.stopping or identifier in self.tasks:return
        task=asyncio.create_task(self.execute(identifier));self.tasks[identifier]=task
        def done(value):
            self.tasks.pop(identifier,None)
            if not value.cancelled() and value.exception():logger.warning('Opportunity worker stopped; durable recovery will retry.')
        task.add_done_callback(done)

    async def recover(self):
        while not self.stopping:
            try:
                if self.available:
                    for row in await thread(self.store.due):self.launch(row['_id'])
            except Exception:logger.warning('Opportunity recovery temporarily unavailable.')
            await asyncio.sleep(3)

    async def start(self,owner,goal,selection,session,run,key,command):
        if not self.available:raise GoalError('Opportunity Intelligence is unavailable on this server. Reload to see its availability details.',503)
        job=await thread(self.store.start,owner,goal,selection,session,run,key,command)
        if job['finished']:await self.attach(job)
        else:self.launch(job['_id'])
        return job

    async def execute(self,identifier):
        token=uuid4().hex;job=await thread(self.store.claim,identifier,token)
        if not job:return
        context=ResearchContext.model_validate(job['context']);cache=None
        try:
            cached=await thread(self.store.cached,context)
            if cached and cached.intelligence.researched_at>=job['created_at'] and all(v.status not in ('pending','running') and v.expires_at and v.expires_at>now() for v in cached.intelligence.categories.values()):
                await thread(self.store.update,identifier,token,research_id=cached.id,categories={k:v.model_dump(mode='json') for k,v in cached.intelligence.categories.items()},summary=cached.intelligence.summary.model_dump(),status=cached.intelligence.status,finished=True)
                await self.attach({**job,'research_id':cached.id});return
            cache=await thread(self.store.research.begin,context,True)
            if cache.get('processing'):
                await thread(self.store.update,identifier,token,status='pending',next_attempt_at=now()+timedelta(seconds=5));return
            await thread(self.store.rows.update_one,{'lease.token':cache['token']},{'$set':{'lease.expires_at':now()+timedelta(seconds=self.settings.run_seconds+60)}})
            await thread(self.store.update,identifier,token,cache=cache)
            # A restarted job can reconstruct from its durable per-category results, even after TTL checkpoint expiry.
            config={'configurable':{'thread_id':identifier+':'+token},'recursion_limit':20,'callbacks':[]}
            with tracing_context(enabled=False):
                async with asyncio.timeout(self.settings.run_seconds):
                    result=await self.graph.ainvoke({'job_id':identifier,'results':{}},config,durability='sync')
        except asyncio.CancelledError:raise
        except (AIError,GoalError,TimeoutError,ValueError) as error:
            code=error.code if isinstance(error,AIError) else 'research_timeout' if isinstance(error,TimeoutError) else 'research_validation_failed' if isinstance(error,ValueError) else 'research_state_changed'
            logger.warning('research_error code=%s exception_type=%s reason=%s',code,type(error).__name__,error.reason if isinstance(error,AIError) else None)
            quota=isinstance(error,AIError) and error.code=='rate_limited'
            latest=await thread(self.store.rows.find_one,{'_id':identifier});updates={}
            for category,value in latest.get('categories',{}).items():
                if value['status'] in ('pending','running'):
                    updates[f'categories.{category}.status']='pending' if quota else 'partial' if value.get('findings') else 'failed'
                    updates[f'categories.{category}.error_code']=code
            partial=any(v['status']=='completed' or v.get('findings') for v in latest.get('categories',{}).values())
            await thread(self.store.update,identifier,token,status='pending' if quota else 'partial' if partial else 'failed',finished=not quota,error_code=code,
                next_attempt_at=now()+timedelta(seconds=max(1,min(3600,error.retry_after or 61)) if quota else 5),**updates)
            interview=latest.get('categories',{}).get('interview_intelligence',{})
            phase='ready' if interview.get('status') in ('completed','partial') else 'waiting_quota' if quota else 'research_failed'
            try:
                await thread(self.app.state.workspace_store.phase,job['owner'],job['session'],job['run'],phase,
                    error=None if phase=='ready' else 'Research is waiting for the AI allowance and will resume automatically.' if quota else 'Research could not finish. Your goal and available findings remain saved.',
                    error_code=None if phase=='ready' else code,retry_after=max(1,min(3600,error.retry_after or 61)) if quota else None)
            except GoalError:pass  # A replaced workspace must not receive this run's error.
        finally:
            if cache and cache.get('token'):await thread(self.store.research.fail,context,cache['token'],'partial')
            await thread(self.store.release,identifier,token)

    async def attach(self,job):
        if not job.get('research_id'):return
        latest=await thread(self.store.rows.find_one,{'_id':job['_id']})
        if latest:job=latest
        record=await thread(self.store.research.records.get_research,job['research_id'])
        if not record:return
        row=await thread(self.app.state.workspace_store.row,job['owner']);w=row.get('workspace',{})
        if str(row.get('goal_id'))!=job['goal_id'] or w.get('run_id')!=job['run']:return
        try:
            await thread(self.store.research.attach,job['owner'],job['goal_id'],job['selection'],job['_id'],job['digest'],record)
            interview=record.intelligence.categories['interview_intelligence']
            phase='ready' if interview.status in ('completed','partial') else 'waiting_quota' if interview.status=='pending' else 'research_failed'
            code=interview.error_code or job.get('error_code')
            waiting=phase=='waiting_quota'
            retry=max(1,int((job['next_attempt_at']-now()).total_seconds())) if waiting else None
            message=('Groq’s local 7,000-token window will reopen shortly; research will resume automatically.' if job.get('limit_scope')=='user' else 'The model provider requested a cooldown. Saved-goal chat remains available.') if waiting and code=='rate_limited' else 'Brave is rate limited; research will resume automatically.' if waiting and code=='source_rate_limited' else 'Interview research is still pending.' if waiting else 'Interview research could not finish. Available findings remain readable.'
            await thread(self.app.state.workspace_store.phase,job['owner'],job['session'],job['run'],phase,research_id=record.id,
                error=None if phase=='ready' else message,error_code=None if phase=='ready' else code or 'research_unavailable',retry_after=retry,limit_scope=job.get('limit_scope'),provider=job.get('provider'))
        except GoalError:pass  # A replacement goal cannot be overwritten by this historical run.

    async def close(self):
        self.stopping=True;self.sweeper.cancel()
        for task in list(self.tasks.values()):task.cancel()
        await asyncio.gather(self.sweeper,*list(self.tasks.values()),return_exceptions=True)

"""Checkpointed fan-out/fan-in research with durable jobs and independently saved branches."""
from elo_shared.model_budget import budget_owner
import asyncio
import json
import logging
import time
import httpx
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
from app.ai.opportunity_contracts import structure_input,triage_input
from app.workflows.model_waits import resume_obsolete_model_waits
from app.clients.search_sources import SourceRateLimit
from app.repositories.goals import GoalError,now,fingerprint
from app.schemas.analysis import ResearchContext,ResearchSource,InterviewResearch,Generation
from app.schemas.opportunity import CATEGORIES,FIELDS,CategoryResult,Finding,OpportunityReport,Summary
from .store import OpportunityStore
from .sources import pool,retain_useful,category_sources,choose_reads
from .queries import ACTIVITIES,planned_queries,topic_map
from .topics import CANDIDATES_PER_SEARCH,TOPIC_CATEGORIES,TOPICS,category_topics,owner,policy,settled
from app.domain.review import MAPPING_VERSION
from .domain import whitespace,public_opportunity,validate_claims,summary_input,dedupe_findings,supported_claims,validated_skill_levels,weighted_skills

logger=logging.getLogger('uvicorn.error.opportunity')
NOT_FOUND_WARNING='Information pertaining to this category was not found in the retrieved sources.'

def select_evidence(sources,budget):
    """Fit exact source passages fairly within the evidence token budget; no budget passes every source whole."""
    if budget is None:return [s for s in sources if s.evidence]
    encoding=tiktoken.get_encoding('o200k_harmony')
    def size(values):
        serialized=json.dumps([s.model_dump(mode='json') for s in values])
        return len(encoding.encode(serialized,disallowed_special=()))
    selected=[]
    for index,source in enumerate(sources):
        # Reserve a fair share for later sources.
        allowance=size(selected)+max(0,(budget-size(selected))//(len(sources)-index))
        low,high=0,len(source.evidence)
        best=None
        while low<=high:
            length=(low+high)//2
            if not length:low=1;continue
            candidate=source.model_copy(update={'evidence':source.evidence[:length]})
            if size([*selected,candidate])<=allowance:
                best=candidate;low=length+1
            else:high=length-1
        if best is not None:selected.append(best)
    return selected


def transient(error):
    """Timeouts, dropped connections and provider outages are retried; configuration and access errors are not."""
    return (isinstance(error,TimeoutError) or getattr(error,'reason',None) in ('timeout','unavailable')
        or isinstance(error.__context__,(httpx.TimeoutException,httpx.TransportError,TimeoutError)))


def availability_issues(settings,ai,source):
    """Capability codes only: never expose settings values or provider credentials."""
    if not settings.enabled:return ['research_disabled']
    issues=[]
    if not getattr(getattr(ai,'settings',None),'enabled',False):issues.append('reasoning_disabled')
    if not getattr(ai,'context_enabled',False):issues.append('model_not_configured')
    if not callable(getattr(source,'collect_opportunity_query',None)) or not getattr(source,'configured',True):issues.append('brave_not_configured' if getattr(source,'provider','brave')=='brave' else 'search_not_configured')
    if getattr(source,'provider','brave')=='brave' and getattr(source,'brave_mode','')!='llm_context':issues.append('brave_llm_context_required')
    return issues

def merge(left,right):return {**left,**right}
def valid_levels(levels,categories):
    # A rating may only cite findings that survived into the saved report.
    ids={f.finding_id for result in categories.values() for f in result.findings}
    return [{**level,'finding_ids':[i for i in level.get('finding_ids',[]) if i in ids],
             'reported_examples':[e for e in level.get('reported_examples',[]) if e.get('finding_id') in ids]} for level in levels or []][:60]

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
        # 'provider' is the persisted channel id; 'backend' names the search service.
        if getattr(self.source,'backend',getattr(self.source,'provider','brave'))!='brave':
            self.store.research.policy+=':'+self.source.cache_policy
        self.availability_issues=availability_issues(settings,ai,self.source)
        self.available=not self.availability_issues
        graph=StateGraph(State)
        for name,node in [('load_context',self.load),('cache_and_plan',self.plan),('search_topics',self.search_topics),('research_category',self.branch),('quality',self.quality),('summarize',self.summarize),('rate_skills',self.rate_skills),('validate_persist',self.persist)]:graph.add_node(name,node)
        graph.add_edge(START,'load_context');graph.add_edge('load_context','cache_and_plan')
        graph.add_edge('cache_and_plan','search_topics');graph.add_conditional_edges('search_topics',self.fanout);graph.add_edge('research_category','quality');graph.add_edge('quality','summarize');graph.add_edge('summarize','rate_skills');graph.add_edge('rate_skills','validate_persist');graph.add_edge('validate_persist',END)
        saver=MongoDBSaver(db.client,db_name=db.name,checkpoint_collection_name='career_checkpoints',writes_collection_name='career_checkpoint_writes',ttl=86400)
        self.graph=graph.compile(checkpointer=saver)
        self.sweeper=asyncio.create_task(self.recover())

    async def job(self,state):return await thread(self.store.rows.find_one,{'_id':state['job_id']})
    async def load(self,state):
        job=await self.job(state)
        if not job:raise GoalError('Research run is no longer available.',404)
        missing=set(CATEGORIES)-set(job['categories'])
        if missing:
            updates={f'categories.{k}':CategoryResult().model_dump(mode='json') for k in missing}
            for category,result in job['categories'].items():
                kept=[f for f in result.get('findings',[]) if f['field'] in FIELDS[category]]
                if len(kept)!=len(result.get('findings',[])):
                    # Re-evaluate existing paid evidence under the new field contract.
                    updates.update({f'categories.{category}':{**result,'findings':kept,'status':'pending','error_code':None},
                                    f'evaluated.{category}':[],f'evaluation_complete.{category}':False})
            await thread(self.store.update,job['_id'],job['worker_token'],**{
                **updates,'requested':list(dict.fromkeys([*job.get('requested',[]),*missing])),
                'queries_planned':False,'prefetched':True})
            job=await self.job(state)
        return {'results':{k:v for k,v in job['categories'].items() if v['status'] not in ('pending','running')}}

    async def generate(self,job,stage,data,validate=None):
        # Bounded schema repair for this pipeline.
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
                    logger.warning('node=%s attempt=%s error_code=%s reason=%s limit_scope=%s violations=%s',stage,attempt+1,error.code,error.reason,error.limit_scope,json.dumps(list(error.violations),separators=(',',':')))
                    if error.code not in ('invalid_output','incomplete_output'):raise
                    invalids+=1
                    correction={'reason':error.reason or ('incomplete_json' if error.code=='incomplete_output' else 'schema_validation'),'fields':list(error.fields),'issues':list(error.violations)}
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
        await thread(self.store.rows.update_one,{'_id':job['_id'],'worker_token':job['worker_token']},{'$addToSet':{'activities':'checking_sources'}})
        if all(v['status'] in ('completed','not_applicable') for v in job['categories'].values()):return {}
        planned=topic_map(job.get('queries'))
        if planned and job.get('queries_planned'):return {}
        plan=await self.generate(job,'opportunity_plan',{'opportunity':job['public'],'recruitment_year':now().year,'previous_queries':topic_map(job.get('history'))})
        queries=planned_queries(plan,self.settings.topic_searches,job['public'])
        if job.get('prefetched'):
            # Successful paid prefetch queries stay first.
            queries={topic:list(dict.fromkeys([*topic_map(job.get('history')).get(topic,[]),*queries[topic]]))[:self.settings.topic_searches] for topic in TOPICS}
        await thread(self.store.update,job['_id'],job['worker_token'],queries=queries,queries_planned=True)
        return {}

    async def search_topic(self,job_id,topic):
        """Run a topic's next planned search within its search allowances; returns the new candidate pages."""
        job=await self.job({'job_id':job_id})
        history=topic_map(job.get('history')).get(topic,[])
        queries=topic_map(job.get('queries')).get(topic) or planned_queries(None,self.settings.topic_searches,job['public'])[topic]
        found=pool(topic_map(job.get('evidence')).get(topic,[]))
        read=topic_map(job.get('read')).get(topic,[])
        if len(history)>=min(self.settings.topic_searches,len(queries)) or len(read)>=policy(topic).max_urls:return []
        if not await thread(self.store.reserve_search,job['_id'],job['worker_token'],self.settings.run_searches):return []
        query=queries[len(history)]
        await thread(self.store.rows.update_one,{'_id':job['_id'],'worker_token':job['worker_token']},{'$addToSet':{'activities':ACTIVITIES[owner(topic)]}})
        sources=None
        for attempt in range(self.settings.retries+1):
            try:
                async with self.slots:
                    async with asyncio.timeout(self.settings.timeout_seconds):
                        with budget_owner(job['owner']):
                            sources=await self.source.collect_opportunity_query(ResearchContext.model_validate(job['context']),query,
                                max_sources=CANDIDATES_PER_SEARCH)
                break
            except (GoalError,TimeoutError) as error:
                if not transient(error) or attempt==self.settings.retries:raise
                await asyncio.sleep(.5*2**attempt)
        known={s.source_id for s in found}
        fresh=[s for s in pool([s.model_dump(mode='json') for s in sources or []]) if s.source_id not in known]
        await thread(self.store.update,job['_id'],job['worker_token'],**{f'history.{topic}':[*history,query],
            f'evidence.{topic}':[s.model_dump(mode='json') for s in [*found,*fresh]]})
        return fresh

    async def search_topics(self,state):
        """Every requested topic's first search runs concurrently before any category evaluates."""
        job=await self.job(state)
        requested=[c for c,v in job['categories'].items() if v['status'] in ('pending','running')]
        history=topic_map(job.get('history'))
        topics=[t for c in requested for t in category_topics(c) if not history.get(t)]
        async def first(topic):
            try:await self.search_topic(job['_id'],topic)
            except (GoalError,TimeoutError,SourceRateLimit,ValueError) as error:
                # The owning category retries the search and reports its outcome.
                logger.warning('topic=%s first_search_failed exception_type=%s',topic,type(error).__name__)
        await asyncio.gather(*(first(t) for t in topics))
        return {}

    def fanout(self,state):return [Send('research_category',{'job_id':state['job_id'],'category':category}) for category in CATEGORIES]

    def category_evidence(self,job,category):
        """Every candidate page found for this category's topics, plus its previously retained sources."""
        evidence=topic_map(job.get('evidence'))
        return pool([*job.get('retained_sources',{}).get(category,[]),*[s for t in FIELDS[category] for s in evidence.get(t,[])]])

    @staticmethod
    def shared(job,category):
        """Findings other categories extracted for this category's topics, with their cited sources."""
        entries=job.get('shared',{}).get(category,[])
        return [Finding.model_validate(e['finding']) for e in entries],pool([s for e in entries for s in e['sources']])

    async def triage(self,job,topics,candidates):
        """Map each candidate page to the needed topics its title, URL, date and preview suggest it answers."""
        context=triage_input(job['public'],topics,candidates)
        def validate(output):
            problems=[{'field':f'pages.{i}','issue':'unknown_page_or_topic'} for i,page in enumerate(output.pages)
                if page.ref>=len(candidates) or not set(page.topics)<=set(topics)]
            if problems:raise AIError('invalid_output',True,reason='provenance',fields=('pages',),violations=problems)
        try:output=await self.generate(job,'opportunity_triage',context,validate)
        except AIError as error:
            if error.code not in ('invalid_output','incomplete_output'):raise
            return None
        flags={}
        for page in output.pages:flags.setdefault(candidates[page.ref].source_id,set()).update(page.topics)
        return flags

    async def share(self,job,category,findings,sources):
        """Hand findings for another category's topics to that category, with only their cited passages."""
        by_id={s.source_id:s for s in sources};entries={}
        for finding in findings:
            cited=[by_id[sid].model_copy(update={'evidence':quote}).model_dump(mode='json') for sid,quote in zip(finding.source_ids,finding.quotes)]
            for target in TOPIC_CATEGORIES[finding.field]:
                if target!=category:entries.setdefault(target,[]).append({'finding':finding.model_dump(mode='json'),'sources':cited})
        if entries:
            await thread(self.store.rows.update_one,{'_id':job['_id'],'worker_token':job['worker_token']},
                {'$push':{f'shared.{target}':{'$each':values} for target,values in entries.items()}})

    async def branch(self,state):
        category=state['category'];job=await self.job(state);old=CategoryResult.model_validate(job['categories'][category])
        if old.status not in ('pending','running'):return {'results':{category:old.model_dump(mode='json')}}
        started=time.monotonic();stamp=now();own=category_topics(category)
        fields=[*FIELDS[category],*[t for t in TOPICS if t not in FIELDS[category]]]
        evaluated=set(job.get('evaluated',{}).get(category,[]))
        triaged=set(job.get('triaged',{}).get(category,[]))
        flags={sid:set(values) for sid,values in job.get('flags',{}).get(category,{}).items()}
        findings=old.findings;rejected=0;model_calls=0;error_code=None;pending=False;round_error=None
        relevant_ids=set(job.get('relevant_sources',{}).get(category,[]))|set(old.source_ids)
        evidence=self.category_evidence(job,category)
        await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{category}.status':'running'})
        try:
            rounds=0 if job.get('evaluation_complete',{}).get(category) else self.settings.topic_searches
            for index in range(rounds):
                job=await self.job(state);read=topic_map(job.get('read'))
                others,other_sources=self.shared(job,category)
                evidence=self.category_evidence(job,category)
                # A backed topic leaves the search list, whichever category found its sources.
                due=[t for t in own if not settled(t,[*findings,*others],[*evidence,*other_sources]) and len(read.get(t,[]))<policy(t).max_urls]
                if not due:
                    await thread(self.store.update,job['_id'],job['worker_token'],**{f'evaluation_complete.{category}':True})
                    break
                history=topic_map(job.get('history'))
                searchable=[t for t in due if len(history.get(t,[]))<=index]
                if searchable:
                    async with asyncio.TaskGroup() as group:
                        for topic in searchable:group.create_task(self.search_topic(job['_id'],topic))
                    job=await self.job(state);evidence=self.category_evidence(job,category)
                found={t:pool(topic_map(job.get('evidence')).get(t,[])) for t in due}
                unseen=pool([s.model_dump(mode='json') for t in due for s in found[t] if s.source_id not in triaged and s.evidence])
                if unseen:
                    model_calls+=1
                    result=await self.triage(job,due,unseen)
                    # Without a usable triage, each topic reads its own top-ranked results.
                    if result is None:result={s.source_id:{t for t in due if s.source_id in {f.source_id for f in found[t]}} for s in unseen}
                    for sid,topics in result.items():flags.setdefault(sid,set()).update(topics)
                    triaged.update(s.source_id for s in unseen)
                    await thread(self.store.update,job['_id'],job['worker_token'],**{f'triaged.{category}':sorted(triaged),
                        f'flags.{category}':{sid:sorted(values) for sid,values in flags.items()}})
                picks,reads=choose_reads(due,found,flags,read)
                fresh=[s for s in picks if s.source_id not in evaluated]
                if fresh:
                    # Keep useful passages within the model evidence allowance.
                    selected=select_evidence(fresh,self.settings.evidence_tokens)
                    def validate(output):
                        if any(ref<0 or ref>=len(selected) for ref in output.relevant_refs):
                            raise AIError('invalid_output',True,reason='provenance',fields=('relevant_refs',),violations=[{'field':'relevant_refs','issue':'source_index_out_of_range'}])
                        return supported_claims(output,category,selected,job['public'])
                    context=structure_input(job['public'],category,selected,findings,fields)
                    if context['evidence']:
                        model_calls+=1
                        try:
                            output=await self.generate(job,'opportunity_structure',context,validate)
                            relevant_ids.update(selected[ref].source_id for ref in output.relevant_refs)
                            current,discarded=supported_claims(output,category,selected,job['public']);rejected+=discarded
                            findings=dedupe_findings(category,[*findings,*[f for f in current if f.field in FIELDS[category]]])
                            await self.share(job,category,[f for f in current if f.field not in FIELDS[category]],selected)
                        except AIError as error:
                            # Record an unusable round and try the next search.
                            if error.code not in ('invalid_output','incomplete_output'):raise
                            round_error=error.code
                    evaluated.update(s.source_id for s in fresh)
                complete=index+1>=rounds
                # Findings, triage and read cursors commit together before any next call.
                await thread(self.store.update,job['_id'],job['worker_token'],**{
                    f'categories.{category}.findings':[f.model_dump(mode='json') for f in findings],
                    f'evaluated.{category}':sorted(evaluated),f'triaged.{category}':sorted(triaged),
                    f'flags.{category}':{sid:sorted(values) for sid,values in flags.items()},
                    **{f'read.{t}':sorted({*read.get(t,[]),*ids}) for t,ids in reads.items() if ids},
                    f'evaluation_complete.{category}':complete,f'relevant_sources.{category}':list(relevant_ids)})
                if complete:break
        except* (AIError,SourceRateLimit,GoalError,TimeoutError,ValueError) as group:
            error=group.exceptions[0]
            while isinstance(error,BaseExceptionGroup):error=error.exceptions[0]
            if isinstance(error,AIError):
                error_code=error.code
                logger.warning('category=%s error_code=%s reason=%s limit_scope=%s',category,error.code,error.reason,error.limit_scope)
                if error.code=='rate_limited':
                    pending=True
                    await thread(self.store.update,job['_id'],job['worker_token'],next_attempt_at=now()+timedelta(seconds=max(1,min(3600,error.retry_after or 60))),limit_scope=error.limit_scope,provider=error.provider)
            elif isinstance(error,SourceRateLimit):
                error_code='source_rate_limited'
                waits=job.get('source_waits',{}).get(category,0)
                if waits<self.settings.retries:
                    pending=True
                    await thread(self.store.update,job['_id'],job['worker_token'],next_attempt_at=now()+timedelta(seconds=error.retry_after),provider=error.provider,limit_scope='provider',**{f'source_waits.{category}':waits+1})
            else:
                error_code='source_timeout' if isinstance(error,TimeoutError) else 'source_unavailable'
                logger.warning('category=%s error_code=%s exception_type=%s',category,error_code,type(error).__name__)
        # Every round failed validation and nothing was kept: report the round error.
        if round_error and not findings and not error_code and not pending:error_code=round_error
        evidence=self.category_evidence(await self.job(state),category)
        findings,retained=retain_useful(category,findings,evidence,relevant_ids)
        await thread(self.store.update,job['_id'],job['worker_token'],**{f'retained_sources.{category}':[s.model_dump(mode='json') for s in retained]})
        outcome=None if pending else 'validation_failed' if error_code in ('invalid_output','incomplete_output') else 'provider_failed' if error_code else 'findings_found' if findings else 'information_not_found' if relevant_ids else 'no_relevant_sources'
        missing=[field for field in FIELDS[category] if field not in {f.field for f in findings}]
        status='pending' if pending else 'partial' if error_code and findings else 'failed' if error_code else 'completed'
        warnings=[]
        if rejected:warnings.append('Unsupported claims were excluded; only independently validated citations are shown.')
        if not findings and not error_code:warnings.append(NOT_FOUND_WARNING)
        if any(f.confidence in ('low','insufficient_evidence') for f in findings):warnings.append('Some findings have limited confidence; inspect their sources before relying on them.')
        if any(f.scope!='exact' for f in findings):warnings.append('Some reports concern related roles, locations or employment types.')
        if any(f.conflict_group for f in findings):warnings.append('Conflicting reports are preserved separately; figures are not averaged.')
        history=topic_map((await self.job(state)).get('history'))
        result=CategoryResult(status=status,outcome=outcome,source_ids=[s.source_id for s in retained],findings=findings,missing_fields=missing,warnings=warnings,error_code=error_code,
            researched_at=stamp,expires_at=stamp+timedelta(hours=self.settings.incomplete_hours if missing or error_code else self.settings.freshness_hours),
            searches=min(50,sum(len(history.get(t,[])) for t in own)),model_calls=min(20,old.model_calls+model_calls),latency_ms=int((time.monotonic()-started)*1000))
        await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{category}':result.model_dump(mode='json')})
        logger.info('category=%s status=%s searches=%s model_calls=%s latency_ms=%s',category,status,result.searches,result.model_calls,result.latency_ms)
        return {'results':{category:result.model_dump(mode='json')}}

    async def quality(self,state):
        # Revalidate persisted branch values.
        job=await self.job(state);categories={k:CategoryResult.model_validate(v) for k,v in job['categories'].items()}
        for key,result in categories.items():
            others,other_sources=self.shared(job,key)
            if others:
                # Findings another category read for this one's topics join its own, under the same per-topic limits.
                saved=pool([*job.get('retained_sources',{}).get(key,[]),*[s.model_dump(mode='json') for s in other_sources]])
                kept,retained=retain_useful(key,dedupe_findings(key,[*result.findings,*others]),saved,result.source_ids)
                job.setdefault('retained_sources',{})[key]=[s.model_dump(mode='json') for s in retained]
                await thread(self.store.update,job['_id'],job['worker_token'],**{f'retained_sources.{key}':job['retained_sources'][key]})
                result.findings=kept;result.source_ids=[s.source_id for s in retained]
                if kept and result.outcome in ('information_not_found','no_relevant_sources'):
                    result.outcome='findings_found'
                    result.warnings=[w for w in result.warnings if w!=NOT_FOUND_WARNING]
                if kept and result.status=='failed':result.status='partial'
            # Check each category against its own saved sources only.
            sources=category_sources(job,key)
            valid=[f for f in result.findings if all(s in sources and whitespace(q) in whitespace(sources[s].evidence or '') for s,q in zip(f.source_ids,f.quotes))]
            if len(valid)!=len(result.findings):
                result.warnings=(result.warnings+['Some claims exceeded the bounded evidence budget.'])[:10]
                result.error_code='invalid_output';result.outcome='validation_failed'
                result.status='partial' if valid else 'failed'
            result.findings=dedupe_findings(key,valid)
            result.missing_fields=[f for f in FIELDS[key] if f not in {v.field for v in result.findings}]
            await thread(self.store.update,job['_id'],job['worker_token'],**{f'categories.{key}':result.model_dump(mode='json')})
        return {'results':{k:v.model_dump(mode='json') for k,v in categories.items()}}

    async def summarize(self,state):
        job=await self.job(state);categories={k:CategoryResult.model_validate(v) for k,v in state['results'].items()};facts=summary_input(categories)
        if not facts or any(v.status=='pending' for v in categories.values()):return {'summary':{}}
        await thread(self.store.rows.update_one,{'_id':job['_id'],'worker_token':job['worker_token']},{'$addToSet':{'activities':'preparing_summary'}})
        # Display the structuring model's wording verbatim; overview references are selected locally.
        ids=list(dict.fromkeys(f['id'] for f in facts))
        considerations=[f['id'] for f in facts if f['scope']!='exact' or f['confidence'] in ('low','insufficient_evidence') or f['conflict_group']]
        summary=Summary(overview_refs=ids[:3],key_takeaway_refs=ids[3:9],consideration_refs=considerations[:6])
        await thread(self.store.update,job['_id'],job['worker_token'],summary_error=False)
        return {'summary':summary.model_dump()}

    async def rate_skills(self,state):
        """Rate the level the role needs in each goal skill from the validated findings.

        The model decides each level, guided by elo's weighted reference score for the skill.
        Any model failure leaves the weighted reference targets in place.
        """
        job=await self.job(state);skills=job.get('skills') or []
        categories={k:CategoryResult.model_validate(v) for k,v in job['categories'].items()}
        # Rebuilding a cached report's summary keeps its saved ratings.
        if not skills or not job.get('requested') or any(v.status=='pending' for v in categories.values()):return {}
        findings=[{k:f[k] for k in ('id','category','field','value','confidence','scope')} for f in summary_input(categories)]
        public=job['public'];ids={f['id'] for f in findings}
        data={'opportunity':{k:public.get(k) for k in ('company','role','field','location','seniority_level','employment_type')},
              'skills':weighted_skills(skills,public,categories),'findings':findings}
        try:
            output=await self.generate(job,'opportunity_skill_levels',data,lambda value:validated_skill_levels(value,skills,ids))
            levels=validated_skill_levels(output,skills,ids)
        except Exception as error:
            # Enrichment failures are logged and skipped; cancellation still propagates.
            logger.warning('node=opportunity_skill_levels skipped error_code=%s',getattr(error,'code',type(error).__name__))
            levels=[]
        await thread(self.store.update,job['_id'],job['worker_token'],skill_levels=levels)
        return {}

    async def persist(self,state):
        job=await self.job(state);identifier=job['_id'];token=job['worker_token'];cache=job['cache'];context=ResearchContext.model_validate(job['context'])
        categories={k:CategoryResult.model_validate(v) for k,v in job['categories'].items()}
        pending=any(v.status=='pending' for v in categories.values());applicable=[v for v in categories.values() if v.status!='not_applicable'];failed=bool(applicable) and all(v.status=='failed' for v in applicable)
        complete=all(v.status in ('completed','not_applicable') for v in categories.values())
        status='failed' if failed else 'completed' if complete else 'partial'
        stamp=now();sources=pool([s for values in job.get('retained_sources',job.get('evidence',{})).values() for s in values])
        primary=getattr(self.ai,'primary',self.ai);coordinator=getattr(self.ai,'context',None)
        models={k:v for k,v in {'reasoning':getattr(getattr(primary,'settings',None),'model',None),'coordination':getattr(getattr(coordinator,'settings',None),'model',None)}.items() if v}
        report=OpportunityReport(models=models,fingerprint=context.details_fingerprint,opportunity_id=context.details_fingerprint if context.company else None,
            employment_type=job['public']['employment_type'],job_url=job['public']['job_url'],categories=categories,summary=Summary.model_validate(state.get('summary',{})),status=status,
            skill_levels=valid_levels(job.get('skill_levels'),categories),
            researched_at=stamp,expires_at=min(v.expires_at or stamp for v in categories.values()),warnings=['Summary uses only validated cited extracts.']+(['Overall summary unavailable; validated category findings remain available.'] if job.get('summary_error') else []))
        record=InterviewResearch(_id=str(ObjectId()),version=cache['version'],skill_mapping_version=MAPPING_VERSION,created_at=stamp,updated_at=stamp,
            **context.model_dump(),intelligence=report,sources=sources,
            research_status='failed' if failed else 'succeeded' if any(v.findings for v in categories.values()) else 'no_findings',last_researched_at=stamp,
            generation=Generation(provider=getattr(getattr(primary,'settings',None),'provider','unreported'),model=models.get('reasoning','unreported'),prompt_version='opportunity-structured-findings-v5',generated_at=stamp))
        record=await thread(self.store.research.finish,context,cache['token'],record)
        if not pending:await thread(self.store.rows.update_one,{'_id':identifier,'worker_token':token},{'$addToSet':{'activities':'research_failed' if failed else 'research_partial' if status=='partial' else 'research_complete'}})
        failure=next((v.error_code for v in categories.values() if v.error_code),None)
        await thread(self.store.update,identifier,token,research_id=record.id,status='pending' if pending else status,finished=not pending,summary=report.summary.model_dump(),error_code=failure,
            limit_scope=job.get('limit_scope') if pending else None,provider=job.get('provider') if pending else None)
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
                if self.available and getattr(self.ai.settings,'provider',None)=='compatible':
                    await thread(resume_obsolete_model_waits,self.store.rows,'opportunity_job')
                if self.available:
                    for row in await thread(self.store.due):self.launch(row['_id'])
            except Exception:logger.warning('Opportunity recovery temporarily unavailable.')
            await asyncio.sleep(3)

    async def start(self,owner,goal,selection,session,run,key,command,seed=None):
        if not self.available:raise GoalError('Opportunity Intelligence is unavailable on this server. Reload to see its availability details.',503)
        job=await thread(self.store.start,owner,goal,selection,session,run,key,command,seed)
        if job['finished']:await self.attach(job)
        else:self.launch(job['_id'])
        return job

    async def execute(self,identifier):
        token=uuid4().hex;job=await thread(self.store.claim,identifier,token)
        if not job:return
        context=ResearchContext.model_validate(job['context']);cache=None
        try:
            cached=await thread(self.store.cached,context)
            if cached and cached.intelligence.status=='completed' and not any(w.startswith('Overall summary unavailable;') for w in cached.intelligence.warnings) and cached.intelligence.researched_at>=job['created_at'] and all(v.status in ('completed','not_applicable') and not v.error_code and v.expires_at and v.expires_at>now() for v in cached.intelligence.categories.values()):
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
            retry_transient=(isinstance(error,TimeoutError) or isinstance(error,AIError) and error.code in ('timeout','unavailable')) and job.get('automatic_retries',0)<1
            pending=quota or retry_transient
            latest=await thread(self.store.rows.find_one,{'_id':identifier});updates={}
            for category,value in latest.get('categories',{}).items():
                if value['status'] in ('pending','running'):
                    updates[f'categories.{category}.status']='pending' if pending else 'partial' if value.get('findings') else 'failed'
                    updates[f'categories.{category}.error_code']=code
            partial=any(v['status']=='completed' or v.get('findings') for v in latest.get('categories',{}).values())
            await thread(self.store.update,identifier,token,status='pending' if pending else 'partial' if partial else 'failed',finished=not pending,error_code=code,
                automatic_retries=job.get('automatic_retries',0)+(1 if retry_transient else 0),
                next_attempt_at=now()+timedelta(seconds=max(1,min(3600,error.retry_after or 61)) if quota else 1),**updates)
            phase='waiting_quota' if quota else 'research_pending' if retry_transient else 'research_failed'
            try:
                await thread(self.app.state.workspace_store.phase,job['owner'],job['session'],job['run'],phase,
                    error='Research is waiting for the AI allowance and will resume automatically.' if quota else 'Research is retrying automatically.' if retry_transient else 'Research could not finish. Your goal and available findings remain saved.',
                    error_code=code,retry_after=max(1,min(3600,error.retry_after or 61)) if quota else None)
            except GoalError:pass
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
            await thread(self.store.research.attach,job['owner'],job['goal_id'],job['selection'],job['_id'],job['digest'],record,goal_version=job.get('goal_version',w.get('revision')))
            categories=record.intelligence.categories.values()
            pending=not job['finished'] or any(v.status in ('pending','running') for v in categories)
            failed=any(v.status in ('failed','partial') or v.error_code for v in categories)
            code=next((v.error_code for v in categories if v.error_code),None) or job.get('error_code')
            cooling=pending and code in ('rate_limited','source_rate_limited') and job['next_attempt_at']>now()
            phase=('waiting_quota' if cooling else 'researching') if pending else 'research_failed' if failed else 'ready'
            waiting=phase=='waiting_quota'
            retry=max(1,int((job['next_attempt_at']-now()).total_seconds())) if waiting else None
            message=('The previous AI service wait will resume automatically.' if job.get('limit_scope')=='user' else 'The model provider requested a cooldown. Research will resume automatically.') if waiting and code=='rate_limited' else 'The search provider is rate limited; research will resume automatically.' if waiting and code=='source_rate_limited' else 'Interview research is still pending.' if waiting else 'Some research categories could not finish. Available findings remain readable.'
            await thread(self.app.state.workspace_store.phase,job['owner'],job['session'],job['run'],phase,research_id=record.id,
                error=None if phase in ('ready','researching') else message,error_code=None if phase in ('ready','researching') else code or 'research_unavailable',retry_after=retry,limit_scope=job.get('limit_scope'),provider=job.get('provider'))
        except GoalError:pass

    async def close(self):
        self.stopping=True;self.sweeper.cancel()
        for task in list(self.tasks.values()):task.cancel()
        await asyncio.gather(self.sweeper,*list(self.tasks.values()),return_exceptions=True)

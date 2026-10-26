"""Resumable goal-setting and market research using existing Career stores/providers."""
import asyncio
import json
import logging
import math
from datetime import timedelta
from uuid import uuid4
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.mongodb import MongoDBSaver
from langsmith import tracing_context
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.discovery_config import DiscoverySettings
from app.ai.contracts import AIInput,Message
from app.ai.recovery import validation_feedback
from app.ai.waiting import quota_progress
from app.clients.search_sources import SourceRateLimit
from app.domain.review import ALIASES
from app.repositories.goals import GoalError,now,fingerprint,stable_id
from app.schemas.analysis import ResearchContext,ResearchSource,DiscoveryEvidence,Generation
from app.schemas.discovery import Scope,Decision,Plan,Listings,MarketSummary
from app.schemas.jd import JDExtraction,ReviewSkill
from app.workflows.opportunity.sources import pool

log=logging.getLogger('uvicorn.error.discovery')


def normal(value):return ' '.join((value or '').casefold().split())


def validated_listings(output,sources,scope):
    """Reject invented quotes, metadata and seniority; retain only actual listings."""
    result=[];seen=set()
    for listing in output.listings:
        if listing.ref>=len(sources) or listing.ref in seen:raise AIError('invalid_output',reason='source_reference')
        seen.add(listing.ref);source=sources[listing.ref];text=source.evidence or '';metadata=text+' '+(source.title or '')
        if not listing.relevant:continue
        if listing.job_title not in metadata or (listing.company and listing.company not in metadata):
            raise AIError('invalid_output',reason='listing_provenance')
        if scope.career_stage!='unspecified' and listing.career_stage!=scope.career_stage:continue
        if scope.career_stage in ('internship','entry_level') and any(word in normal(listing.job_title).split() for word in ('senior','lead','principal','director')):continue
        if scope.location and (not listing.location or normal(scope.location) not in normal(listing.location)):continue
        if listing.location and normal(listing.location) not in normal(metadata):continue
        for item in listing.requirements:
            if item.quote not in text or item.name not in item.quote:raise AIError('invalid_output',reason='quote_provenance')
        if listing.requirements:result.append({**listing.model_dump(mode='json'),'source_id':source.source_id,'source_url':source.url,'published_at':source.published_date.isoformat() if source.published_date else None})
    return result


def aggregate(scope,listings,settings=None):
    settings=settings or DiscoverySettings()
    """Count each canonical skill once per distinct employer/title/location listing."""
    distinct={}
    for listing in listings:
        identity=(normal(listing['company']),normal(listing['job_title']),normal(listing['location'])) if listing['company'] else (listing['source_url'],)
        if identity not in distinct:distinct[identity]=listing
    listings=list(distinct.values());groups={};responsibilities={};qualifications={}
    for index,listing in enumerate(listings):
        for item in listing['requirements']:
            name=item['name'];category=item['category']
            if item['kind']=='skill':
                canonical=ALIASES.get((category.casefold(),name.casefold()))
                # Alias lookup spans taxonomy categories only when unambiguous.
                matches={v for (c,n),v in ALIASES.items() if n==name.casefold()}
                canonical=canonical or (next(iter(matches)) if len(matches)==1 else None)
                key=canonical or (normal(name),category)
                entry=groups.setdefault(key,{'name':name,'category':category,'skill_id':canonical,'listings':set(),'required':set(),'source_ids':set(),'source_urls':set(),'terms':set(),'quote':item['quote']})
                entry['listings'].add(index)
                if not item['preferred']:entry['required'].add(index)
                entry['source_ids'].add(listing['source_id']);entry['source_urls'].add(listing['source_url']);entry['terms'].add(name)
            else:
                target=responsibilities if item['kind']=='responsibility' else qualifications
                entry=target.setdefault(normal(name),{'name':name,'quote':item['quote'],'source_ids':set(),'source_urls':set()})
                entry['source_ids'].add(listing['source_id']);entry['source_urls'].add(listing['source_url'])
    count=len(listings);skills=[];stats=[]
    for entry in sorted(groups.values(),key=lambda v:(-len(v['required']),-len(v['listings']),v['name']))[:60]:
        kind='core' if len(entry['required'])>=max(2,math.ceil(count*.5)) else 'specialisation' if entry['required'] else 'optional'
        stats.append({'name':entry['name'],'skill_id':entry['skill_id'],'requirement_type':kind,'mention_count':len(entry['listings']),'sample_size':count,'source_ids':sorted(entry['source_ids']),'original_terms':sorted(entry['terms'])})
        skills.append(ReviewSkill(name=entry['name'],category=entry['category'],skill_id=entry['skill_id'],priority='preferred' if kind=='optional' else 'required',
            origin='market_research',priority_origin='market_research',evidence=entry['quote'],source_urls=sorted(entry['source_urls'])[:10],
            context=f"{kind.title()} · mentioned in {len(entry['listings'])} of {count} sampled listings; not a market-wide estimate."))
    def serial(items):return [{**v,'source_ids':sorted(v['source_ids']),'source_urls':sorted(v['source_urls'])[:10]} for v in items.values()]
    responsibilities=serial(responsibilities)[:20];qualifications=serial(qualifications)[:30]
    content=JDExtraction(role=scope.area,field=scope.field,company=None,job_url=None,location=scope.location,
        seniority_level=None if scope.career_stage=='unspecified' else scope.career_stage,
        employment_type='internship' if scope.career_stage=='internship' else 'unknown',
        summary=f"Career target for {scope.area}, based on requirements found in {count} distinct public job listings. Requirements describe this sample only.",
        skills=skills,responsibilities=[v['name'] for v in responsibilities],non_skill_requirements=[{
            'requirement_id':str(uuid4()),'category':'qualification','description':v['name'],'priority':'unspecified',
            'evidence':v['quote'],'origin':'market_research','source_urls':v['source_urls']} for v in qualifications])
    employers={normal(v['company']) for v in listings if v['company']}
    warnings=[]
    if count<settings.target_listings or len(employers)<settings.target_employers:warnings.append(f'Limited coverage: the sample did not reach {settings.target_listings} distinct listings and {settings.target_employers} identified employers. Missing requirements remain unknown.')
    if not skills:warnings.append('Insufficient evidence to establish job skills. Refine the scope or refresh research.')
    if qualifications:warnings.append('Qualifications vary across listings; review the individual sources rather than treating every qualification as mandatory.')
    return {'content':content.model_dump(mode='json'),'stats':stats,'responsibilities':responsibilities,'qualifications':qualifications,
        'listings':listings,'employers':len(employers),'coverage':'insufficient' if not skills else 'good' if count>=settings.target_listings and len(employers)>=settings.target_employers else 'limited','warnings':warnings}


class DiscoveryEngine:
    def __init__(self,app,db,ai,source):
        self.app,self.ai,self.source=app,ai,source
        self.settings=DiscoverySettings.from_env()
        self.rows=app.state.goal_store.db.research_contexts
        self.tasks={};self.stopping=False
        graph=StateGraph(dict)
        for name,node in [('plan_research',self.plan),('search_job_listings',self.search),('extract_requirements',self.extract),('aggregate_requirements',self.combine),('generate_career_target',self.target)]:graph.add_node(name,node)
        graph.add_edge(START,'plan_research');graph.add_edge('plan_research','search_job_listings');graph.add_edge('search_job_listings','extract_requirements');graph.add_edge('extract_requirements','aggregate_requirements');graph.add_edge('aggregate_requirements','generate_career_target');graph.add_edge('generate_career_target',END)
        saver=MongoDBSaver(db.client,db_name=db.name,checkpoint_collection_name='career_checkpoints',writes_collection_name='career_checkpoint_writes',ttl=86400)
        self.saver=saver
        self.graph=graph.compile(checkpointer=saver)
        self.sweeper=asyncio.create_task(self.recover())

    def get(self,identifier,owner=None):
        query={'_id':identifier,'kind':'career_discovery'}
        if owner:query['owner']=owner
        row=self.rows.find_one(query)
        if not row:raise GoalError('Career discovery was not found.',404)
        return row

    def current(self,owner):return self.rows.find_one({'owner':owner,'kind':'career_discovery'},sort=[('created_at',-1)])

    def start(self,owner,key):
        current=self.current(owner)
        if current and current['status']!='confirmed':return current
        identifier=stable_id(owner,key,'career-discovery');stamp=now()
        row={'_id':identifier,'kind':'career_discovery','owner':owner,'version':1,'status':'conversation','decision':None,'created_at':stamp,'updated_at':stamp,'receipts':[]}
        self.rows.update_one({'_id':identifier},{'$setOnInsert':row},upsert=True)
        return self.get(identifier,owner)

    def update(self,row,**values):
        query={'_id':row['_id'],'run':row['run'],'lease':row['lease']}
        if not self.rows.update_one(query,{'$set':{**values,'updated_at':now()}}).matched_count:raise GoalError('This research scope changed; open the current discovery.')

    async def model(self,row,stage,data,validate=None):
        step=stage+'_'+fingerprint(data)[:20];attempts=(row.get('attempts') or {}).get(step,0)
        for attempt in range(attempts,2):
            token=quota_progress.set(None)
            feedback=validation_feedback.set({'reason':'schema_or_provenance','fields':[]} if attempt else None)
            try:
                result=await self.ai.generate(AIInput(stage=stage,context=json.dumps(data,separators=(',',':'))),Operation(row['owner'],row['run'],stage),current_revision=lambda:row['run'],validate_output=validate)
                if validate:validate(result.data)
                return result
            except AIError as error:
                if error.code not in ('invalid_output','incomplete_output'):raise
                await thread(self.update,row,**{'attempts.'+step:attempt+1})
                if attempt==1:raise
            finally:quota_progress.reset(token);validation_feedback.reset(feedback)
        raise AIError('invalid_output',reason='repair_exhausted')

    async def converse(self,identifier,owner,key,body):
        row=await thread(self.get,identifier,owner);digest=fingerprint(body.model_dump(mode='json'))
        receipt=next((v for v in row['receipts'] if v['key']==key),None)
        if receipt:
            if receipt['hash']!=digest:raise GoalError('This message key was used for another message.')
            return row
        if row['version']!=body.expected_version or row['status'] in ('researching','waiting','confirmed'):raise GoalError('Reload the latest discovery before changing its scope.')
        # Only approved structured direction survives; raw human messages are transient.
        async def understand(state):
            result=await self.ai.generate(AIInput(stage='discovery_turn',context=json.dumps({'previous':row['decision']}),conversation=[Message(role='user',content=body.message)]),Operation(owner,str(row['version']),'discovery_turn'),current_revision=lambda:str(row['version']))
            return {'decision':Decision.model_validate(result.data.model_dump()).model_dump(mode='json')}
        def confirm_area(state):
            decision=state['decision']
            if decision['action']=='START_RESEARCH':decision['action']='CONFIRM_AREA'
            return {'decision':decision}
        graph=StateGraph(dict);graph.add_node('understand_intent',understand);graph.add_node('confirm_career_area',confirm_area)
        graph.add_edge(START,'understand_intent');graph.add_conditional_edges('understand_intent',lambda s:'confirm_career_area' if s['decision']['scope'] else END);graph.add_edge('confirm_career_area',END)
        compiled=graph.compile(checkpointer=self.saver)
        config={'configurable':{'thread_id':'discovery-conversation:'+identifier+':'+key}}
        with tracing_context(enabled=False):
            snapshot=await compiled.aget_state(config)
            value=await compiled.ainvoke(None if snapshot.next else {},config) if not snapshot.values or snapshot.next else snapshot.values
        changed=await thread(self.rows.update_one,{'_id':identifier,'owner':owner,'version':body.expected_version,'status':row['status']},{'$set':{'decision':value['decision'],'status':'conversation','updated_at':now()},'$inc':{'version':1},'$push':{'receipts':{'$each':[{'key':key,'hash':digest}],'$slice':-100}}})
        if not changed.matched_count:raise GoalError('A newer discovery message arrived; reload it.')
        return await thread(self.get,identifier,owner)

    def begin(self,identifier,owner,key,body):
        row=self.get(identifier,owner);digest=fingerprint(body.model_dump(mode='json'))
        receipt=next((v for v in row['receipts'] if v['key']==key),None)
        if receipt:
            if receipt['hash']!=digest:raise GoalError('This research key was used with another scope.')
            return row
        if row['version']!=body.expected_version or row['status'] in ('researching','waiting'):raise GoalError('This discovery changed or research is already running.')
        decision=Decision.model_validate(row['decision']) if row['decision'] else None
        if not decision or decision.scope!=body.scope:raise GoalError('Review the proposed scope before researching.',422)
        scope=body.scope.model_dump(mode='json');scope_key=fingerprint({k:normal(v) if isinstance(v,str) else v for k,v in scope.items()})
        # Owner-scoped fresh reuse avoids exposing another person's session/evidence.
        cached=None if body.refresh else self.rows.find_one({'kind':'career_discovery','owner':owner,'scope_key':scope_key,'aggregate':{'$exists':True},'researched_at':{'$gt':now()-timedelta(hours=self.settings.freshness_hours)}},sort=[('researched_at',-1)])
        if not body.refresh and row.get('scope_key')==scope_key and row['status']=='failed':cached=row
        values={'run':uuid4().hex,'scope':scope,'scope_key':scope_key,'status':'researching','stage':'plan_research','next_attempt_at':now(),'lease_until':now(),'error_code':None,'limit_scope':None,'provider':None,'updated_at':now()}
        for field in ('plan','sources','searched','listings','evaluated','aggregate','summary','generation','review_id','researched_at','attempts','search_failures'):
            values[field]=cached.get(field) if cached else {} if field=='attempts' else None
        if row['status']=='failed':values['attempts']={}
        changed=self.rows.update_one({'_id':identifier,'owner':owner,'version':body.expected_version,'status':row['status']},{'$set':values,'$inc':{'version':1},'$push':{'receipts':{'$each':[{'key':key,'hash':digest}],'$slice':-100}}})
        if not changed.matched_count:raise GoalError('A newer research scope arrived; reload it.')
        return self.get(identifier,owner)

    async def plan(self,state):
        row=await thread(self.get,state['id'])
        if row.get('plan'):return state
        result=await self.model(row,'discovery_plan',{'scope':row['scope'],'year':now().year})
        plan=Plan.model_validate(result.data.model_dump())
        scope=Scope.model_validate(row['scope'])
        prefix=' '.join(v for v in (scope.area,scope.location,scope.career_stage.replace('_',' ') if scope.career_stage!='unspecified' else None,str(now().year)) if v)
        queries=list(dict.fromkeys((prefix+' '+v+' job requirements')[:180] for v in plan.queries))
        await thread(self.update,row,plan={'related_roles':plan.related_roles,'queries':queries},stage='search_job_listings')
        return state

    async def search(self,state):
        row=await thread(self.get,state['id'])
        if row.get('aggregate'):return state
        scope=Scope.model_validate(row['scope']);context=ResearchContext(field=scope.field,role=scope.area,location=scope.location,seniority_level=scope.career_stage)
        searched=row.get('searched') or [];sources=[ResearchSource.model_validate(s) for s in row.get('sources') or []];failures=row.get('search_failures') or []
        queries=row['plan']['queries']
        # At most two focused follow-ups; never invent coverage to reach the target.
        if len(sources)<self.settings.target_listings:
            for term in ('employer careers responsibilities qualifications','graduate internship' if scope.career_stage in ('entry_level','internship') else 'hiring required skills')[:self.settings.max_followups]:
                q=' '.join(v for v in (scope.area,scope.location,scope.career_stage.replace('_',' '),str(now().year),term) if v)[:180]
                if q not in queries:queries=queries+[q]
        async def fetch(query):
            for attempt in range(2):
                try:
                    async with asyncio.timeout(30):return await self.source.collect_opportunity_query(context,query)
                except SourceRateLimit:raise
                except (TimeoutError,GoalError):
                    if attempt:raise
                    await asyncio.sleep(.5)
        remaining=[q for q in queries[:6] if q not in searched]
        for offset in range(0,len(remaining),2):
            if len(sources)>=self.settings.target_listings and offset>=len(row['plan']['queries']):break
            batch=remaining[offset:offset+2]
            results=await asyncio.gather(*(fetch(q) for q in batch),return_exceptions=True)
            rate=None
            for q,result in zip(batch,results):
                if isinstance(result,SourceRateLimit):rate=result;continue
                searched.append(q)
                if isinstance(result,BaseException):failures.append('source_unavailable');continue
                sources=pool([s.model_dump(mode='json') for s in [*sources,*result]])[:self.settings.max_listings]
            await thread(self.update,row,sources=[s.model_dump(mode='json') for s in sources],searched=searched,search_failures=failures,stage='extract_requirements')
            if rate:raise rate
        return state

    async def extract(self,state):
        row=await thread(self.get,state['id'])
        if row.get('aggregate'):return state
        scope=Scope.model_validate(row['scope']);sources=[ResearchSource.model_validate(v) for v in row.get('sources') or []]
        evaluated=row.get('evaluated') or [];listings=row.get('listings') or []
        for offset in range(0,len(sources),3):
            batch=[s for s in sources[offset:offset+3] if s.source_id not in evaluated]
            if not batch:continue
            def validate(output):validated_listings(Listings.model_validate(output.model_dump()),batch,scope)
            result=await self.model(row,'discovery_extract',{'scope':scope.model_dump(),'sources':[{'ref':i,'title':s.title,'excerpt':s.evidence} for i,s in enumerate(batch)]},validate)
            listings.extend(validated_listings(result.data,batch,scope));evaluated.extend(s.source_id for s in batch)
            await thread(self.update,row,listings=listings,evaluated=evaluated,generation=result.generation.model_dump(mode='json'))
        return state

    async def combine(self,state):
        row=await thread(self.get,state['id'])
        if row.get('aggregate'):return state
        result=aggregate(Scope.model_validate(row['scope']),row.get('listings') or [],self.settings)
        if row.get('search_failures'):result['warnings'].append('Some searches failed; the target includes only successfully retrieved evidence.')
        await thread(self.update,row,aggregate=result,stage='generate_career_target')
        return state

    async def target(self,state):
        row=await thread(self.get,state['id']);result=row['aggregate'];scope=Scope.model_validate(row['scope'])
        if not row.get('summary'):
            response=await self.model(row,'discovery_summary',{'scope':row['scope'],'responsibilities':result['responsibilities']})
            summary=MarketSummary.model_validate(response.data.model_dump())
            if any(i<0 or i>=len(result['responsibilities']) for i in summary.responsibility_refs):raise AIError('invalid_output',reason='summary_reference')
            await thread(self.update,row,summary=summary.model_dump(),generation=row.get('generation') or response.generation.model_dump(mode='json'))
            row=await thread(self.get,state['id'])
        content=JDExtraction.model_validate(result['content'])
        content.responsibilities=[result['responsibilities'][i]['name'] for i in dict.fromkeys(row['summary']['responsibility_refs'])]
        evidence=DiscoveryEvidence(research_id=row['_id']+':'+row['run'],selected_area=scope.area,related_roles=row['plan']['related_roles'],specificity=scope.specificity,
            listings_analysed=len(result['listings']),employers_analysed=result['employers'],coverage=result['coverage'],source_ids=list(dict.fromkeys(v['source_id'] for v in result['listings'])),researched_at=row.get('researched_at') or now())
        review=await thread(self.app.state.review_store.create_discovery,row['owner'],row['run'],content,Generation.model_validate(row['generation']),evidence)
        # Immutable public evidence snapshot remains resolvable after scope changes.
        await thread(self.rows.update_one,{'_id':evidence.research_id},{'$setOnInsert':{'kind':'career_discovery_evidence','owner':row['owner'],'review_id':review.id,'scope':row['scope'],'sources':row.get('sources') or [],'aggregate':result,'created_at':now()}},upsert=True)
        await thread(self.update,row,review_id=review.id,status='review',stage='review_career_target',researched_at=evidence.researched_at,error_code=None,lease_until=now())
        return state

    def launch(self,identifier):
        if identifier in self.tasks or self.stopping:return
        task=asyncio.create_task(self.run(identifier));self.tasks[identifier]=task
        task.add_done_callback(lambda _:self.tasks.pop(identifier,None))

    async def run(self,identifier):
        row=await thread(self.rows.find_one_and_update,{'_id':identifier,'kind':'career_discovery','status':{'$in':['researching','waiting']},'next_attempt_at':{'$lte':now()},'lease_until':{'$lte':now()}},{'$set':{'lease':uuid4().hex,'lease_until':now()+timedelta(seconds=330),'status':'researching'}},return_document=ReturnDocument.AFTER)
        if not row:return
        try:
            async with asyncio.timeout(300):
                with tracing_context(enabled=False):await self.graph.ainvoke({'id':identifier},config={'configurable':{'thread_id':'discovery:'+identifier+':'+row['run']}})
        except asyncio.CancelledError:
            await thread(self.update,row,lease_until=now());raise
        except (AIError,SourceRateLimit,GoalError,TimeoutError,ValueError) as error:
            wait=isinstance(error,SourceRateLimit) or isinstance(error,AIError) and error.code=='rate_limited'
            code=error.code if isinstance(error,AIError) else 'source_rate_limited' if isinstance(error,SourceRateLimit) else 'research_timeout' if isinstance(error,TimeoutError) else 'research_validation_failed'
            delay=max(1,getattr(error,'retry_after',None) or 60)
            log.warning('error_code=%s limit_scope=%s',code,getattr(error,'limit_scope',None))
            try:await thread(self.update,row,status='waiting' if wait else 'failed',error_code=code,limit_scope=getattr(error,'limit_scope',None),provider='brave' if isinstance(error,SourceRateLimit) else getattr(error,'provider',None),next_attempt_at=now()+timedelta(seconds=delay),lease_until=now())
            except GoalError:pass
        except Exception as error:
            log.error('discovery_worker_failed exception_type=%s',type(error).__name__)
            try:await thread(self.update,row,status='failed',error_code='research_unavailable',lease_until=now())
            except GoalError:pass

    async def recover(self):
        while not self.stopping:
            try:
                rows=await thread(lambda:list(self.rows.find({'kind':'career_discovery','status':{'$in':['researching','waiting']},'next_attempt_at':{'$lte':now()},'lease_until':{'$lte':now()}},{'_id':1}).limit(10)))
                for row in rows:self.launch(row['_id'])
            except Exception:log.warning('discovery_recovery_unavailable')
            await asyncio.sleep(2)

    async def close(self):
        self.stopping=True;self.sweeper.cancel()
        tasks=[self.sweeper,*self.tasks.values()]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

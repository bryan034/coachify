"""Resumable goal-setting and market research using existing Career stores/providers."""
import asyncio
import json
import logging
import math
import re
from datetime import timedelta
from uuid import uuid4
from pymongo import ReturnDocument
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.mongodb import MongoDBSaver
from langsmith import tracing_context
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.discovery_config import DiscoverySettings
from app.ai.contracts import AIInput,Message
from app.ai.recovery import validation_feedback
from app.workflows.model_waits import resume_obsolete_model_waits
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


def check_conversation_capacity(row):
    messages=row.get('messages',[])
    if len(messages)>=996 or len(json.dumps(messages,ensure_ascii=False).encode())>=3_500_000:
        raise GoalError('This conversation is full. Save your reviewed goal before starting another discovery.',422)


def research_facts(row):
    """Bounded projection for chat; never send full sources or the whole transcript."""
    result=row.get('aggregate') or {}
    facts=[]
    for item in result.get('stats',[])[:12]:
        facts.append({'text':item['name'], 'mentions':item['mention_count'],
            'sample_size':item['sample_size'],'source_ids':item['source_ids'][:3]})
    for item in result.get('responsibilities',[])[:4]:
        facts.append({'text':item['name'],'source_ids':item['source_ids'][:3]})
    return facts


def citations(ids,sources):
    allowed={s['source_id']:s['url'] for s in sources}
    return ' '.join(f'[source](<{allowed[i]}>)' for i in dict.fromkeys(ids) if i in allowed)


def plain_reply(value):
    # Only server-resolved references can create external links.
    return re.sub(r'https?://\S+', '', re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', value)).strip() or 'What would you like to explore?'


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

    def research_row(self,state):
        row=self.get(state['id'])
        if row.get('run')!=state['run'] or row.get('lease')!=state['lease']:
            raise GoalError('This research was superseded.')
        return row

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
        if row['version']!=body.expected_version or row['status']=='confirmed':raise GoalError('Reload the latest discovery before changing its scope.')
        check_conversation_capacity(row)
        facts=research_facts(row)
        allowed={source for fact in facts for source in fact['source_ids']}
        async def understand(state):
            previous=row.get('decision') or {}
            direction={k:v for k,v in previous.items() if k in ('scope','excluded_skills','requested_skills')}
            history=[Message(role=m['role'],content=m['content'][:400]) for m in row.get('messages',[])[-6:]]
            result=await self.ai.generate(AIInput(stage='discovery_turn',context=json.dumps({
                'previous':direction,'memory':previous.get('memory',{}),'scope':row.get('scope'),
                'research_status':row['status'],'research_question':row.get('research_question'),'facts':facts},separators=(',',':')),
                conversation=[*history,Message(role='user',content=body.message)]),
                Operation(owner,str(row['version']),'discovery_turn'),current_revision=lambda:str(row['version']))
            decision=Decision.model_validate(result.data.model_dump())
            if any(i not in allowed for i in decision.source_ids):raise AIError('invalid_output',reason='source_reference')
            return {'decision':decision.model_dump(mode='json'),'digest':digest}
        graph=StateGraph(dict);graph.add_node('understand_intent',understand)
        graph.add_edge(START,'understand_intent');graph.add_edge('understand_intent',END)
        compiled=graph.compile(checkpointer=self.saver)
        config={'configurable':{'thread_id':'discovery-conversation:'+identifier+':'+key}}
        with tracing_context(enabled=False):
            snapshot=await compiled.aget_state(config)
            if snapshot.values and snapshot.values.get('digest')!=digest:raise GoalError('This message key was used for another message.')
            value=await compiled.ainvoke(None if snapshot.next else {},config) if not snapshot.values or snapshot.next else snapshot.values
        decision=value['decision'];proposed=decision.get('scope')
        # A question does not silently change the current research scope.
        if decision['action']=='ANSWER':proposed=row.get('scope') or proposed;decision['scope']=proposed
        values={'decision':decision,'updated_at':now()}
        previous_memory=(row.get('decision') or {}).get('memory',{})
        preference_changed=any(decision.get('memory',{}).get(k,[])!=previous_memory.get(k,[])
            for k in ('interests','preferences','rejected_directions'))
        ready=proposed and (decision['action'] in ('START_RESEARCH','CONFIRM_AREA','REFINE_SKILLS') or preference_changed and row['status']=='review')
        changed_scope=proposed and proposed!=row.get('scope')
        if ready and (changed_scope or row['status'] in ('conversation','failed') or decision['action']=='REFINE_SKILLS' or preference_changed and row['status']=='review'):
            values.update(await thread(self.research_values,row,proposed,False))
        reply=plain_reply(decision['reply'])
        if decision.get('question'):reply+='\n\n'+plain_reply(decision['question'])
        links=citations(decision.get('source_ids',[])[:3],row.get('sources') or [])
        if links:reply+=' '+links
        if values.get('status')=='researching':reply+='\n\nResearching '+proposed['area']+'. You can keep chatting while I compare representative listings.'
        changed=await thread(self.rows.update_one,{'_id':identifier,'owner':owner,'version':body.expected_version,'status':{'$ne':'confirmed'}},
            {'$set':values,'$inc':{'version':1},'$push':{
                'messages':{'$each':[{'role':'user','content':body.message},{'role':'assistant','content':reply}]},
                'receipts':{'$each':[{'key':key,'hash':digest}],'$slice':-100}}})
        if not changed.matched_count:raise GoalError('A newer discovery message arrived; reload it.')
        return await thread(self.get,identifier,owner)

    def research_values(self,row,scope,refresh):
        scope_key=fingerprint({k:normal(v) if isinstance(v,str) else v for k,v in scope.items()})
        cached=None if refresh else self.rows.find_one({'kind':'career_discovery','owner':row['owner'],'scope_key':scope_key,
            'aggregate':{'$ne':None},'researched_at':{'$gt':now()-timedelta(hours=self.settings.freshness_hours)}},sort=[('researched_at',-1)])
        if not refresh and row.get('scope_key')==scope_key and row['status'] in ('failed','researching','waiting'):cached=row
        values={'run':uuid4().hex,'scope':scope,'scope_key':scope_key,'status':'researching','stage':'plan_research',
            'next_attempt_at':now(),'lease':None,'lease_until':now(),'error_code':None,'limit_scope':None,'provider':None,'updated_at':now()}
        for field in ('plan','sources','searched','listings','evaluated','aggregate','generation','researched_at','search_failures'):
            values[field]=cached.get(field) if cached else None
        values.update(summary=None,summary_version=None,review_id=None,attempts={},research_question=None)
        return values

    def begin(self,identifier,owner,key,body):
        row=self.get(identifier,owner);digest=fingerprint(body.model_dump(mode='json'))
        receipt=next((v for v in row['receipts'] if v['key']==key),None)
        if receipt:
            if receipt['hash']!=digest:raise GoalError('This research key was used with another scope.')
            return row
        if row['version']!=body.expected_version or row['status'] in ('researching','waiting','confirmed'):raise GoalError('This discovery changed or research is already running.')
        check_conversation_capacity(row)
        decision=Decision.model_validate(row['decision']) if row['decision'] else None
        if not decision or decision.scope!=body.scope:raise GoalError('Research must match the current direction.',422)
        values=self.research_values(row,body.scope.model_dump(mode='json'),body.refresh)
        changed=self.rows.update_one({'_id':identifier,'owner':owner,'version':body.expected_version,'status':row['status']},
            {'$set':values,'$inc':{'version':1},'$push':{'receipts':{'$each':[{'key':key,'hash':digest}],'$slice':-100}}})
        if not changed.matched_count:raise GoalError('A newer research scope arrived; reload it.')
        return self.get(identifier,owner)

    async def plan(self,state):
        row=await thread(self.research_row,state)
        if row.get('plan'):return state
        result=await self.model(row,'discovery_plan',{'scope':row['scope'],'year':now().year})
        plan=Plan.model_validate(result.data.model_dump())
        scope=Scope.model_validate(row['scope'])
        prefix=' '.join(v for v in (scope.area,scope.location,scope.career_stage.replace('_',' ') if scope.career_stage!='unspecified' else None,str(now().year)) if v)
        queries=list(dict.fromkeys((prefix+' '+v+' job requirements')[:180] for v in plan.queries))
        await thread(self.update,row,plan={'related_roles':plan.related_roles,'queries':queries},stage='search_job_listings')
        return state

    async def search(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return state
        scope=Scope.model_validate(row['scope']);context=ResearchContext(field=scope.field,role=scope.area,location=scope.location,seniority_level=scope.career_stage)
        searched=row.get('searched') or [];sources=[ResearchSource.model_validate(s) for s in row.get('sources') or []];failures=row.get('search_failures') or []
        queries=row['plan']['queries']
        # At most two focused follow-ups; never invent coverage to reach the target.
        if len(sources)<self.settings.target_listings:
            for term in ('employer careers responsibilities qualifications','graduate internship' if scope.career_stage in ('entry_level','internship') else 'hiring required skills')[:self.settings.max_followups]:
                q=' '.join(v for v in (scope.area,scope.location,scope.career_stage.replace('_',' ') if scope.career_stage!='unspecified' else None,str(now().year),term) if v)[:180]
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
            await thread(self.update,row,sources=[s.model_dump(mode='json') for s in sources],searched=searched,search_failures=failures,stage='search_job_listings')
            if rate:raise rate
        return state

    async def extract(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return state
        await thread(self.update,row,stage='extract_requirements')
        scope=Scope.model_validate(row['scope']);sources=[ResearchSource.model_validate(v) for v in row.get('sources') or []]
        evaluated=row.get('evaluated') or [];listings=row.get('listings') or []
        for offset in range(0,len(sources),3):
            row=await thread(self.research_row,state)
            batch=[s for s in sources[offset:offset+3] if s.source_id not in evaluated]
            if not batch:continue
            def validate(output):
                parsed=Listings.model_validate(output.model_dump())
                validated_listings(parsed,batch,scope)
                if any(i<0 or i>=len(batch) for i in parsed.question_refs) or parsed.question and not parsed.question_refs:
                    raise AIError('invalid_output',reason='question_reference')
            result=await self.model(row,'discovery_extract',{'scope':scope.model_dump(),'memory':(row.get('decision') or {}).get('memory',{}),'previous_question':row.get('research_question'),'sources':[{'ref':i,'title':s.title,'excerpt':s.evidence} for i,s in enumerate(batch)]},validate)
            if result.data.question and not row.get('research_question'):
                question=plain_reply(result.data.question)
                links=citations([batch[i].source_id for i in result.data.question_refs],[v.model_dump(mode='json') for v in batch])
                await thread(self.update,row,research_question=question)
                await thread(self.rows.update_one,{'_id':row['_id'],'run':row['run'],'lease':row['lease']},
                    {'$push':{'messages':{'role':'assistant','content':question+' '+links}}})
                row['research_question']=question
            listings.extend(validated_listings(result.data,batch,scope));evaluated.extend(s.source_id for s in batch)
            await thread(self.update,row,listings=listings,evaluated=evaluated,generation=result.generation.model_dump(mode='json'))
        return state

    async def combine(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return state
        await thread(self.update,row,stage='aggregate_requirements')
        result=aggregate(Scope.model_validate(row['scope']),row.get('listings') or [],self.settings)
        if row.get('search_failures'):result['warnings'].append('Some searches failed; the target includes only successfully retrieved evidence.')
        await thread(self.update,row,aggregate=result,stage='generate_career_target')
        return state

    async def target(self,state):
        # A chat answer may arrive while synthesis runs. Re-synthesise against its
        # new memory; never publish recommendations for an older conversation.
        for _ in range(3):
            row=await thread(self.research_row,state);result=row['aggregate'];scope=Scope.model_validate(row['scope'])
            await thread(self.update,row,stage='generate_career_target')
            decision=row.get('decision') or {};excluded={normal(v) for v in decision.get('excluded_skills',[])}
            requested=decision.get('requested_skills',[])
            def validate(output):
                summary=MarketSummary.model_validate(output.model_dump())
                if any(i<0 or i>=len(result['responsibilities']) for i in summary.responsibility_refs):raise AIError('invalid_output',reason='summary_reference')
                names=set()
                for skill in summary.skills:
                    if normal(skill.name) in names:raise AIError('invalid_output',reason='duplicate_skill')
                    names.add(normal(skill.name))
                    if any(i<0 or i>=len(result['stats']) for i in skill.skill_refs):raise AIError('invalid_output',reason='skill_reference')
                    if not skill.skill_refs and skill.name not in requested:raise AIError('invalid_output',reason='unsupported_recommendation')
                    if normal(skill.name) in excluded or any(normal(result['stats'][i]['name']) in excluded for i in skill.skill_refs):raise AIError('invalid_output',reason='excluded_skill')
            if not row.get('summary') or row.get('summary_version')!=row['version']:
                response=await self.model(row,'discovery_summary',{'scope':row['scope'],'memory':decision.get('memory',{}),
                    'excluded_skills':decision.get('excluded_skills',[]),'requested_skills':requested,
                    'skills':[{'name':v['name'],'context':v['context']} for v in result['content']['skills']],
                    'frequencies':result['stats'],'responsibilities':result['responsibilities']},validate)
                summary=MarketSummary.model_validate(response.data.model_dump())
            else:summary=MarketSummary.model_validate(row['summary']);validate(summary)
            content=JDExtraction.model_validate(result['content'])
            content.responsibilities=[result['responsibilities'][i]['name'] for i in dict.fromkeys(summary.responsibility_refs)]
            content.skills=[]
            for recommendation in summary.skills:
                refs=recommendation.skill_refs
                urls=list(dict.fromkeys(url for i in refs for url in result['content']['skills'][i]['source_urls']))[:10]
                content.skills.append(ReviewSkill(name=recommendation.name,category=result['content']['skills'][refs[0]]['category'] if refs else 'technical',
                    priority='suggested',origin='generated_guidance' if refs else 'user_declaration',
                    priority_origin='generated_guidance' if refs else 'user_declaration',source_urls=urls,
                    context=(recommendation.learning_priority.title()+' learning priority · '+recommendation.relevance)[:600]))
            evidence=DiscoveryEvidence(research_id=row['_id']+':'+row['run']+':'+str(row['version']),selected_area=scope.area,
                related_roles=row['plan']['related_roles'],specificity=scope.specificity,listings_analysed=len(result['listings']),
                employers_analysed=result['employers'],coverage=result['coverage'],source_ids=list(dict.fromkeys(v['source_id'] for v in result['listings'])),
                researched_at=row.get('researched_at') or now())
            generation=Generation.model_validate(row.get('generation') or response.generation.model_dump(mode='json'))
            review=await thread(self.app.state.review_store.create_discovery,row['owner'],row['run']+':'+str(row['version']),content,generation,evidence)
            await thread(self.rows.update_one,{'_id':evidence.research_id},{'$setOnInsert':{
                'kind':'career_discovery_evidence','owner':row['owner'],'review_id':review.id,'scope':row['scope'],
                'sources':row.get('sources') or [],'aggregate':result,'summary':summary.model_dump(),'created_at':now()}},upsert=True)
            lines=[f"Your career direction: **{scope.area}**.",
                f"Researched {len(result['listings'])} distinct listings across {result['employers']} identified employers; {result['coverage']} coverage.",
                'Learning priorities below are Gemini recommendations informed by this sample, not universal employer requirements.']
            for i in summary.responsibility_refs[:3]:
                item=result['responsibilities'][i];lines.append('- Typical work: '+plain_reply(item['name'])+' '+citations(item['source_ids'][:1],row.get('sources') or []))
            labels={'core':'Foundation','specialisation':'Specialisation-dependent','optional':'Optional tool'}
            for skill in summary.skills[:8]:
                ids=list(dict.fromkeys(source for i in skill.skill_refs for source in result['stats'][i]['source_ids']))
                lines.append('- '+labels[skill.requirement_type]+': **'+plain_reply(skill.name)+'** · '+skill.learning_priority+' learning priority. '+plain_reply(skill.relevance)+' '+
                    (citations(ids[:1],row.get('sources') or []) if ids else '(user-requested addition; no listing evidence)'))
            for item in result['qualifications'][:2]:lines.append('- Sample condition (varies by listing): '+plain_reply(item['name'])+' '+citations(item['source_ids'][:1],row.get('sources') or []))
            if summary.specialisations:lines.append('Possible specialisations (Gemini interpretation): '+', '.join(plain_reply(v) for v in summary.specialisations)+'. '+citations(evidence.source_ids[:1],row.get('sources') or []))
            lines.extend(result['warnings'])
            if summary.question:lines.append(plain_reply(summary.question))
            lines.append('Ask a question or describe a change. Review and confirm when you are ready to save this goal.')
            # Keep each transcript entry bounded, including unusually long source URLs.
            message=''
            for line in lines:
                if len(message)+len(line)+2<=12000:message+=('\n\n' if message else '')+line
            changed=await thread(self.rows.update_one,{'_id':row['_id'],'run':row['run'],'lease':row['lease'],'version':row['version']},
                {'$set':{'summary':summary.model_dump(),'summary_version':row['version'],'review_id':review.id,'status':'review',
                    'stage':'review_career_target','researched_at':evidence.researched_at,'error_code':None,'lease_until':now(),'updated_at':now()},
                 '$push':{'messages':{'role':'assistant','content':message}}})
            if changed.matched_count:return state
        raise AIError('rate_limited',retry_after=1,provider='gemini')

    def launch(self,identifier):
        if identifier in self.tasks or self.stopping:return
        task=asyncio.create_task(self.run(identifier));self.tasks[identifier]=task
        task.add_done_callback(lambda _:self.tasks.pop(identifier,None))

    async def run(self,identifier):
        row=await thread(self.rows.find_one_and_update,{'_id':identifier,'kind':'career_discovery','status':{'$in':['researching','waiting']},'next_attempt_at':{'$lte':now()},'lease_until':{'$lte':now()}},{'$set':{'lease':uuid4().hex,'lease_until':now()+timedelta(seconds=330),'status':'researching'}},return_document=ReturnDocument.AFTER)
        if not row:return
        try:
            async with asyncio.timeout(300):
                with tracing_context(enabled=False):await self.graph.ainvoke({'id':identifier,'run':row['run'],'lease':row['lease']},config={'configurable':{'thread_id':'discovery:'+identifier+':'+row['run']}})
        except asyncio.CancelledError:
            await thread(self.update,row,lease_until=now());raise
        except GoalError:
            return
        except (AIError,SourceRateLimit,TimeoutError,ValueError) as error:
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
                if self.ai.settings.enabled and getattr(self.ai.settings,'provider',None)=='gemini':
                    await thread(resume_obsolete_model_waits,self.rows,'career_discovery')
                rows=await thread(lambda:list(self.rows.find({'kind':'career_discovery','status':{'$in':['researching','waiting']},'next_attempt_at':{'$lte':now()},'lease_until':{'$lte':now()}},{'_id':1}).limit(10)))
                for row in rows:self.launch(row['_id'])
            except Exception:log.warning('discovery_recovery_unavailable')
            await asyncio.sleep(2)

    async def close(self):
        self.stopping=True;self.sweeper.cancel()
        tasks=[self.sweeper,*self.tasks.values()]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

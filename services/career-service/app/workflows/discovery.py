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
from app.schemas.analysis import ResearchContext,DiscoveryEvidence,Generation
from app.schemas.discovery import Scope,Decision,Plan,Listings,MarketSummary,SourceAssessments,DiscoverySource,DiscoveryUnderstanding
from app.schemas.jd import JDExtraction,ReviewSkill
from app.domain.discovery_sources import POLICY,excluded_kind,candidates,validate_assessments,ranked_sources
from app.domain.discovery_conversation import conversation_messages
from app.domain.discovery_readiness import clarification_bundle,grounded_understanding,ready_for_research,research_context

log=logging.getLogger('uvicorn.error.discovery')


class EvidenceRejected(Exception):
    def __init__(self,source_ids):self.source_ids=list(source_ids)



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
    """Check listing identity/scope; accept model-interpreted faithful paraphrases."""
    result=[];seen=set()
    for listing in output.listings:
        if listing.ref>=len(sources) or listing.ref in seen:raise AIError('invalid_output',reason='source_reference')
        seen.add(listing.ref);source=sources[listing.ref];text=source.evidence or '';metadata=text+' '+(source.title or '')
        if not listing.relevant or excluded_kind(source):continue
        if listing.job_title not in metadata:
            raise AIError('invalid_output',reason='listing_provenance')
        if scope.career_stage!='unspecified' and listing.career_stage!=scope.career_stage:continue
        if scope.career_stage in ('internship','entry_level') and any(word in normal(listing.job_title).split() for word in ('senior','lead','principal','director')):continue
        if scope.location and (not listing.location or normal(scope.location) not in normal(listing.location)):continue
        if listing.location and normal(listing.location) not in normal(metadata):continue
        if listing.requirements:result.append({**listing.model_dump(mode='json'),'company':getattr(source,'company',None),'source_id':source.source_id,'source_url':source.url,'published_at':source.published_date.isoformat() if source.published_date else None})
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
        graph.add_edge(START,'plan_research');graph.add_edge('plan_research','search_job_listings');graph.add_edge('search_job_listings','extract_requirements');graph.add_conditional_edges('extract_requirements',self.next_research_node);graph.add_edge('aggregate_requirements','generate_career_target');graph.add_edge('generate_career_target',END)
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
        identifier=stable_id(owner,key,'career-discovery');stamp=now()
        row={'_id':identifier,'kind':'career_discovery','owner':owner,'version':1,'status':'conversation','decision':None,
            'messages':[],'created_at':stamp,'updated_at':stamp,'receipts':[]}
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

    async def model(self,row,stage,data,validate=None,*,split_incomplete=False,max_attempts=2):
        step=stage+'_'+fingerprint(data)[:20];attempts=(row.get('attempts') or {}).get(step,0)
        for attempt in range(attempts,max_attempts):
            token=quota_progress.set(None)
            feedback=validation_feedback.set({'reason':'schema_or_provenance','fields':[]} if attempt else None)
            try:
                result=await self.ai.generate(AIInput(stage=stage,context=json.dumps(data,separators=(',',':'),ensure_ascii=False)),Operation(row['owner'],row['run'],stage),current_revision=lambda:row['run'],validate_output=validate)
                if validate:validate(result.data)
                return result
            except AIError as error:
                if error.code not in ('invalid_output','incomplete_output') or split_incomplete and error.code=='incomplete_output':raise
                await thread(self.update,row,**{'attempts.'+step:attempt+1})
                if attempt+1==max_attempts:raise
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
            history=[Message(role=m['role'],content=m['content'][:400]) for m in conversation_messages(row.get('messages',[]))[-6:]]
            result=await self.ai.generate(AIInput(stage='discovery_turn',context=json.dumps({
                'previous':direction,'memory':previous.get('memory',{}),'understanding':DiscoveryUnderstanding.model_validate(previous.get('understanding',{})).model_dump(mode='json'),'scope':row.get('scope'),
                'research_status':row['status'],'research_question':row.get('research_question'),'facts':facts},separators=(',',':')),
                conversation=[*history,Message(role='user',content=body.message)]),
                Operation(owner,str(row['version']),'discovery_turn'),current_revision=lambda:str(row['version']))
            decision=Decision.model_validate(result.data.model_dump())
            if any(i not in allowed for i in decision.source_ids):raise AIError('invalid_output',reason='source_reference')
            return {'decision':decision.model_dump(mode='json'),'digest':digest}
        def evaluate(state):
            decision=Decision.model_validate(state['decision'])
            previous=row.get('decision') or {}
            changed_field=bool(row.get('scope') and decision.scope and normal(row['scope']['field'])!=normal(decision.scope.field))
            decision.understanding=grounded_understanding(decision.understanding,previous.get('understanding'),row.get('messages',[]),
                changed_field=changed_field,current_message=body.message)
            if decision.scope:
                stage=decision.understanding.career_stage;location=decision.understanding.location
                if stage.status in ('unsure','skipped'):decision.scope.career_stage='unspecified'
                elif stage.status=='known' and stage.value in ('internship','entry_level','experienced','unspecified'):decision.scope.career_stage=stage.value
                if location.status in ('unanswered','unsure','skipped'):decision.scope.location=None
                elif location.status=='known':decision.scope.location=location.value
            return {**state,'decision':decision.model_dump(mode='json'),'research_ready':ready_for_research(decision)}
        def clarify(state):
            decision=state['decision']
            # Existing research questions remain answerable without starting a run.
            if decision['action']=='ANSWER' and row['status'] not in ('conversation','failed') and decision.get('scope')==row.get('scope'):return state
            questions=clarification_bundle(decision['understanding'])
            decision.update(action='ASK_CLARIFICATION',reply=questions[0],question='\n'.join(questions[1:]) or None)
            return {**state,'decision':decision}
        def proceed(state):
            decision=state['decision']
            if row['status'] in ('conversation','failed') and decision['action'] in ('ASK_CLARIFICATION','SUGGEST_ROLES'):
                decision.update(action='START_RESEARCH',question=None)
            return {**state,'decision':decision}
        graph=StateGraph(dict);graph.add_node('understand_intent',understand)
        graph.add_node('evaluate_readiness',evaluate);graph.add_node('clarify_scope',clarify);graph.add_node('scope_ready',proceed)
        graph.add_edge(START,'understand_intent');graph.add_edge('understand_intent','evaluate_readiness')
        graph.add_conditional_edges('evaluate_readiness',lambda state:'ready' if state['research_ready'] else 'clarify',{'ready':'scope_ready','clarify':'clarify_scope'})
        graph.add_edge('scope_ready',END);graph.add_edge('clarify_scope',END)
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
            for k in ('interests','preferences','rejected_directions')) or research_context(decision.get('understanding'))!=research_context((row.get('decision') or {}).get('understanding')) or (decision.get('understanding',{}).get('other_interests') or {}).get('value')!=((row.get('decision') or {}).get('understanding',{}).get('other_interests') or {}).get('value')
        ready=ready_for_research(decision) and proposed and (decision['action'] in ('START_RESEARCH','CONFIRM_AREA','REFINE_SKILLS') or preference_changed and row['status']=='review')
        changed_scope=proposed and proposed!=row.get('scope')
        if ready and (changed_scope or row['status'] in ('conversation','failed') or decision['action']=='REFINE_SKILLS' or preference_changed and row['status']=='review'):
            values.update(await thread(self.research_values,row,proposed,False,decision['understanding']))
        if changed_scope and not ready and row['status'] in ('researching','waiting','review'):
            values.update(run=uuid4().hex,status='conversation',stage=None,scope=proposed,review_id=None,summary=None,summary_version=None,sources=[],aggregate=None)
            decision['source_ids']=[]
        reply=plain_reply(decision['reply'])
        if decision['action'] in ('START_RESEARCH','CONFIRM_AREA') and proposed:
            reply='Your career direction is '+proposed['area']+'.'
            if row['status'] in ('researching','waiting') and not values.get('status'):reply+=' Research for this direction is continuing.'
            decision['reply']=reply
            if decision.get('question') and re.search(r'(?i)(?:start|begin|confirm|approve|proceed).*(?:research|area|scope)|(?:research).*(?:start|begin)',decision['question']):decision['question']=None
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

    def research_values(self,row,scope,refresh,understanding=None):
        context=research_context(understanding)
        scope_key=fingerprint({'scope':{k:normal(v) if isinstance(v,str) else v for k,v in scope.items()},'context':context})
        cached=None if refresh else self.rows.find_one({'kind':'career_discovery','owner':row['owner'],'scope_key':scope_key,
            'research_policy':POLICY,'aggregate':{'$ne':None},'researched_at':{'$gt':now()-timedelta(hours=self.settings.freshness_hours)}},sort=[('researched_at',-1)])
        if not refresh and row.get('scope_key')==scope_key and row.get('research_policy')==POLICY and row['status'] in ('failed','researching','waiting'):cached=row
        values={'run':uuid4().hex,'scope':scope,'scope_key':scope_key,'status':'researching','stage':'plan_research',
            'research_policy':POLICY,'next_attempt_at':now(),'lease':None,'lease_until':now(),'error_code':None,'limit_scope':None,'provider':None,'updated_at':now()}
        for field in ('plan','sources','searched','listings','evaluated','aggregate','generation','researched_at','search_failures','candidates','assessments','split_batches','narrowed_sources','extraction_failures','followup_requested','rejected_source_ids','replacement_searches','replacement_query','replacement_shortfall'):
            values[field]=cached.get(field) if cached else None
        if cached and cached.get('research_policy')!=POLICY:values.update(aggregate=None,assessments=None)
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
        if not ready_for_research(decision):raise GoalError('Complete the discovery context in chat before researching; unsure or skip answers are allowed.',422)
        values=self.research_values(row,body.scope.model_dump(mode='json'),body.refresh,decision.understanding.model_dump())
        changed=self.rows.update_one({'_id':identifier,'owner':owner,'version':body.expected_version,'status':row['status']},
            {'$set':values,'$inc':{'version':1},'$push':{'receipts':{'$each':[{'key':key,'hash':digest}],'$slice':-100}}})
        if not changed.matched_count:raise GoalError('A newer research scope arrived; reload it.')
        return self.get(identifier,owner)

    async def plan(self,state):
        row=await thread(self.research_row,state)
        if row.get('plan'):return state
        result=await self.model(row,'discovery_plan',{'scope':row['scope'],'research_context':research_context((row.get('decision') or {}).get('understanding')),'year':now().year})
        plan=Plan.model_validate(result.data.model_dump())
        scope=Scope.model_validate(row['scope'])
        prefix=' '.join(v for v in (scope.field,scope.area,scope.location,scope.career_stage.replace('_',' ') if scope.career_stage!='unspecified' else None,str(now().year)) if v)
        queries=list(dict.fromkeys((prefix+' '+v+' job requirements')[:180] for v in plan.queries))
        await thread(self.update,row,plan={'related_roles':plan.related_roles,'queries':queries},stage='search_job_listings')
        return state

    def research_queries(self,row):
        scope=Scope.model_validate(row['scope'])
        # Retried older plans also gain field context to disambiguate role names.
        initial=[q if normal(scope.field) in normal(q) else scope.field+' '+q for q in row['plan']['queries']]
        prefix=' '.join(v for v in (scope.field,scope.area,scope.location,
            scope.career_stage.replace('_',' ') if scope.career_stage!='unspecified' else None,str(now().year)) if v)
        followups=[(prefix+' '+term)[:180] for term in (
            'individual employer vacancy responsibilities required skills',
            'related role employers careers job qualifications')[:self.settings.max_followups]]
        return list(dict.fromkeys(initial+followups))[:6],initial

    async def search(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return state
        scope=Scope.model_validate(row['scope']);context=ResearchContext(field=scope.field,role=scope.area,location=scope.location,seniority_level=scope.career_stage)
        searched=row.get('searched') or [];found=row.get('candidates') or row.get('sources') or [];failures=row.get('search_failures') or []
        queries,initial=self.research_queries(row)
        remaining=[q for q in initial if q not in searched]
        if not remaining:
            # A quota/restart resume must finish existing assessment/extraction
            # before deciding whether additional paid searches are necessary.
            if not row.get('followup_requested'):return state
            remaining=[q for q in queries if q not in searched][:2]
        async def fetch(query):
            for attempt in range(2):
                try:
                    async with asyncio.timeout(30):return await self.source.collect_discovery_query(context,query)
                except SourceRateLimit:raise
                except (TimeoutError,GoalError):
                    if attempt:raise
                    await asyncio.sleep(.5)
        for offset in range(0,len(remaining),2):
            batch=remaining[offset:offset+2]
            results=await asyncio.gather(*(fetch(q) for q in batch),return_exceptions=True);rate=None
            for query,result in zip(batch,results):
                if isinstance(result,SourceRateLimit):rate=result;continue
                searched.append(query)
                if isinstance(result,BaseException):failures.append('source_unavailable');continue
                found=[source.model_dump(mode='json') for source in candidates([*found,*[v.model_dump(mode='json') for v in result]])]
            await thread(self.update,row,candidates=found,searched=searched,search_failures=failures,followup_requested=rate is not None,stage='assess_job_listings')
            if rate:raise rate
        return state

    async def assess_candidates(self,state):
        row=await thread(self.research_row,state)
        sources=[DiscoverySource.model_validate(v) for v in row.get('candidates') or row.get('sources') or []
            if v['source_id'] not in (row.get('rejected_source_ids') or [])]
        assessments=row.get('assessments') or {}
        rejected=set(row.get('rejected_source_ids') or [])
        failed=[]
        for source in sources:
            if excluded_kind(source) and source.source_id not in rejected:
                assessments[source.source_id]={'relevant':False,'score':0,'company':source.company,'quote':None}
                failed.append(source.source_id)
        pending=[source for source in sources if source.source_id not in assessments and source.source_id not in rejected]
        for offset in range(0,len(pending),3):
            batch=pending[offset:offset+3]
            def validate(output):validate_assessments(SourceAssessments.model_validate(output.model_dump()),batch)
            try:
                result=await self.model(row,'discovery_assess',{'scope':row['scope'],'research_context':research_context((row.get('decision') or {}).get('understanding')),
                    'sources':[{'ref':i,'url':v.url,'title':v.title,'excerpt':v.evidence} for i,v in enumerate(batch)]},validate,max_attempts=1)
                values=validate_assessments(result.data,batch)
                assessments.update(values)
                failed.extend(key for key,value in values.items() if not value['relevant'])
            except AIError as error:
                if error.code not in ('invalid_output','incomplete_output'):raise
                log.warning('discovery_evidence_rejected stage=discovery_assess reason=%s fields=%s',error.reason or 'assessment_validation',error.fields)
                failed.extend(source.source_id for source in batch)
            await thread(self.update,row,assessments=assessments)
        return sources,assessments,failed

    async def replace_rejected_evidence(self,state,source_ids):
        row=await thread(self.research_row,state)
        rejected=list(dict.fromkeys([*(row.get('rejected_source_ids') or []),*source_ids]))
        if row.get('replacement_searches'):
            await thread(self.update,row,rejected_source_ids=rejected,replacement_shortfall=True,
                sources=[v for v in row.get('sources') or [] if v['source_id'] not in rejected])
            return False
        scope=Scope.model_validate(row['scope'])
        # Replace only the rejected evidence in this same scope, keeping all other
        # candidates, assessments and completed extractions. One retry per run.
        query=' '.join(v for v in (scope.field,scope.area,scope.location,
            scope.career_stage.replace('_',' ') if scope.career_stage!='unspecified' else None,
            str(now().year),'alternative employers individual job vacancies responsibilities required skills') if v)[:350]
        await thread(self.update,row,replacement_searches=1,rejected_source_ids=rejected,
            sources=[v for v in row.get('sources') or [] if v['source_id'] not in rejected],
            stage='search_job_listings',replacement_query=query)
        # A durable marker lets quota/restart recovery resume this same search.
        await self.finish_replacement_search(state)
        return True

    async def finish_replacement_search(self,state):
        row=await thread(self.research_row,state)
        query=row.get('replacement_query')
        if not query:return
        scope=Scope.model_validate(row['scope'])
        context=ResearchContext(field=scope.field,role=scope.area,location=scope.location,seniority_level=scope.career_stage)
        try:
            async with asyncio.timeout(30):found=await self.source.collect_discovery_query(context,query)
        except SourceRateLimit:raise
        except (TimeoutError,GoalError):
            await thread(self.update,row,replacement_query=None,replacement_shortfall=True,stage='assess_job_listings')
            return
        previous=row.get('candidates') or []
        known={v['url'] for v in previous}
        fresh=[v.model_dump(mode='json') for v in found if v.url not in known]
        await thread(self.update,row,replacement_query=None,searched=[*(row.get('searched') or []),query],
            candidates=[v.model_dump(mode='json') for v in candidates([*previous,*fresh])],stage='assess_job_listings')
        if not fresh:await thread(self.update,row,replacement_shortfall=True)

    async def extract_batch(self,state,batch,*,max_requirements=15):
        row=await thread(self.research_row,state)
        batch=[v for v in batch if v.source_id not in (row.get('evaluated') or [])]
        if not batch:return
        signature=fingerprint([v.source_id for v in batch])
        split=signature in (row.get('split_batches') or [])
        if len(batch)==1 and batch[0].source_id in (row.get('narrowed_sources') or []):max_requirements=8
        if not split:
            scope=Scope.model_validate(row['scope'])
            def validate(output):
                parsed=Listings.model_validate(output.model_dump());validated_listings(parsed,batch,scope)
                if any(len(v.requirements)>max_requirements for v in parsed.listings):raise AIError('invalid_output',reason='requirement_limit')
                if any(i<0 or i>=len(batch) for i in parsed.question_refs) or parsed.question and not parsed.question_refs:
                    raise AIError('invalid_output',reason='question_reference')
            try:
                result=await self.model(row,'discovery_extract',{'scope':row['scope'],'memory':(row.get('decision') or {}).get('memory',{}),
                    'research_context':research_context((row.get('decision') or {}).get('understanding')),'previous_question':row.get('research_question'),'max_requirements':max_requirements,
                    'sources':[{'ref':i,'title':v.title,'excerpt':v.evidence} for i,v in enumerate(batch)]},validate,split_incomplete=True,max_attempts=1)
            except AIError as error:
                if error.code not in ('incomplete_output','context_limit'):raise
                if len(batch)>1:
                    await thread(self.update,row,split_batches=[*(row.get('split_batches') or []),signature]);split=True
                elif max_requirements>8:
                    await thread(self.update,row,narrowed_sources=list(dict.fromkeys([*(row.get('narrowed_sources') or []),batch[0].source_id])))
                    return await self.extract_batch(state,batch,max_requirements=8)
                else:
                    await thread(self.update,row,extraction_failures=list(dict.fromkeys([*(row.get('extraction_failures') or []),batch[0].source_id])),
                        evaluated=[*(row.get('evaluated') or []),batch[0].source_id])
                    return
            else:
                extracted=validated_listings(result.data,batch,scope)
                supported={item['source_id'] for item in extracted}
                rejected=[item.source_id for item in batch if item.source_id not in supported]
                row=await thread(self.research_row,state)
                values={'listings':[*(row.get('listings') or []),*extracted],
                    'evaluated':[*(row.get('evaluated') or []),*[v.source_id for v in batch]],'generation':result.generation.model_dump(mode='json')}
                if result.data.question and not row.get('research_question'):
                    question=plain_reply(result.data.question)
                    links=citations([batch[i].source_id for i in result.data.question_refs],[v.model_dump(mode='json') for v in batch])
                    values['research_question']=question
                    await thread(self.rows.update_one,{'_id':row['_id'],'run':row['run'],'lease':row['lease']},
                        {'$push':{'messages':{'role':'assistant','content':question+' '+links}}})
                await thread(self.update,row,**values)
                if rejected:raise EvidenceRejected(rejected)
                return
        if split:
            middle=len(batch)//2
            await self.extract_batch(state,batch[:middle])
            await self.extract_batch(state,batch[middle:])

    async def extract(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return state
        await self.finish_replacement_search(state)
        while True:
            try:
                row=await thread(self.research_row,state)
                await thread(self.update,row,stage='assess_job_listings')
                sources,assessments,rejected=await self.assess_candidates(state)
                if rejected:
                    await self.replace_rejected_evidence(state,rejected)
                    continue
                row=await thread(self.research_row,state)
                selected=ranked_sources(sources,assessments,row.get('evaluated') or [],row.get('listings') or [],self.settings.max_listings)
                selected=[v for v in selected if v.source_id not in (row.get('rejected_source_ids') or [])]
                if not selected:raise EvidenceRejected([])
                await thread(self.update,row,sources=[v.model_dump(mode='json') for v in selected],stage='extract_requirements')
                rejected=[]
                for offset in range(0,len(selected),3):
                    batch=selected[offset:offset+3]
                    try:await self.extract_batch(state,batch)
                    except EvidenceRejected as error:rejected.extend(error.source_ids)
                    except AIError as error:
                        if error.code!='invalid_output':raise
                        log.warning('discovery_evidence_rejected stage=discovery_extract reason=%s fields=%s',error.reason or 'extraction_validation',error.fields)
                        rejected.extend(v.source_id for v in batch)
                if rejected:raise EvidenceRejected(rejected)
                return state
            except EvidenceRejected as error:
                replaced=await self.replace_rejected_evidence(state,error.source_ids)
                if not replaced and not error.source_ids:
                    raise AIError('invalid_output',reason='provenance') from None

    def selected_listings(self,row):
        ids={source['source_id'] for source in row.get('sources') or []}
        return [listing for listing in row.get('listings') or [] if listing['source_id'] in ids]

    async def next_research_node(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return 'aggregate_requirements'
        result=aggregate(Scope.model_validate(row['scope']),self.selected_listings(row),self.settings)
        if result['coverage']=='good':return 'aggregate_requirements'
        sources=[DiscoverySource.model_validate(v) for v in row.get('candidates') or row.get('sources') or []
            if v['source_id'] not in (row.get('rejected_source_ids') or [])]
        selected=ranked_sources(sources,row.get('assessments') or {},row.get('evaluated') or [],row.get('listings') or [],self.settings.max_listings)
        if any(v.source_id not in (row.get('evaluated') or []) for v in selected):return 'extract_requirements'
        queries,_=self.research_queries(row)
        if any(q not in (row.get('searched') or []) for q in queries):
            await thread(self.update,row,followup_requested=True)
            return 'search_job_listings'
        return 'aggregate_requirements'

    async def combine(self,state):
        row=await thread(self.research_row,state)
        if row.get('aggregate'):return state
        await thread(self.update,row,stage='aggregate_requirements')
        result=aggregate(Scope.model_validate(row['scope']),self.selected_listings(row),self.settings)
        rejected=len(set(row.get('rejected_source_ids') or []) | {key for key,item in (row.get('assessments') or {}).items() if not item.get('relevant',False)})
        if rejected:result['warnings'].append(f'{rejected} retrieved pages were excluded as irrelevant, unsupported or unusable evidence; only validated listings support this target.')
        if row.get('replacement_shortfall'):result['warnings'].append('The single replacement search did not replace every rejected source. This target uses only the usable evidence retained; research coverage may be limited.')
        if row.get('narrowed_sources') or row.get('extraction_failures'):result['warnings'].append('Some source extractions were reduced or could not finish after output/context limits. Their coverage is incomplete; unsupported requirements were not included.')
        if row.get('search_failures'):result['warnings'].append('Some searches failed; the target includes only successfully retrieved evidence.')
        supported={listing['source_id'] for listing in result['listings']}
        await thread(self.update,row,aggregate=result,sources=[source for source in row.get('sources') or [] if source['source_id'] in supported],stage='generate_career_target')
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
                    'understanding':DiscoveryUnderstanding.model_validate(decision.get('understanding',{})).model_dump(mode='json'),'excluded_skills':decision.get('excluded_skills',[]),'requested_skills':requested,
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
        except (AIError,SourceRateLimit,TimeoutError,ValueError) as error:
            wait=isinstance(error,SourceRateLimit) or isinstance(error,AIError) and error.code=='rate_limited'
            code=error.code if isinstance(error,AIError) else 'source_rate_limited' if isinstance(error,SourceRateLimit) else 'research_timeout' if isinstance(error,TimeoutError) else 'research_validation_failed'
            delay=max(1,getattr(error,'retry_after',None) or 60)
            log.warning('error_code=%s limit_scope=%s',code,getattr(error,'limit_scope',None))
            try:await thread(self.update,row,status='waiting' if wait else 'failed',error_code=code,limit_scope=getattr(error,'limit_scope',None),provider='brave' if isinstance(error,SourceRateLimit) else getattr(error,'provider',None),next_attempt_at=now()+timedelta(seconds=delay),lease_until=now())
            except GoalError:pass
        except GoalError:
            return
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

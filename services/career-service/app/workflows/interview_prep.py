"""Keyword-only interview guide for specific jobs: validated model keywords plus deterministic planning."""
import json
import re
from datetime import date,timedelta
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput
from app.ai.routing import chat_models
from app.repositories.goals import GoalError,now
from app.schemas.interview_prep import GuideSource,InterviewPrepGuide,Question,ResumeLink,Stage,Topic,ScheduleStep
from app.workflows.structured import structured_node

RESEARCH_CATEGORIES=('interview_intelligence','company_intelligence')
BASIS_RANK={'confirmed':0,'candidate_report':1,'prediction':2}
EVIDENCE_BASIS={'official':'confirmed','candidate_reported':'candidate_report','third_party':'candidate_report','inferred':'prediction'}
PRIORITY_RANK={'high':0,'medium':1,'low':2}
NUMBER=re.compile(r'\d+(?:[.,]\d+)*')
DEFAULT_DAYS=7


def require_specific_job(goal):
    if goal.target_type!='specific_job':
        raise GoalError('Interview preparation guides are only available for a specific job.',409)


def research_catalogue(record):
    """Public findings, each addressed by a request-owned reference the model must copy."""
    items=[]
    if not record or not getattr(record,'intelligence',None):return items
    for category in RESEARCH_CATEGORIES:
        result=record.intelligence.categories.get(category)
        for finding in (result.findings if result else []):
            items.append({'ref':f'research_{len(items)}','category':category,'field':finding.field,'value':finding.value,
                'evidence_type':finding.evidence_type,'scope':finding.scope,'round_number':finding.round_number,
                'round_name':finding.round_name,'source_ids':list(finding.source_ids)})
    return items


def cv_catalogue(snapshot):
    if snapshot is None:return []
    return [{'name':skill.name,'months':skill.experience_months,'context':(skill.context or '')[:200]} for skill in snapshot.skills[:60]]


def goal_catalogue(goal):
    return {'role':goal.role,'company':goal.company,'field':goal.field,'location':goal.location,'seniority_level':goal.seniority_level,
        'employment_type':goal.employment_type,'responsibilities':list(goal.responsibilities),
        'skills':[{'name':s.name,'priority':s.priority,'category':s.category} for s in goal.skills[:60]]}


def numbers(text):
    return set(NUMBER.findall(text))


def keyword_texts(output):
    """(top-level field, text) pairs so a rejection names the offending section."""
    values=[('role',v) for v in output.role]+[('success',v) for v in output.success]
    for stage in output.process:values.extend(('process',v) for v in [stage.name,*stage.format])
    for link in output.resume:values.extend(('resume',v) for v in [link.competency,*link.signals])
    for topic in output.syllabus:values.extend(('syllabus',v) for v in [topic.name,*topic.terms])
    values.extend(('company',v) for group in output.company.model_dump().values() for v in group)
    values.extend(('questions',q.text) for q in output.questions)
    return values


def validator(context):
    refs={item['ref'] for item in context['research']}
    skills={item['name'] for item in context['cv']}
    allowed=numbers(json.dumps(context,ensure_ascii=False))
    def validate(output):
        groups=[('process',output.process),('syllabus',output.syllabus),('questions',output.questions)]
        for name,items in groups:
            for index,item in enumerate(items):
                if any(ref not in refs for ref in item.refs):
                    raise AIError('invalid_output',True,reason='provenance',fields=(name,'refs'),
                        violations=({'field':f'{name}.{index}.refs','issue':'unknown_research_reference'},))
        for index,link in enumerate(output.resume):
            if link.skill is not None and link.skill not in skills:
                raise AIError('invalid_output',True,reason='provenance',fields=('resume','skill'),
                    violations=({'field':f'resume.{index}.skill','issue':'unknown_cv_skill'},))
        # Never invent achievements or numbers: digits must already be in the supplied facts.
        for section,value in keyword_texts(output):
            if numbers(value)-allowed:
                raise AIError('invalid_output',True,reason='provenance',fields=(section,),
                    violations=({'field':section,'issue':'unsupported_number'},))
    return validate


def basis_for(refs,catalogue):
    """Evidence labels come from the stored findings, never from the model."""
    found=[EVIDENCE_BASIS[catalogue[ref]['evidence_type']] for ref in refs if ref in catalogue]
    return (min(found,key=BASIS_RANK.get) if found else 'prediction'),list(dict.fromkeys(s for ref in refs if ref in catalogue for s in catalogue[ref]['source_ids']))[:3]


def make_schedule(topics,process,resume,today,interview_date):
    """Deterministic plan: spread fixed phases over the days left, or a default week."""
    high=[t.name for t in topics if t.priority=='high'];medium=[t.name for t in topics if t.priority!='high']
    phases=[('Role and process',[s.name for s in process][:3] or ['Role keywords']),
        ('Core topics',high[:4] or medium[:4] or ['Core skills']),
        ('Supporting topics',medium[:4] or high[4:8]),
        ('Resume stories',[r.competency for r in resume if r.status!='gap'][:4] or ['STAR stories']),
        ('Mock interview',['Mock interview','Timed answers']),
        ('Final review',['High-priority topics','Questions to ask'])]
    phases=[(name,focus) for name,focus in phases if focus]
    days=(interview_date-today).days if interview_date else None
    if days is not None and days<0:days=None
    steps=min(len(phases),max(1,days if days is not None else DEFAULT_DAYS))
    if days==0:steps=1
    # Keep the last phase (final review) when compressing into fewer days.
    chosen=phases if steps>=len(phases) else [*phases[:steps-1],phases[-1]] if steps>1 else [phases[-1]]
    span=days if days is not None else DEFAULT_DAYS
    result=[]
    for index,(name,focus) in enumerate(chosen):
        offset=index*span//max(1,len(chosen)) if len(chosen)>1 else 0
        when=(today+timedelta(days=offset)).strftime('%b %d').replace(' 0',' ') if days is not None else f'Day {offset+1}'
        result.append(ScheduleStep(when=when,focus=[name,*focus][:4]))
    return result


def assemble(goal,record,output,catalogue,cv,interview_date,today):
    by_ref={item['ref']:item for item in catalogue}
    process=[]
    for stage in output.process:
        basis,ids=basis_for(stage.refs,by_ref)
        process.append(Stage(round=stage.round,name=stage.name,format=stage.format,basis=basis,source_ids=ids))
    process.sort(key=lambda s:(s.round is None,s.round or 0))
    topics=[]
    for topic in output.syllabus:
        basis,ids=basis_for(topic.refs,by_ref)
        topics.append(Topic(name=topic.name,priority=topic.priority,depth=topic.depth,terms=topic.terms,basis=basis,source_ids=ids))
    topics.sort(key=lambda t:PRIORITY_RANK[t.priority])
    questions=[]
    for question in output.questions:
        basis,ids=basis_for(question.refs,by_ref)
        questions.append(Question(text=question.text,kind=question.kind,basis=basis,source_ids=ids))
    resume=[ResumeLink(competency=link.competency,skill=link.skill,signals=link.signals,
        status='gap' if link.skill is None else 'strength' if link.signals else 'partial') for link in output.resume]
    used={s for item in [*process,*topics,*questions] for s in item.source_ids}
    known={s.source_id:s for s in (record.sources if record else [])}
    sources=[GuideSource(source_id=i,url=known[i].url,title=known[i].title) for i in sorted(used) if i in known]
    not_covered=['recent news']
    if not catalogue:not_covered.append('public research')
    if not cv:not_covered.append('resume map')
    return InterviewPrepGuide(goal_id=goal.id,goal_version=goal.version,research_id=getattr(record,'id',None),generated_at=now(),
        interview_date=interview_date,role=output.role,success=output.success,process=process,resume=resume,syllabus=topics,
        company=output.company,questions=questions,schedule=make_schedule(topics,process,resume,today,interview_date),
        sources=sources,not_covered=not_covered)


def collection(request):
    return request.app.state.goal_store.goals.database['interview_prep_guides']


def key_for(account,goal):return f'{account}:{goal.id}'


async def read_saved(request,account,goal):
    row=await thread(collection(request).find_one,{'_id':key_for(account,goal)})
    if not row or row.get('goal_version')!=goal.version:return None
    return InterviewPrepGuide.model_validate(row['guide'])


async def generate(request,account,goal,research_record,cv_snapshot,interview_date,today=None):
    require_specific_job(goal)
    catalogue=research_catalogue(research_record);cv=cv_catalogue(cv_snapshot)
    context={'goal':goal_catalogue(goal),'research':catalogue,'cv':cv}
    encoded=json.dumps(jsonable_encoder(context),separators=(',',':'),ensure_ascii=False)
    if len(encoded)>40000:raise AIError('context_limit')
    revision=f'{goal.id}:{goal.version}'
    async def current():
        state=await thread(request.app.state.goal_store.current,account)
        saved=state['goal']
        if not saved or saved.id!=goal.id or saved.version!=goal.version:raise AIError('stale_input',True)
        return revision
    validate=validator(jsonable_encoder(context))
    @structured_node
    async def present(state):
        result=await chat_models(request.app.state).generate(AIInput(stage='interview_prep',context=encoded),
            Operation(account,revision,'interview_prep'),current_revision=current,validate_output=validate)
        validate(result.data)
        return result.data
    output=await present({})
    guide=assemble(goal,research_record,output,catalogue,cv,interview_date,today or now().date())
    await thread(collection(request).replace_one,{'_id':key_for(account,goal)},
        {'_id':key_for(account,goal),'goal_version':goal.version,'guide':jsonable_encoder(guide)},True)
    return guide

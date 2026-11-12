"""Fill empty interview-preparation slots (questions to expect, how to prepare) with labelled AI predictions."""
import json
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput
from app.ai.routing import chat_models
from app.repositories.goals import now
from app.schemas.interview_prep import Gap,InterviewSuggestions,Suggestion
from app.schemas.opportunity import plain_text
from app.workflows.structured import structured_node

GAP_FIELDS=('interview_questions','preparation_topics')
HEADLINE_FIELDS=('recruitment_stages','application_timeline','difficulty')


def interview_findings(record):
    if not record or not getattr(record,'intelligence',None):return []
    result=record.intelligence.categories.get('interview_intelligence')
    return list(result.findings) if result else []


def find_gaps(findings):
    """Every empty slot: missing headline facts, then per-round slots (or whole-process slots without rounds)."""
    rounds={}
    for f in findings:
        if f.round_number is not None and not rounds.get(f.round_number):rounds[f.round_number]=f.round_name
    present={(f.round_number,f.field) for f in findings}
    headline=[Gap(field=field) for field in HEADLINE_FIELDS if (None,field) not in present]
    if rounds:
        return headline+[Gap(round_number=n,round_name=rounds[n],field=field) for n in sorted(rounds) for field in GAP_FIELDS if (n,field) not in present]
    return headline+[Gap(field=field) for field in GAP_FIELDS if (None,field) not in present]


def research_catalogue(findings):
    return [{'field':f.field,'value':plain_text(f.value),'round_number':f.round_number,'round_name':f.round_name,'evidence_type':f.evidence_type} for f in findings]


def goal_catalogue(goal):
    return {'role':goal.role,'company':goal.company,'field':goal.field,'location':goal.location,'seniority_level':goal.seniority_level,
        'employment_type':goal.employment_type,'target_type':goal.target_type,'responsibilities':list(goal.responsibilities or [])[:20],
        'skills':[{'name':s.name,'priority':s.priority,'category':s.category} for s in (goal.skills or [])[:60]]}


def validator(context):
    wanted={(g['round_number'],g['field']) for g in context['gaps']}
    def validate(output):
        for index,fill in enumerate(output.fills):
            if (fill.round_number,fill.field) not in wanted:
                raise AIError('invalid_output',True,reason='provenance',fields=('fills',),
                    violations=({'field':f'fills.{index}','issue':'unrequested_gap'},))
            # Headline facts are single values; extra items would read as separate facts.
            if fill.field in HEADLINE_FIELDS and len(fill.items)>1:
                raise AIError('invalid_output',True,reason='schema',fields=('fills',),
                    violations=({'field':f'fills.{index}.items','issue':'one_item_expected'},))
    return validate


def collection(request):
    return request.app.state.goal_store.goals.database['interview_prep_suggestions']


def key_for(account,goal):return f'{account}:{goal.id}'


def research_key(record):return getattr(record,'id',None)


async def read_saved(request,account,goal,record):
    row=await thread(collection(request).find_one,{'_id':key_for(account,goal)})
    if not row or row.get('goal_version')!=goal.version or row.get('research_id')!=research_key(record):return None
    return InterviewSuggestions.model_validate(row['suggestions'])


async def generate(request,account,goal,record):
    findings=interview_findings(record)
    gaps=find_gaps(findings)
    suggestions=InterviewSuggestions(goal_id=goal.id,goal_version=goal.version,research_id=research_key(record),generated_at=now(),gaps=gaps)
    if gaps:
        context=jsonable_encoder({'goal':goal_catalogue(goal),'research':research_catalogue(findings),'gaps':gaps})
        encoded=json.dumps(context,separators=(',',':'),ensure_ascii=False)
        if len(encoded)>40000:raise AIError('context_limit')
        revision=f'{goal.id}:{goal.version}'
        async def current():
            state=await thread(request.app.state.goal_store.current,account)
            saved=state['goal']
            if not saved or saved.id!=goal.id or saved.version!=goal.version:raise AIError('stale_input',True)
            return revision
        validate=validator(context)
        @structured_node
        async def present(state):
            result=await chat_models(request.app.state).generate(AIInput(stage='interview_prep',context=encoded),
                Operation(account,revision,'interview_prep'),current_revision=current,validate_output=validate)
            validate(result.data)
            return result.data
        output=await present({})
        seen=set();items=[]
        for fill in output.fills:
            for value in fill.items:
                if (fill.round_number,fill.field,plain_text(value).casefold()) in seen:continue
                seen.add((fill.round_number,fill.field,plain_text(value).casefold()))
                items.append(Suggestion(round_number=fill.round_number,field=fill.field,value=value))
        suggestions.items=items
    await thread(collection(request).replace_one,{'_id':key_for(account,goal)},
        {'_id':key_for(account,goal),'goal_version':goal.version,'research_id':suggestions.research_id,'suggestions':jsonable_encoder(suggestions)},True)
    return suggestions

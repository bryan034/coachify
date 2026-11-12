"""About the role digest: the model condenses each card's goal text or research findings into cited bullets."""
import json
import re
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput
from app.ai.routing import chat_models
from app.repositories.goals import now
from app.schemas.opportunity import FIELDS,plain_text
from app.schemas.role_summary import FORMAT,Bullet,CardDigest,GeneratedCard,RoleSummary,markup_issue
from app.workflows.structured import structured_node

# The About the role page shows every category except interview research.
ROLE_CATEGORIES=('internship_insights','career_progression','conversion_outcomes','company_intelligence')
# Every topic the page shows, in page order; each is sourced, AI-made, or (only on failure) not filled.
ROLE_FIELDS=tuple(dict.fromkeys(field for category in ROLE_CATEGORIES for field in FIELDS[category]))
TITLES={'eligibility':'Eligibility and commitment','work':'What you would work on','compensation':'Salary','benefits':'Benefits',
    'projects':'What interns work on','mentorship':'Mentorship','work_life_balance':'Hours and workload','full_time_role':'Role after the internship',
    'career_path':'Career path','conversion_salary':'Full-time salary','conversion_rate':'Conversion rate','historical_cohort':'Intake',
    'offer_acceptance':'Offers and acceptances','company_culture':'Company culture','team_culture':'Team culture','management':'Management'}
NUMBER=re.compile(r'\d+(?:[.,]\d+)*')


def build_cards(goal,record):
    """Cards in page order; item refs match what the frontend can resolve to sources."""
    cards=[]
    requirements=[{'ref':f'req:{r.requirement_id}','text':str(r.description)} for r in (goal.non_skill_requirements or [])]
    if requirements:cards.append({'card_id':'eligibility','title':'Eligibility and commitment','items':requirements})
    work=([{'ref':'summary','text':str(goal.summary)}] if goal.summary else [])+[{'ref':f'resp:{i}','text':str(t)} for i,t in enumerate(goal.responsibilities or [])]
    if work:cards.append({'card_id':'work','title':'What you would work on','items':work})
    fields={}
    categories=record.intelligence.categories if record and getattr(record,'intelligence',None) else {}
    for category in ROLE_CATEGORIES:
        result=categories.get(category)
        for f in (result.findings if result else []):
            fields.setdefault(f.field,[]).append({'ref':f.finding_id,'text':plain_text(f.value)})
    cards.extend({'card_id':field,'title':TITLES.get(field,field.replace('_',' ')),'items':items} for field,items in fields.items())
    return cards


def missing_cards(cards):
    present={c['card_id'] for c in cards}
    return [{'card_id':i,'title':TITLES[i]} for i in ('eligibility','work',*ROLE_FIELDS) if i not in present]


def numbers(text):return set(NUMBER.findall(text))


def markup_error(path,text):
    issue=markup_issue(text)
    return AIError('invalid_output',True,reason='format',fields=(path.split('.')[0],),violations=({'field':path,'issue':issue},)) if issue else None


def validator(cards,missing=()):
    by_id={c['card_id']:c for c in cards}
    wanted={m['card_id'] for m in missing}
    def validate(output):
        filled=set()
        for index,fill in enumerate(output.fills):
            if fill.card_id not in wanted or fill.card_id in filled:
                raise AIError('invalid_output',True,reason='provenance',fields=('fills',),
                    violations=({'field':f'fills.{index}.card_id','issue':'unknown_or_repeated_card'},))
            filled.add(fill.card_id)
            for b,text in enumerate(fill.bullets):
                if error:=markup_error(f'fills.{index}.bullets.{b}',text):raise error
        seen=set()
        for index,card in enumerate(output.cards):
            source=by_id.get(card.card_id)
            if source is None or card.card_id in seen:
                raise AIError('invalid_output',True,reason='provenance',fields=('cards',),
                    violations=({'field':f'cards.{index}.card_id','issue':'unknown_or_repeated_card'},))
            seen.add(card.card_id)
            refs={item['ref'] for item in source['items']}
            allowed=numbers(' '.join(item['text'] for item in source['items']))
            if numbers(card.headline)-allowed:
                raise AIError('invalid_output',True,reason='provenance',fields=('cards',),
                    violations=({'field':f'cards.{index}.headline','issue':'unsupported_number'},))
            for b,bullet in enumerate(card.bullets):
                if error:=markup_error(f'cards.{index}.bullets.{b}.text',bullet.text):raise error
                if not set(bullet.refs)<=refs:
                    raise AIError('invalid_output',True,reason='provenance',fields=('cards',),
                        violations=({'field':f'cards.{index}.bullets.{b}.refs','issue':'ref_outside_card'},))
                # A summary may not introduce figures its own card does not state.
                if numbers(bullet.text)-allowed:
                    raise AIError('invalid_output',True,reason='provenance',fields=('cards',),
                        violations=({'field':f'cards.{index}.bullets.{b}.text','issue':'unsupported_number'},))
    return validate


def collection(request):
    return request.app.state.goal_store.goals.database['role_summaries']


def key_for(account,goal):return f'{account}:{goal.id}'


def research_key(record):return getattr(record,'id',None)


async def read_saved(request,account,goal,record):
    row=await thread(collection(request).find_one,{'_id':key_for(account,goal)})
    if not row or row.get('summary',{}).get('format')!=FORMAT or row.get('goal_version')!=goal.version or row.get('research_id')!=research_key(record):return None
    return RoleSummary.model_validate(row['summary'])


async def generate(request,account,goal,record):
    cards=build_cards(goal,record);missing=missing_cards(cards)
    summary=RoleSummary(goal_id=goal.id,goal_version=goal.version,research_id=research_key(record),generated_at=now())
    if cards or missing:
        context=jsonable_encoder({'role':goal.role,'company':goal.company,'field':goal.field,'location':goal.location,
            'employment_type':goal.employment_type,'seniority_level':goal.seniority_level,'cards':cards,'missing':missing})
        encoded=json.dumps(context,separators=(',',':'),ensure_ascii=False)
        if len(encoded)>40000:raise AIError('context_limit')
        revision=f'{goal.id}:{goal.version}'
        async def current():
            state=await thread(request.app.state.goal_store.current,account)
            saved=state['goal']
            if not saved or saved.id!=goal.id or saved.version!=goal.version:raise AIError('stale_input',True)
            return revision
        validate=validator(context['cards'],context['missing'])
        @structured_node
        async def present(state):
            result=await chat_models(request.app.state).generate(AIInput(stage='role_summary',context=encoded),
                Operation(account,revision,'role_summary'),current_revision=current,validate_output=validate)
            validate(result.data)
            return result.data
        output=await present({})
        summary.cards=[CardDigest(card_id=c.card_id,headline=c.headline,bullets=[Bullet(text=b.text,refs=list(dict.fromkeys(b.refs))) for b in c.bullets]) for c in output.cards]
        summary.generated=[GeneratedCard(card_id=c.card_id,headline=c.headline,bullets=c.bullets) for c in output.fills]
    await thread(collection(request).replace_one,{'_id':key_for(account,goal)},
        {'_id':key_for(account,goal),'goal_version':goal.version,'research_id':summary.research_id,'summary':jsonable_encoder(summary)},True)
    return summary

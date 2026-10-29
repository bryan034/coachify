"""Transient Gemini presentation; canonical goal and research stay unchanged."""
import json
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError, Operation
from app.ai.contracts import AIInput
from app.ai.routing import chat_models
from app.ai.goal_summary import SUMMARY_CLOSING
from app.repositories.goals import GoalError
from app.workflows.activity import activity
from app.workflows.structured import structured_node
from app.workflows.citations import summary_text, source_links


async def summarize(request, account, body):
    repo = request.app.state.workspace_store

    async def snapshot():
        row = await thread(repo.check, account, body.session_id, body.expected_version)
        w = row['workspace']
        if w.get('phase') not in ('ready','research_failed') or w.get('research_id') != body.research_id:
            raise GoalError('Research changed or is incomplete. Reload your career goal.')
        goal = (await thread(repo.goals.current, account))['goal']
        record = await thread(request.app.state.research_store.read, account, goal.id, body.research_id)
        if not record or not record.intelligence or record.intelligence.status not in ('completed','partial'):
            raise GoalError('Complete opportunity research before preparing the summary.')
        if any(getattr(category,'status',None) in ('pending','running') for category in record.intelligence.categories.values()):
            raise GoalError('Research is still running. Wait before preparing the summary.')
        return goal, record

    goal, record = await snapshot()
    sources = {s.source_id: s.url for s in record.sources}
    references = {}
    research_refs = set()

    def goal_sources(urls):
        identifiers=[]
        for url in urls:
            if not url:continue
            identifier=next((key for key,value in sources.items() if value==url),None)
            if identifier is None:
                identifier='goal_source_'+str(len(sources))
                while identifier in sources:identifier+='_'  # Never collide with stored IDs.
                sources[identifier]=url
            if identifier not in identifiers:identifiers.append(identifier)
        return identifiers

    fields = ('target_type', 'role', 'field', 'company', 'location', 'seniority_level', 'employment_type', 'interests', 'preferences',
              'summary', 'responsibilities', 'skills', 'non_skill_requirements', 'requirements_need_review')
    goal_data=jsonable_encoder({k:getattr(goal,k,None) for k in fields})
    goal_data['reference']='goal'
    references['goal']=goal_sources([getattr(goal,'job_url',None)])
    for field,prefix in (('skills','skill'),('non_skill_requirements','condition')):
        for index,item in enumerate(goal_data.get(field) or []):
            ref=f'{prefix}_{index}';item['reference']=ref
            references[ref]=goal_sources(item.pop('source_urls',[]))
    categories=jsonable_encoder(record.intelligence.categories)
    for name,category in categories.items():
        ref='coverage_'+name;category['reference']=ref;references[ref]=[]
        category.pop('source_ids',None)
        for finding in category.get('findings',[]):
            finding.pop('quotes',None)
            ref='research_'+str(len(research_refs));finding['reference']=ref
            references[ref]=finding.pop('source_ids');research_refs.add(ref)
    context={'goal':goal_data,'categories':categories}

    def validate(output):
        used=set()
        for index,block in enumerate(output.blocks):
            if any(ref not in references for ref in block.references):
                raise AIError('invalid_output',True,reason='provenance',fields=('blocks','references'),
                    violations=({'field':f'blocks.{index}.references','issue':'unknown_fact_reference'},))
            if not block.text.replace(SUMMARY_CLOSING,'').strip():
                raise AIError('invalid_output',True,reason='schema_validation',fields=('blocks','text'),
                    violations=({'field':f'blocks.{index}.text','issue':'empty_summary_point'},))
            used.update(block.references)
        if research_refs and not used.intersection(research_refs):
            raise AIError('invalid_output',True,reason='provenance',fields=('blocks','references'),
                violations=({'field':'blocks','issue':'missing_research_reference'},))

    activity('preparing_summary')
    encoded = json.dumps(jsonable_encoder(context), separators=(',', ':'))
    if len(encoded) > 40000:
        raise AIError('context_limit')
    @structured_node
    async def present(state):
        # Each repair rechecks ownership/version before another paid generation.
        await snapshot()
        result = await chat_models(request.app.state).generate(
            AIInput(stage='goal_summary', context=encoded),
            Operation(account, str(body.expected_version), 'goal_summary'),
            current_revision=lambda: str(body.expected_version), validate_output=validate)
        validate(result.data)
        return result.data

    result = await present({})
    await snapshot()  # A replaced goal/research must never publish a stale overview.
    points=[]
    for block in result.blocks:
        text=summary_text(block.text.replace(SUMMARY_CLOSING,''))
        ids=list(dict.fromkeys(identifier for ref in block.references for identifier in references[ref]))
        citations=source_links(ids,sources)
        point=text+(' '+citations if citations else '')
        points.append('- '+point)
    return {'reply':'## Your career goal\n\n'+'\n\n'.join(points)+'\n\n'+SUMMARY_CLOSING}

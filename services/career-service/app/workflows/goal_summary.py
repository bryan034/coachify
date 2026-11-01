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
from app.workflows.current import workspace_revision
from app.workflows.citations import summary_text, source_links

CATEGORY_LABELS={
    'interview_intelligence':'Interview expectations',
    'internship_insights':'Internship insights',
    'career_progression':'Career progression',
    'conversion_outcomes':'Conversion rates',
    'company_intelligence':'Company culture',
}
FAILURE_EXPLANATIONS={
    'context_limit':'The research request exceeded the model context or token allowance.',
    'invalid_output':'The model response could not be validated.',
    'incomplete_output':'The model response ended before it was complete.',
    'timeout':'The research provider took too long to respond.',
}


def failed_research_summary(goal,record):
    """Explain saved failures without depending on the provider that just failed."""
    sources={s.source_id:s.url for s in record.sources}
    has_findings=any(c.findings for c in record.intelligence.categories.values())
    points=['## Research could not be completed',
            '**Saved goal:** '+summary_text(goal.role),
            '**Findings:** '+('Previously validated findings are retained below.' if has_findings else 'No validated research findings were saved in this report.')]
    for name,category in record.intelligence.categories.items():
        points.append('### '+CATEGORY_LABELS.get(name,'Research category'))
        if category.status=='not_applicable':
            points.append('**Status:** This category does not apply to the saved goal.')
            continue
        for finding in category.findings:
            citations=source_links(finding.source_ids,sources)
            qualifier=' (related context)' if getattr(finding,'scope','exact')!='exact' else ''
            points.append(summary_text(finding.value)+qualifier+(' '+citations if citations else ''))
        explanation=FAILURE_EXPLANATIONS.get(getattr(category,'error_code',None),'The research provider could not complete this category.')
        points.append('**Status:** '+explanation)
    points.extend(['### Next steps','Your career goal remains saved. Use **Resume research** to try again. Context-limit failures may require a smaller research evidence budget or a larger model context allowance.',SUMMARY_CLOSING])
    return {'reply':'\n\n'.join(points)}


def saved_evidence_summary(goal,record):
    """Present validated saved evidence; never reuse rejected model wording."""
    def cited(text,urls):
        links={str(index):url for index,url in enumerate(urls) if url}
        citations=source_links(links,links)
        return text+(' '+citations if citations else '')
    goal_urls=[getattr(goal,'job_url',None)]
    points=['## Your career goal',cited('**Role:** '+summary_text(goal.role),goal_urls),
            '**Overview:** Showing saved facts because the AI-written overview could not be prepared.']
    for field,label in (('company','Company'),('field','Field'),('location','Location')):
        value=getattr(goal,field,None)
        if value:points.append(cited('**'+label+':** '+summary_text(value),goal_urls))
    for priority,label in (('required','Required skills'),('preferred','Preferred skills')):
        skills=[skill for skill in getattr(goal,'skills',[]) or [] if skill.priority==priority]
        if skills:
            selected=skills[:10]
            points.append(cited('**'+label+':** '+summary_text(', '.join(skill.name for skill in selected)),
                [url for skill in selected for url in getattr(skill,'source_urls',[])]))
            if len(skills)>10:points.append('More skills are available in **Role and research details**.')
    if getattr(goal,'requirements_need_review',False):
        points.append('**Requirements:** Your goal changed; review its saved requirements.')
    sources={s.source_id:s.url for s in record.sources}
    points.append('## Research findings')
    for name,category in record.intelligence.categories.items():
        points.append('### '+CATEGORY_LABELS.get(name,'Research category'))
        findings=[finding for finding in category.findings if getattr(finding,'value',None)]
        for finding in findings[:2]:
            qualifiers=[]
            if getattr(finding,'scope','exact')!='exact':qualifiers.append('related context')
            if getattr(finding,'confidence',None):qualifiers.append(finding.confidence.replace('_',' ')+' confidence')
            citations=source_links(finding.source_ids,sources)
            points.append('- '+summary_text(finding.value)+(' ('+', '.join(qualifiers)+')' if qualifiers else '')+(' '+citations if citations else ''))
        if len(findings)>2:points.append('More findings are available in **Role and research details**.')
        if category.status in ('failed','partial'):
            points.append('**Coverage:** '+FAILURE_EXPLANATIONS.get(getattr(category,'error_code',None),'Research coverage is incomplete for this category.'))
        elif category.status=='not_applicable':points.append('**Coverage:** This category does not apply to the saved goal.')
        elif not findings:points.append('**Coverage:** No supported findings were found in the retrieved sources.')
        missing=getattr(category,'missing_fields',[])
        if missing:points.append('**Missing information:** '+summary_text(', '.join(field.replace('_',' ') for field in missing))+'.')
    points.append(SUMMARY_CLOSING)
    return {'reply':'\n\n'.join(points)}


async def summarize(request, account, body):
    repo = request.app.state.workspace_store

    async def snapshot():
        row = await thread(repo.check, account, body.session_id, body.expected_version)
        w = row['workspace']
        if w.get('phase') not in ('ready','research_failed') or w.get('research_id') != body.research_id:
            raise GoalError('Research changed or is incomplete. Reload your career goal.')
        goal = (await thread(repo.goals.current, account))['goal']
        record = await thread(request.app.state.research_store.read, account, goal.id, body.research_id, current=True, goal_version=goal.version)
        if not record or not record.intelligence or record.intelligence.status not in ('completed','partial','failed'):
            raise GoalError('Complete opportunity research before preparing the summary.')
        if any(getattr(category,'status',None) in ('pending','running') for category in record.intelligence.categories.values()):
            raise GoalError('Research is still running. Wait before preparing the summary.')
        return goal, record

    goal, record = await snapshot()
    if record.intelligence.status=='failed':
        result=failed_research_summary(goal,record)
        await snapshot()
        return result
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
        await snapshot()
        return saved_evidence_summary(goal,record)
    @structured_node
    async def present(state):
        # Each repair rechecks ownership/version before another paid generation.
        await snapshot()
        result = await chat_models(request.app.state).generate(
            AIInput(stage='goal_summary', context=encoded),
            Operation(account, str(body.expected_version), 'goal_summary'),
            current_revision=workspace_revision(repo,account,body.session_id,body.expected_version), validate_output=validate)
        validate(result.data)
        return result.data

    try:
        result = await present({})
    except AIError as error:
        if error.code not in ('invalid_output','incomplete_output','context_limit'):raise
        await snapshot()
        return saved_evidence_summary(goal,record)
    await snapshot()  # A replaced goal/research must never publish a stale overview.
    points=[]
    research_heading=False
    for block in result.blocks:
        if not research_heading and any(ref.startswith(('research_','coverage_')) for ref in block.references):
            points.append('### Research findings')
            research_heading=True
        text=summary_text(block.text.replace(SUMMARY_CLOSING,''))
        ids=list(dict.fromkeys(identifier for ref in block.references for identifier in references[ref]))
        citations=source_links(ids,sources)
        point=text+(' '+citations if citations else '')
        points.append('**'+block.label+':** '+point)
    return {'reply':'## Your career goal\n\n'+'\n\n'.join(points)+'\n\n'+SUMMARY_CLOSING}

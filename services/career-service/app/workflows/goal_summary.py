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
from app.workflows.citations import normalize_citations, render_citations, citation_error


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
    # Exclude private owner/operational metadata and original source excerpts.
    fields = ('target_type', 'role', 'field', 'company', 'location', 'seniority_level', 'employment_type', 'interests', 'preferences',
              'summary', 'responsibilities', 'skills', 'non_skill_requirements', 'requirements_need_review')
    # Summarise validated values, not the repeated original evidence quotations.
    categories=jsonable_encoder(record.intelligence.categories)
    for category in categories.values():
        for finding in category.get('findings',[]):
            finding.pop('quotes',None)
    context = {'goal': {k: getattr(goal, k, None) for k in fields},
               'categories': categories, 'source_ids': list(sources)}

    def validate(output):
        _, cited = normalize_citations(output.reply, sources)
        # A concise overview selects key findings rather than reproducing them all.
        if any(category.findings for category in record.intelligence.categories.values()) and not cited:
            raise citation_error('missing_finding_citation')

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
    normalized, _ = normalize_citations(result.reply, sources)
    reply = render_citations(normalized, sources)
    reply=reply.replace(SUMMARY_CLOSING,'').strip()+'\n\n'+SUMMARY_CLOSING
    return {'reply': reply}

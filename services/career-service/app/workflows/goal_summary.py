"""Transient Gemini presentation; canonical goal and research stay unchanged."""
import json
import re
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError, Operation
from app.ai.contracts import AIInput
from app.ai.routing import chat_models
from app.repositories.goals import GoalError
from app.workflows.activity import activity


async def summarize(request, account, body):
    repo = request.app.state.workspace_store

    async def snapshot():
        row = await thread(repo.check, account, body.session_id, body.expected_version)
        w = row['workspace']
        if w.get('phase') != 'ready' or w.get('research_id') != body.research_id:
            raise GoalError('Research changed or is incomplete. Reload your career goal.')
        goal = (await thread(repo.goals.current, account))['goal']
        record = await thread(request.app.state.research_store.read, account, goal.id, body.research_id)
        if not record or not record.intelligence or record.intelligence.status != 'completed':
            raise GoalError('Complete opportunity research before preparing the summary.')
        return goal, record

    goal, record = await snapshot()
    sources = {s.source_id: s.url for s in record.sources}
    # Exclude private owner/operational metadata and original source excerpts.
    fields = ('target_type', 'role', 'field', 'company', 'location', 'seniority_level', 'employment_type', 'interests', 'preferences',
              'summary', 'responsibilities', 'skills', 'non_skill_requirements', 'requirements_need_review')
    context = {'goal': {k: getattr(goal, k, None) for k in fields},
               'categories': record.intelligence.categories, 'source_ids': list(sources)}

    def validate(output):
        refs = re.findall(r'\[([^\]\n]+)\]', output.reply)
        if any(ref not in sources for ref in refs) or re.search(r'https?://|\]\(', output.reply):
            raise AIError('invalid_output', True, reason='provenance', fields=('reply',))
        cited = set(refs)
        required = {sid for category in record.intelligence.categories.values()
                    for finding in category.findings for sid in finding.source_ids}
        if not required <= cited:
            raise AIError('invalid_output', True, reason='provenance', fields=('reply',))

    activity('preparing_summary')
    encoded = json.dumps(jsonable_encoder(context), separators=(',', ':'))
    if len(encoded) > 40000:
        raise AIError('context_limit')
    result = await chat_models(request.app.state).generate(
        AIInput(stage='goal_summary', context=encoded),
        Operation(account, str(body.expected_version), 'goal_summary'),
        current_revision=lambda: str(body.expected_version), validate_output=validate)
    validate(result.data)
    await snapshot()  # A replaced goal/research must never publish a stale overview.
    reply = re.sub(r'\[([^\]\n]+)\]', lambda m: f'[Source]({sources[m[1]]})', result.data.reply)
    return {'reply': reply}

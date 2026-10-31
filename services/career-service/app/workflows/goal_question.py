"""Focused, public-only Brave retrieval for a Gemini-selected goal question."""
import asyncio
from app.schemas.analysis import ResearchContext
from app.clients.research import normalize_sources
from app.repositories.goals import GoalError
from app.workflows.activity import activity
from app.clients.search_sources import SourceRateLimit
from app.ai.waiting import quota_progress, quota_reason

FOCUSES = {
    'location': 'work location office internship location remote hybrid',
    'compensation': 'salary compensation benefits',
    'eligibility': 'eligibility qualifications work authorization',
    'dates': 'application deadline internship start date duration',
    'role_details': 'job responsibilities requirements',
    'interviews': 'interview process candidate experience',
    'workplace': 'team culture internship mentorship experience',
    'career_progression': 'career progression full time conversion salary',
    'conversion': 'internship full time conversion rate historical outcomes',
}


async def research_question(request, title, focus, check):
    provider = request.app.state.research_client
    collect = getattr(provider, 'collect_query', None)
    if not callable(collect):
        raise GoalError('Public research is unavailable. Your saved goal remains available.', 503)
    context = ResearchContext(**{key: title.get(key) for key in
        ('role', 'field', 'company', 'location', 'seniority_level')})
    # Only saved public identity + a fixed Gemini-selected focus reach Brave.
    # User messages, conversation and CV data never enter the query.
    query = ' '.join(filter(None, (context.company, context.role, context.location, FOCUSES[focus])))[:400]
    await check()
    activity('searching_question')
    for attempt in range(4):
        try:
            sources = normalize_sources(await collect(context, query))[:6]
            break
        except SourceRateLimit as error:
            observer = quota_progress.get()
            if observer is None or attempt == 3:
                raise
            token = quota_reason.set({'provider': error.provider, 'limit_scope': 'provider'})
            try:
                observer(error.retry_after)
                waiting = error.retry_after
                while waiting > 0:
                    pause = min(5, waiting)
                    await asyncio.sleep(pause)
                    await check()
                    waiting -= pause
            finally:
                observer(None)
                quota_reason.reset(token)
    await check()
    facts = [{'ref': f'web{i}', 'kind': 'public_source',
              'data': {'title': source.title, 'evidence': source.evidence,
                       'scope': 'Public source; verify exact role, location and dates.'}}
             for i, source in enumerate(sources) if source.evidence]
    links = {f'web{i}': [source.model_dump(mode='json')] for i, source in enumerate(sources) if source.evidence}
    return facts, links

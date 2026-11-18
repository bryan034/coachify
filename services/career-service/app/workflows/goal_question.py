"""Focused, public-only Brave retrieval for a model-selected goal question."""
import asyncio
import re
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


MAX_QUESTION_SEARCHES = 3


def question_queries(title, focus, terms=None):
    # Only a bounded public subject produced by the router crosses the search boundary.
    # Raw messages, history and resolved_question never become search queries.
    from app.domain.questions import blocked_task
    if terms:
        if not re.fullmatch(r'[A-Za-z][A-Za-z -]{2,99}', terms) or blocked_task(terms) or re.search(
                r'\b(?:my|email|phone|password|secret|passport|address|resume|cv)\b', terms, re.I):
            terms=None
    subject=terms or FOCUSES[focus]
    from app.domain.source_scope import SINGAPORE,target_place
    # Keep the market in every query: Brave has no Singapore country filter and
    # DeepSeek has none at all, so the query text is the only geographic anchor.
    parts=[str(title.get(key) or '').strip() for key in ('company','role','location')]
    if target_place(title)==SINGAPORE and not any(re.search(r'\bsingapore\b',part,re.I) for part in parts):
        parts.append('Singapore')
    market=' '.join(part for part in parts[2:] if part)
    prefix=' '.join(part for part in parts[:2] if part)
    # Reserve space for the market before bounding the employer/role prefix.
    identity=' '.join(part for part in (prefix[:max(0,239-len(market))],market) if part)
    # Later searches narrow towards employer-published and local sources rather than
    # broadening to global candidate reports.
    local={'compensation':'SGD per month','location':'office address'}.get(focus,'employee reviews')
    suffixes=('', 'official careers', local)
    return list(dict.fromkeys(' '.join((identity,subject,suffix)).strip() for suffix in suffixes))[:MAX_QUESTION_SEARCHES]


async def research_question(request, title, focus, check, *, query=None):
    provider = request.app.state.research_client
    collect = getattr(provider, 'collect_query', None)
    if not callable(collect):
        raise GoalError('Public research is unavailable. Your saved goal remains available.', 503)
    context = ResearchContext(**{key: title.get(key) for key in
        ('role', 'field', 'company', 'location', 'seniority_level')})
    query = query or question_queries(title,focus)[0]
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
                       'scope': 'Public source; verify exact employer, role, Singapore location and dates.'}}
             for i, source in enumerate(sources) if source.evidence]
    links = {f'web{i}': [source.model_dump(mode='json')] for i, source in enumerate(sources) if source.evidence}
    return facts, links

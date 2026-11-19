"""Focused, public-only retrieval for a model-selected goal question."""
import asyncio
import re
from app.schemas.analysis import ResearchContext
from app.clients.research import normalize_sources
from app.repositories.goals import GoalError
from app.workflows.activity import activity
from app.clients.search_sources import SourceRateLimit, SearchAllowanceExceeded
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
    from app.domain.questions import blocked_task
    if terms:
        if not re.fullmatch(r'[A-Za-z][A-Za-z -]{2,99}', terms) or blocked_task(terms) or re.search(
                r'\b(?:my|email|phone|password|secret|passport|address|resume|cv)\b', terms, re.I):
            terms=None
    subject=terms or FOCUSES[focus]
    from app.domain.source_scope import SINGAPORE,target_place
    company,role=(str(title.get(key) or '').strip() for key in ('company','role'))
    place=target_place(title)
    market='Singapore' if place==SINGAPORE else place
    def query(place, suffix=''):
        # Keep queries within 128 characters without truncating the market or subject.
        tail=' '.join(part for part in (subject,suffix) if part)
        place=place[:max(0,126-len(tail))].strip()
        budget=max(0,127-len(tail)-(len(place)+1 if place else 0))
        role_prefix=role[:budget].strip()
        company_prefix=company[:max(0,budget-len(role_prefix)-bool(role_prefix))].strip()
        return ' '.join(part for part in (company_prefix,role_prefix,place,tail) if part)
    related=title.get('related_locations') or []
    queries=(query(market),query(related[0] if related else ''),query(market,'official careers'))
    return list(dict.fromkeys(' '.join(query.split()) for query in queries))[:MAX_QUESTION_SEARCHES]


async def research_question(request, title, focus, check, *, query=None):
    provider = request.app.state.research_client
    collect = getattr(provider, 'collect_question_query', None) or getattr(provider, 'collect_query', None)
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
        except SearchAllowanceExceeded:
            raise
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
                       'scope': 'Public source; verify exact employer, role, location and dates.'}}
             for i, source in enumerate(sources) if source.evidence]
    links = {f'web{i}': [source.model_dump(mode='json')] for i, source in enumerate(sources) if source.evidence}
    return facts, links

"""Per-topic research policy: each researched field searches, stops and keeps sources by its own rules."""
from dataclasses import dataclass
from urllib.parse import urlsplit
from app.schemas.opportunity import CATEGORIES,FIELDS


@dataclass(frozen=True)
class Policy:
    urls_per_search:int
    max_urls:int
    keep:int
    backing_sites:int


# urls_per_search and max_urls count pages actually read after triage, not search results.
FACTUAL=Policy(urls_per_search=2,max_urls=5,keep=2,backing_sites=2)
REVIEWS=Policy(urls_per_search=4,max_urls=8,keep=4,backing_sites=4)
# Search results whose title, URL, date and preview are triaged before any page is read.
CANDIDATES_PER_SEARCH=6

FACTUAL_TOPICS=frozenset({'compensation','benefits','conversion_salary','conversion_rate','historical_cohort',
    'offer_acceptance','full_time_role','application_timeline','recruitment_stages'})

TOPICS=tuple(dict.fromkeys(field for category in CATEGORIES for field in FIELDS[category]))
TOPIC_CATEGORIES={topic:tuple(c for c in CATEGORIES if topic in FIELDS[c]) for topic in TOPICS}

# What a person would type after the employer and role.
TERMS={
 'recruitment_stages':'interview process stages rounds','interview_questions':'interview questions asked',
 'difficulty':'interview difficulty','application_timeline':'application deadline timeline',
 'preparation_topics':'interview preparation topics','candidate_experience':'interview experience reddit',
 'round_format':'interview round format','compensation':'intern salary per month','benefits':'intern benefits perks',
 'projects':'intern projects work','mentorship':'intern mentorship','work_life_balance':'work life balance hours',
 'full_time_role':'return offer full time role','career_path':'career progression after internship',
 'conversion_salary':'graduate salary full time','conversion_rate':'intern return offer conversion rate',
 'historical_cohort':'internship intake cohort size','offer_acceptance':'return offers accepted',
 'company_culture':'company culture reviews','team_culture':'team culture','management':'management reviews'}
ALTERNATE={
 'compensation':'intern salary glassdoor','conversion_salary':'graduate salary glassdoor levels.fyi',
 'conversion_rate':'return offer rate reddit','benefits':'intern benefits glassdoor',
 'company_culture':'culture reddit glassdoor','team_culture':'team reviews reddit','management':'manager reviews glassdoor',
 'work_life_balance':'hours overtime reddit','mentorship':'intern mentor reddit','candidate_experience':'interview glassdoor',
 'interview_questions':'interview questions glassdoor reddit'}

def policy(topic):
    return FACTUAL if topic in FACTUAL_TOPICS else REVIEWS


def owner(topic):
    """The first category listing a shared topic runs its searches; the others reuse what it reads."""
    return TOPIC_CATEGORIES[topic][0]


def category_topics(category):
    return [topic for topic in FIELDS[category] if owner(topic)==category]


def topic_query(public,topic,attempt=0):
    """A plain employer-and-role search for one topic; a second attempt targets review and salary sites."""
    if not public:return None
    who=' '.join(' '.join((public.get(key) or '').split()) for key in ('company','role')).strip()
    if not who:return None
    terms=ALTERNATE.get(topic,TERMS[topic]) if attempt else TERMS[topic]
    return f'{who[:140]} {terms}'


def site(url):
    host=(urlsplit(url or '').hostname or '').casefold()
    return host[4:] if host.startswith('www.') else host


def backing_sites(topic,findings,sources):
    """Distinct sites behind one topic's findings; a conflict leaves the value unsettled."""
    urls={s.source_id:s.url for s in sources}
    own=[f for f in findings if f.field==topic]
    if any(f.conflict_group for f in own):return set()
    return {site(urls[sid]) for f in own for sid in f.source_ids if sid in urls}


def settled(topic,findings,sources):
    return len(backing_sites(topic,findings,sources))>=policy(topic).backing_sites

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
GROUP_CANDIDATES=10

FACTUAL_TOPICS=frozenset({'compensation','benefits','conversion_salary','conversion_rate','historical_cohort',
    'offer_acceptance','full_time_role','application_timeline','recruitment_stages'})

TOPICS=tuple(dict.fromkeys(field for category in CATEGORIES for field in FIELDS[category]))
TOPIC_CATEGORIES={topic:tuple(c for c in CATEGORIES if topic in FIELDS[c]) for topic in TOPICS}

GROUPS={
 'interview_process':('recruitment_stages','round_format','application_timeline','difficulty'),
 'interview_content':('interview_questions','preparation_topics','candidate_experience'),
 'pay':('compensation','benefits','conversion_salary'),
 'intern_experience':('projects','mentorship','work_life_balance'),
 'conversion':('full_time_role','conversion_rate','historical_cohort','offer_acceptance'),
 'career':('career_path',),
 'culture':('company_culture','team_culture','management'),
}
TOPIC_GROUP={topic:group for group,topics in GROUPS.items() for topic in topics}
GROUP_TERMS={
 'interview_process':'interview process rounds timeline','interview_content':'interview questions experience',
 'pay':'intern salary benefits graduate pay','intern_experience':'intern experience projects mentorship',
 'conversion':'return offer conversion intern intake','career':'career path graduate programme progression',
 'culture':'company culture management reviews'}

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
 'interview_questions':'interview questions glassdoor reddit','recruitment_stages':'interview process glassdoor reddit',
 'difficulty':'interview difficulty glassdoor','application_timeline':'application timeline reddit',
 'preparation_topics':'interview preparation reddit','round_format':'interview rounds format glassdoor',
 'projects':'intern projects reddit','full_time_role':'return offer reddit','career_path':'career progression reddit glassdoor',
 'historical_cohort':'number of interns intake reddit','offer_acceptance':'return offer accepted reddit'}

def policy(topic):
    return FACTUAL if topic in FACTUAL_TOPICS else REVIEWS


def owner(topic):
    """The first category listing a shared topic runs its searches; the others reuse what it reads."""
    return TOPIC_CATEGORIES[topic][0]


def category_topics(category):
    return [topic for topic in FIELDS[category] if owner(topic)==category]


def employer_role(public):
    if not public:return ''
    return ' '.join(' '.join((public.get(key) or '').split()) for key in ('company','role')).strip()[:140]


def topic_query(public,topic,attempt=0):
    """A plain employer-and-role search for one topic; a second attempt targets review and salary sites."""
    who=employer_role(public)
    if not who:return None
    terms=ALTERNATE.get(topic,TERMS[topic]) if attempt else TERMS[topic]
    return f'{who} {terms}'


def group_query(public,group):
    who=employer_role(public)
    return f'{who} {GROUP_TERMS[group]}' if who else None


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


def gap_rank(topic,findings):
    return (topic not in FACTUAL_TOPICS,any(f.field==topic for f in findings))

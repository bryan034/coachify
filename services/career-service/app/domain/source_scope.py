"""Deterministic scope checks for public question evidence.

A passage is *verified* only when every check passes: it names the target market
(Singapore unless the goal states another location) and no other country, currency
or foreign site; it names the saved employer; it contains each core role word; it
addresses the question focus (a salary needs an actual amount) and the router's
search subject; and it is not stale. Only verified passages may be saved as job
facts. Passages with any foreign signal are rejected before a model sees them.
Everything else is an unverified candidate that may inform an answer but is never
saved. Checks are lexical and conservative: a missed match costs recall, never
correctness.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

SINGAPORE = 'singapore'
MAX_AGE_DAYS = 3 * 365

LOCAL = re.compile(r'\bsingapore(?:an)?\b|\bSGD\b|\bS\$|\bSG\$', re.I)
# Currencies other than SGD. Bare "$" stays neutral: Singapore postings use it too.
FOREIGN_CURRENCY = re.compile(
    r'\b(?:AUD|USD|GBP|EUR|INR|MYR|HKD|NZD|CAD|IDR|CNY|RMB|JPY|KRW|THB|VND|AED|CHF)\b'
    r'|(?:\bA|\bAU|\bUS|\bHK|\bNZ|\bC|\bCA|\bNT)\$|£|€|₹|¥|₩|₱|\bRM\s?\d|\bRs\.?\s?\d|\bRp\.?\s?\d', re.I)
FOREIGN_PLACE = re.compile(r'\b(?:' + '|'.join([
    'australia', 'australian', 'sydney', 'melbourne', 'brisbane', 'perth', 'adelaide', 'canberra',
    'new zealand', 'auckland', 'wellington', 'united states', 'usa', 'america', 'new york',
    'san francisco', 'seattle', 'california', 'texas', 'boston', 'chicago', 'canada', 'canadian', 'toronto',
    'vancouver', 'united kingdom', 'britain', 'british', 'england', 'london', 'manchester', 'ireland',
    'dublin', 'india', 'indian', 'bangalore', 'bengaluru', 'mumbai', 'delhi', 'hyderabad', 'pune',
    'chennai', 'malaysia', 'malaysian', 'kuala lumpur', 'penang', 'johor', 'indonesia', 'jakarta',
    'philippines', 'manila', 'vietnam', 'ho chi minh', 'hanoi', 'thailand', 'bangkok', 'hong kong',
    'china', 'chinese mainland', 'shanghai', 'beijing', 'shenzhen', 'taiwan', 'taipei', 'japan', 'tokyo',
    'korea', 'seoul', 'dubai', 'germany', 'berlin', 'france', 'paris', 'netherlands', 'amsterdam',
]) + r')\b', re.I)
FOREIGN_TLDS = frozenset('au uk in my hk ca nz ph id cn jp kr tw th vn ae de fr nl ie us za'.split())
# Two-letter country subdomains used by global job boards, e.g. au.indeed.com.
FOREIGN_SUBDOMAINS = FOREIGN_TLDS | {'gb', 'en-au', 'en-gb', 'en-in'}

COMPANY_SUFFIXES = {'pte', 'ltd', 'limited', 'inc', 'incorporated', 'corp', 'corporation', 'co',
                    'company', 'group', 'holdings', 'plc', 'llc', 'private', 'singapore', 'sg', 'the'}
ROLE_FILLER = {'the', 'and', 'of', 'for', 'in', 'at', 'to', 'a', 'an', 'with', 'i', 'ii', 'iii', 'iv',
               'senior', 'junior', 'lead', 'principal', 'staff', 'associate', 'assistant', 'summer',
               'winter', 'spring', 'autumn', 'fall', 'programme', 'program', 'role', 'position', 'job'}
INTERN = re.compile(r'\b(?:intern|interns|internship|internships|trainee|traineeship|attachment)\b', re.I)
TERM_FILLER = ROLE_FILLER | {'intern', 'interns', 'internship', 'company', 'employer', 'official',
                             'information', 'details', 'detail', 'singapore', 'job', 'work', 'working'}

AMOUNT = re.compile(r'(?:SGD|S\$|SG\$|\$)\s?\d|\d[\d,.]*\s?(?:k\b|SGD\b)'
                    r'|\d[\d,]*\s*(?:per|/|a|an)\s*(?:month|mth|hour|hr|week|year|annum)|\d[\d,]*\s*(?:monthly|hourly)\b', re.I)
TOPIC = {
    'compensation': r'\b(salary|salaries|stipend|allowance|compensation|pay|paid|remuneration|wages?|earns?|earning)\b',
    'location': r'\b(office|located|location|based|address|remote|hybrid|on-?site|work from)\b',
    'eligibility': r'\b(eligib\w*|qualifications?|degree|diploma|citizen\w*|permanent resident|work pass|requirements?)\b',
    'dates': r'\b(deadline|start date|duration|closing|intake|weeks?|months?)\b',
    'role_details': r'\b(responsibilit\w*|requirements?|skills?|duties|you will)\b',
    'interviews': r'\b(interview\w*|assessments?|screening|coding test|online test|rounds?)\b',
    'workplace': r'\b(culture|team|mentors?\w*|hours|overtime|balance|projects?|management|benefits?)\b',
    'career_progression': r'\b(career|progression|graduate|full.time|return offer|promotion)\b',
    'conversion': r'\b(conversion|convert\w*|return offers?|full.time offer|cohort)\b',
}


@dataclass
class Verdict:
    verified: bool
    foreign: bool
    official: bool = False
    reasons: list[str] = field(default_factory=list)


def host(url):
    return (urlsplit(url or '').hostname or '').casefold().removeprefix('www.')


def target_place(goal):
    """Singapore is the default market; another saved location becomes the anchor."""
    location = ' '.join(str((goal or {}).get('location') or '').split())
    if not location or re.search(r'\b(?:singapore|sg)\b', location, re.I):
        return SINGAPORE
    if re.fullmatch(r'(?i)(?:remote|hybrid|on-?site|flexible)', location):
        return SINGAPORE
    return re.split(r'[,(/|-]', location)[0].strip().casefold() or SINGAPORE


def foreign_host(name):
    labels = name.split('.')
    if len(labels) >= 2 and labels[-1] in FOREIGN_TLDS:
        return True
    return len(labels) >= 3 and labels[0] in FOREIGN_SUBDOMAINS


def foreign_text(text, place=SINGAPORE):
    """Any other-country currency or place name. Only defined for Singapore goals."""
    return place == SINGAPORE and bool(FOREIGN_CURRENCY.search(text or '') or FOREIGN_PLACE.search(text or ''))


def foreign_source(url, title, passage, goal):
    place = target_place(goal)
    if place != SINGAPORE:
        return False
    return foreign_host(host(url)) or foreign_text(title, place) or foreign_text(passage, place)


def local(url, title, text, place):
    name = host(url)
    if place == SINGAPORE:
        return name.endswith('.sg') or name.startswith('sg.') or bool(LOCAL.search(text) or LOCAL.search(title or ''))
    return bool(re.search(r'\b' + re.escape(place) + r'\b', f'{title or ""} {text}', re.I))


def company_words(company):
    words = [w for w in re.findall(r'[a-z0-9]+', (company or '').casefold().replace('&', ' and '))]
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    while words and words[0] == 'the':
        words.pop(0)
    return words


def employer_match(company, url, title, text):
    words = company_words(company)
    if not words:
        return False, False
    phrase = r'\b' + r'[\s.&-]*'.join(map(re.escape, words)) + r'\b'
    compact = ''.join(words)
    name = host(url)
    # A matching subdomain or prefix does not establish employer ownership.
    official = len(compact) >= 3 and name in {
        compact + suffix for suffix in ('.com', '.sg', '.com.sg', '.careers', '.io')
    }
    return official or bool(re.search(phrase, f'{title or ""} {text}', re.I)), official


def role_words(role):
    role = re.sub(r'\([^)]*\)', ' ', role or '')
    return [w for w in re.findall(r'[a-z][a-z+#.]*', role.casefold()) if w not in ROLE_FILLER and not INTERN.fullmatch(w)]


def stem(word):
    return word[:5] if len(word) > 5 else word


def role_match(role, title, text):
    combined = f'{title or ""} {text}'.casefold()
    if INTERN.search(role or '') and not INTERN.search(combined):
        return False
    words = role_words(role)
    return bool(words or INTERN.search(role or '')) and all(
        re.search(r'\b' + re.escape(stem(w)), combined) for w in words)


def term_words(terms, goal):
    known = set(company_words((goal or {}).get('company'))) | set(role_words((goal or {}).get('role')))
    return [w for w in re.findall(r'[a-z]{4,}', (terms or '').casefold()) if w not in TERM_FILLER and w not in known]


def verify(focus, url, title, passage, goal, *, terms=None, published=None, today=None, scope_only=False):
    """Return the verdict for one exact passage. Every check must pass to verify.

    scope_only re-checks market, employer, role and age without question relevance,
    which depends on the router's search subject and is decided at retrieval.
    """
    goal = goal or {}
    text = passage or ''
    place = target_place(goal)
    reasons = []
    if foreign_source(url, title, text, goal):
        return Verdict(False, True, reasons=['foreign'])
    if not local(url, title, text, place):
        reasons.append('location')
    # A goal without a saved employer is a general role; there is no employer to match.
    matched, official = employer_match(goal.get('company'), url, title, text) if company_words(goal.get('company')) else (True, False)
    if not matched:
        reasons.append('employer')
    if not role_match(goal.get('role'), title, text):
        reasons.append('role')
    words = term_words(terms, goal)
    asked = bool(words) and any(re.search(r'\b' + re.escape(stem(w)), text, re.I) for w in words)
    if words and not asked and not scope_only:
        reasons.append('question')
    # The router's specific subject (e.g. "housing allowance") satisfies the topic;
    # without one, the focus vocabulary must match. Salaries always need an amount.
    pattern = TOPIC.get(focus)
    if not scope_only and (not (asked or (pattern and re.search(pattern, text, re.I))) or (focus == 'compensation' and not AMOUNT.search(text))):
        reasons.append('topic')
    if published and ((today or date.today()) - published).days > MAX_AGE_DAYS:
        reasons.append('stale')
    official = official or host(url).endswith('.gov.sg')
    return Verdict(not reasons, False, official, reasons)

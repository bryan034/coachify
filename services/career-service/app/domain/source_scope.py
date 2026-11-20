"""Scope checks for public question evidence.

A passage is *verified* only when every check passes: the passage-scope model labels it as
describing the target market (Singapore unless the goal states another location) and as
stating the asked detail (a salary needs an actual amount); it names the saved employer,
contains each core role word and the router's search subject; and it is not stale. Only
verified passages may be saved as job facts. Everything else is an unverified candidate
that may inform an answer, labelled with its market, but is never saved.
"""
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

MIN_EMPLOYER_NAME = 3
STEM_CHARS = 5

SINGAPORE = 'singapore'
MAX_AGE_DAYS = 3 * 365

COMPANY_SUFFIXES = {'pte', 'ltd', 'limited', 'inc', 'incorporated', 'corp', 'corporation', 'co',
                    'company', 'group', 'holdings', 'plc', 'llc', 'private', 'singapore', 'sg', 'the'}
ROLE_FILLER = {'the', 'and', 'of', 'for', 'in', 'at', 'to', 'a', 'an', 'with', 'i', 'ii', 'iii', 'iv',
               'senior', 'junior', 'lead', 'principal', 'staff', 'associate', 'assistant', 'summer',
               'winter', 'spring', 'autumn', 'fall', 'programme', 'program', 'role', 'position', 'job'}
# Currency markers by structure: any Unicode currency symbol (S$, US$, £, ₹...), or an ISO-style
# three-letter code written directly beside the amount (SGD 1,500 or 1,500 AUD).
CURRENCY_SYMBOLS = ''.join(chr(c) for c in range(sys.maxunicode + 1) if unicodedata.category(chr(c)) == 'Sc')
AMOUNT = r'\d+(?:[,.]\d+)*(?:[kKmM]\b)?'
MARKER = r'(?:\b[A-Z]{1,3})?[' + re.escape(CURRENCY_SYMBOLS) + r']|\b[A-Z]{3}(?=\s?\d)'
MONEY = re.compile(r'(' + MARKER + r')\s?(' + AMOUNT + r')|(' + AMOUNT + r')\s?(\b[A-Z]{3}\b)')
INTERN = re.compile(r'\b(?:intern|interns|internship|internships|trainee|traineeship|attachment)\b', re.I)
TERM_FILLER = ROLE_FILLER | {'intern', 'interns', 'internship', 'company', 'employer', 'official',
                             'information', 'details', 'detail', 'singapore', 'job', 'work', 'working'}


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
    location = re.split(r'\s*[(/,-]?\s*\bbased (?:in|out of)\b', location, maxsplit=1, flags=re.I)[0].strip()
    if not location or re.search(r'\b(?:singapore|sg)\b', location, re.I):
        return SINGAPORE
    if re.fullmatch(r'(?i)(?:remote|hybrid|on-?site|flexible)', location):
        return SINGAPORE
    return re.split(r'[,(/|-]', location)[0].strip().casefold() or SINGAPORE


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
    official = len(compact) >= MIN_EMPLOYER_NAME and name in {
        compact + suffix for suffix in ('.com', '.sg', '.com.sg', '.careers', '.io')
    }
    return official or bool(re.search(phrase, f'{title or ""} {text}', re.I)), official


def role_words(role):
    role = re.sub(r'\([^)]*\)', ' ', role or '')
    return [w for w in re.findall(r'[a-z][a-z+#.]*', role.casefold()) if w not in ROLE_FILLER and not INTERN.fullmatch(w)]


def stem(word):
    return word[:STEM_CHARS]


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


def verify(url, title, passage, goal, *, scope=None, terms=None, published=None, today=None):
    """Return the verdict for one exact passage. Every check must pass to verify.

    Without a model label (a saved passage re-checked against the current goal) only the
    employer, role and age checks run; market, detail and search subject were checked at retrieval.
    """
    goal = goal or {}
    text = passage or ''
    reasons = []
    if scope is not None and scope.market == 'other':
        return Verdict(False, True, reasons=['foreign'])
    if scope is not None and scope.market != 'target':
        reasons.append('location')
    # A goal without a saved employer is a general role; there is no employer to match.
    matched, official = employer_match(goal.get('company'), url, title, text) if company_words(goal.get('company')) else (True, False)
    if not matched:
        reasons.append('employer')
    if not role_match(goal.get('role'), title, text):
        reasons.append('role')
    if scope is not None:
        words = term_words(terms, goal)
        if words and not any(re.search(r'\b' + re.escape(stem(w)), text, re.I) for w in words):
            reasons.append('question')
        if not scope.states_detail:
            reasons.append('topic')
    if published and ((today or date.today()) - published).days > MAX_AGE_DAYS:
        reasons.append('stale')
    official = official or host(url).endswith('.gov.sg')
    return Verdict(not reasons, False, official, reasons)


def money_figures(text):
    """(currency marker, amount) pairs written in the text, with thousands separators removed."""
    figures = set()
    for match in MONEY.finditer(text or ''):
        marker, amount = (match[1], match[2]) if match[1] else (match[4], match[3])
        figures.add((marker.casefold(), re.sub(r'(?<=\d),(?=\d{3})', '', amount.casefold())))
    return figures

"""Turn untrusted provider records into bounded catalogue fields.

The catalogue keeps an excerpt and an unordered term index, not the employer's full description.
"""
import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EXCERPT_LENGTH = 280
MAX_TERMS = 3000
MAX_TERM_LENGTH = 40
MAX_DESCRIPTION_CHARACTERS = 200_000

SINGAPORE = re.compile(r'\bsingapore\b', re.I)
INTERNSHIP = re.compile(r'\b(interns?|internships?|trainee|industrial attachment)\b', re.I)
GRADUATE = re.compile(r'\b(graduate|new grad|fresh grad|early career)\b', re.I)
EMPLOYMENT = (
    ('temporary', re.compile(r'\b(temporary|temp|fixed[- ]term)\b', re.I)),
    ('contract', re.compile(r'\b(contract|contractor|freelance)\b', re.I)),
    ('part_time', re.compile(r'\bpart[- ]?time\b', re.I)),
    ('full_time', re.compile(r'\b(full[- ]?time|permanent|regular)\b', re.I)),
)
WORKPLACE = (
    ('hybrid', re.compile(r'\bhybrid\b', re.I)),
    ('remote', re.compile(r'\bremote\b', re.I)),
    ('onsite', re.compile(r'\b(on[- ]?site|in[- ]office)\b', re.I)),
)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
PHONE = re.compile(r'\+?\d[\d ()-]{7,}\d')
TERM = re.compile(r'\.?[a-z0-9][a-z0-9+#.]*')


class _Text(HTMLParser):
    SKIPPED = {'script', 'style', 'noscript', 'template'}
    BLOCKS = {'p', 'div', 'li', 'br', 'tr', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIPPED:
            self.skipping += 1
        elif tag in self.BLOCKS:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in self.SKIPPED and self.skipping:
            self.skipping -= 1
        elif tag in self.BLOCKS:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def plain_text(value, *, escaped=False):
    """Reduce provider HTML to one line of visible text. Greenhouse content is entity-escaped first."""
    if not isinstance(value, str):
        return ''
    value = value[:MAX_DESCRIPTION_CHARACTERS]
    if escaped:
        value = html.unescape(value)
    parser = _Text()
    parser.feed(value)
    parser.close()
    return ' '.join(''.join(parser.parts).split())


def bounded(value, limit):
    text = plain_text(value)
    return text[:limit].rstrip() if text else None


def excerpt(text):
    text = PHONE.sub('[phone removed]', EMAIL.sub('[email removed]', text))
    if len(text) <= EXCERPT_LENGTH:
        return text
    return text[:EXCERPT_LENGTH].rsplit(' ', 1)[0].rstrip(' ,;:.') + '…'


def terms(*priority, description=''):
    """Title and employer terms always survive the cap; description terms are sorted, so word order is not retained."""
    def split(value):
        normal = unicodedata.normalize('NFKC', value).casefold()
        return [t for t in (m.rstrip('.') for m in TERM.findall(normal)) if 0 < len(t) <= MAX_TERM_LENGTH]
    first = list(dict.fromkeys(t for value in priority for t in split(value)))
    known = set(first)
    rest = sorted({t for t in split(PHONE.sub(' ', EMAIL.sub(' ', description)))} - known)
    return (first + rest)[:MAX_TERMS]


def query_terms(value):
    """Search keeps symbols such as C++ and C#, which MongoDB text indexes would discard."""
    return list(dict.fromkeys(terms(value)))[:8]


def job_type(title, employment):
    if INTERNSHIP.search(title):
        return 'internship'
    if GRADUATE.search(title):
        return 'graduate'
    for value in employment:
        if not isinstance(value, str):
            continue
        if INTERNSHIP.search(value):
            return 'internship'
        for name, pattern in EMPLOYMENT:
            if pattern.search(value):
                return name
    return 'unknown'


def workplace(*values):
    """Explicit labels are tried in the order given, so a provider field outranks location text."""
    for value in values:
        if not isinstance(value, str):
            continue
        for name, pattern in WORKPLACE:
            if pattern.search(value):
                return name
    return 'unknown'


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or port not in (None, 443):
        return None
    return value


def job_link(value):
    """A link the user pasted. It is stored and shown, never fetched, so no request ever goes to this host."""
    if not safe_url(value):
        return None
    parsed = urlsplit(value.strip())
    host = parsed.hostname.lower()
    if '.' not in host or host.endswith(('.local', '.internal', '.localhost')) or host.replace('.', '').isdigit() or ':' in host:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith('utm_')])
    return urlunsplit(('https', host, parsed.path or '/', query, ''))


def timestamp(value):
    """Provider dates become UTC at millisecond precision, which is what BSON retains."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            moment = datetime.fromtimestamp(value / 1000, timezone.utc)
        elif isinstance(value, str) and value:
            moment = datetime.fromisoformat(value)
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    if moment.tzinfo is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


def posting_id(provider, board, external_id):
    return hashlib.sha256(f'{provider}:{board}:{external_id}'.encode()).hexdigest()[:32]


def build(source, raw):
    """Return a catalogue document, or None when a required field fails validation."""
    title = bounded(raw.get('title'), 200)
    location = bounded(raw.get('location'), 200)
    external_id = raw.get('external_id')
    apply_url = safe_url(raw.get('apply_url'))
    listing_url = safe_url(raw.get('listing_url')) or apply_url
    if not title or not location or not apply_url or not isinstance(external_id, str) or not 0 < len(external_id) <= 200:
        return None
    description = raw.get('description') or ''
    department = bounded(raw.get('department'), 120)
    return {
        '_id': posting_id(source['provider'], source['board'], external_id),
        'source_id': source_id(source),
        'provider': source['provider'],
        'company': source['company'],
        'industry': source['industry'],
        'title': title,
        'location': location,
        'department': department,
        'job_type': job_type(title, raw.get('employment') or ()),
        'workplace': workplace(*(raw.get('workplace') or ()), location),
        'posted_at': timestamp(raw.get('posted_at')),
        'application_deadline': timestamp(raw.get('application_deadline')),
        'excerpt': excerpt(description),
        'listing_url': listing_url,
        'apply_url': apply_url,
        'search_terms': terms(title, source['company'], department or '', description=description),
    }


def source_id(source):
    return f"{source['provider']}:{source['board']}"

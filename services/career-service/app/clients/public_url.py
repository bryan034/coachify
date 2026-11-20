"""Public-URL safety checks and readable text from job page markup."""
import ipaddress
import re
import socket
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

UNSAFE_URL_CHARACTERS = frozenset(map(chr, [*range(33), 127]))

BLOCKED_PREFIX = 'The information could not be extracted from this website.'
BLOCKED = BLOCKED_PREFIX + ' Copy and paste the job description instead.'
# Job aggregators whose terms forbid automated reading of their listings.
BLOCKED_HOSTS = {'linkedin.com': 'LinkedIn', 'indeed.com': 'Indeed', 'glassdoor.com': 'Glassdoor', 'glassdoor.sg': 'Glassdoor',
    'jobstreet.com': 'JobStreet', 'jobstreet.com.sg': 'JobStreet'}


class AccessBlocked(ValueError):
    """The site refused automated reading; the user should paste the description."""
    def __init__(self, site=None):
        super().__init__(BLOCKED if site is None else
            f'{BLOCKED_PREFIX} {site} does not allow its job listings to be read automatically. '
            f'Open the job on {site}, copy the description and paste it here.')


def blocked_host(host):
    host = (host or '').lower().rstrip('.')
    return next((site for name, site in BLOCKED_HOSTS.items() if host == name or host.endswith('.' + name)), None)


def destination(url):
    try:
        if any(c in UNSAFE_URL_CHARACTERS for c in url) or '\\' in url:
            raise ValueError
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.port not in (None, 80 if parsed.scheme == 'http' else 443):
            raise ValueError
        host = parsed.hostname.encode('idna').decode('ascii')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Use a public HTTP or HTTPS page URL without credentials or custom ports.') from exc
    site = blocked_host(host)
    if site:
        raise AccessBlocked(site)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Private, local and internal addresses cannot be imported. Paste the description instead.')
    except socket.gaierror as exc:
        raise ValueError('The website could not be found. Check the URL or paste the description.') from exc
    return parsed, host, port, addresses[0][4][0]


def html_text(markup):
    soup = BeautifulSoup(markup, 'html.parser')
    for node in soup.select('script,style,nav,footer,header,aside,form,noscript,svg'):
        node.decompose()
    for node in soup.find_all('br'): node.replace_with('\n')
    for node in soup.find_all('li'): node.insert(0, '• ')
    container = soup.select_one('[itemprop="description"]') or soup.find('main') or soup.find('article') or soup.body or soup
    # Keep paragraphs/line structure while avoiding a newline around every inline span.
    for node in container.find_all(['p','div','section','li','h1','h2','h3','h4','tr']): node.append('\n')
    text = container.get_text('')
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text).strip()

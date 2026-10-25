"""Public-page fetcher: pin validated IPs; preserve TLS host verification; no proxies/cookies/scripts."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin, urlunsplit
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from app.domain.documents import validate_text
from app.schemas.preview import MAX_JD_TEXT

MAX_DOWNLOAD = 2 * 1024 * 1024
AGENT = 'CoachifyPreview/1.0'


def destination(url):
    try:
        if any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url:
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
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Private, local and internal addresses cannot be imported. Paste the description instead.')
    except socket.gaierror as exc:
        raise ValueError('The website could not be found. Check the URL or paste the description.') from exc
    return parsed, host, port, addresses[0][4][0]


def request_page(url, deadline):
    parsed, host, port, address = destination(url)
    timeout = max(0.1, min(5, deadline - time.monotonic()))
    if deadline <= time.monotonic(): raise ValueError('The website took too long. Retry or paste the description.')
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.sock = socket.create_connection((address, port), timeout=timeout)
        if parsed.scheme == 'https':
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
        path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
        connection.request('GET', path, headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, headers, b''
        if headers.get('content-encoding', 'identity').lower() != 'identity':
            raise ValueError('This website uses an unsupported response format. Paste the description instead.')
        if int(headers.get('content-length', '0')) > MAX_DOWNLOAD:
            raise ValueError('The webpage is too large. Paste just the job description instead.')
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise ValueError('The website took too long. Retry or paste the description.')
            connection.sock.settimeout(min(5, remaining)) if connection.sock else None
            chunk = response.read1(min(65536, MAX_DOWNLOAD + 1 - len(data)))
            data.extend(chunk)
            if len(data) > MAX_DOWNLOAD: raise ValueError('The webpage is too large. Paste the description instead.')
            if not chunk: break
        return response.status, headers, bytes(data)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError('The website could not be reached securely. Retry, paste the description or upload a document.') from exc
    finally:
        connection.close()


def fetch_following(url, deadline, fetch=request_page):
    for _ in range(4):
        status, headers, data = fetch(url, deadline)
        if status not in {301, 302, 303, 307, 308}: return url, status, headers, data
        location = headers.get('location')
        if not location: raise ValueError('The website returned an invalid redirect. Paste the description instead.')
        url = urljoin(url, location)
    raise ValueError('The website redirects too many times. Paste the description instead.')


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


def posting_context(job):
    """Keep public JobPosting facts that often sit outside description HTML."""
    def readable(value):
        if isinstance(value, str):
            return html_text(value)
        if isinstance(value, list):
            return '; '.join(filter(None, (readable(item) for item in value)))
        return ''

    lines = []
    organization = job.get('hiringOrganization')
    if isinstance(organization, dict) and isinstance(organization.get('name'), str):
        lines.append('Company: ' + readable(organization['name']))
    locations = job.get('jobLocation', [])
    if not isinstance(locations, list):
        locations = [locations]
    names = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get('address')
        if isinstance(address, dict):
            parts = []
            for key in ('addressLocality', 'addressRegion', 'addressCountry'):
                value = address.get(key)
                if isinstance(value, dict):
                    value = value.get('name')
                if readable(value):
                    parts.append(readable(value))
            if parts:
                names.append(', '.join(parts))
        elif readable(address or location.get('name')):
            names.append(readable(address or location.get('name')))
    if names:
        lines.append('Job location: ' + '; '.join(names))
    for key, label in (('jobLocationType', 'Work arrangement'), ('employmentType', 'Employment type'),
            ('industry', 'Industry'), ('occupationalCategory', 'Occupation'),
            ('qualifications', 'Qualifications'), ('educationRequirements', 'Education requirements'),
            ('experienceRequirements', 'Experience requirements'), ('skills', 'Skills'), ('responsibilities', 'Responsibilities')):
        text = readable(job.get(key))
        if text:
            lines.append(label + ': ' + text)
    return '\n'.join(lines)


def extract_page(data):
    soup = BeautifulSoup(data, 'html.parser')
    jobs = []
    def scan(value):
        if isinstance(value, list):
            for item in value: scan(item)
        elif isinstance(value, dict):
            types = value.get('@type', [])
            if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types: jobs.append(value)
            if '@graph' in value: scan(value['@graph'])
    for script in soup.find_all('script', type='application/ld+json'):
        try: scan(json.loads(script.string or ''))
        except (ValueError, RecursionError): continue
    if len(jobs) > 1:
        raise ValueError('This page contains multiple jobs. Open one job listing or paste one description.')
    if jobs and jobs[0].get('description'):
        title = jobs[0].get('title')
        text = '\n\n'.join(filter(None, [html_text(title) if isinstance(title, str) else '', posting_context(jobs[0]), html_text(str(jobs[0]['description']))]))
    else:
        text = html_text(str(soup))
    if not text.strip(): raise ValueError('No readable description was found. The site may require JavaScript or sign-in; paste the description or upload a document.')
    return validate_text(text, max_text=MAX_JD_TEXT)


def import_url(url, fetch=request_page):
    deadline = time.monotonic() + 12
    # Validate before requesting robots as well as on every redirect connection.
    parsed, _, _, _ = destination(url)
    robots = urlunsplit((parsed.scheme, parsed.netloc, '/robots.txt', '', ''))
    _, status, _, data = fetch_following(robots, deadline, fetch)
    if status in {401,403,429} or status >= 500:
        raise ValueError('This website restricts automated access. Paste the description or upload a document.')
    if status == 200:
        rules = RobotFileParser(); rules.parse(data.decode('utf-8', errors='replace').splitlines())
        if not rules.can_fetch(AGENT, url):
            raise ValueError('This website restricts automated access. Paste the description or upload a document.')
    # Re-check robots at a redirect destination before retrieving that page.
    final, status, headers, data = fetch_following(url, deadline,
        lambda u,d: fetch(u,d) if u == url else checked_redirect(u,d,fetch))
    if status != 200:
        raise ValueError('This page is unavailable or requires sign-in. Paste the description or upload a document.')
    if headers.get('content-type','').split(';')[0].lower() not in {'text/html','application/xhtml+xml'}:
        raise ValueError('Use a public HTML job page, or upload the document instead.')
    return {'kind':'url','text':extract_page(data),'source_name':urlsplit(final).hostname or 'Job page','source_url':final,
            'notices':['Check that this preview contains one complete job description. Website navigation or missing sections may need editing.', 'This is a temporary preview; no role or skills have been interpreted.']}


def checked_redirect(url, deadline, fetch):
    parsed, _, _, _ = destination(url)
    robots = urlunsplit((parsed.scheme, parsed.netloc, '/robots.txt', '', ''))
    _, status, _, data = fetch_following(robots, deadline, fetch)
    if status in {401,403,429} or status >= 500:
        raise ValueError('The destination restricts automated access. Paste the description instead.')
    if status == 200:
        rules=RobotFileParser(); rules.parse(data.decode('utf-8',errors='replace').splitlines())
        if not rules.can_fetch(AGENT,url): raise ValueError('The destination restricts automated access. Paste the description instead.')
    return fetch(url,deadline)

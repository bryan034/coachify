"""Public-page fetcher for user-requested pages: pin validated IPs; preserve TLS host verification; no proxies/cookies/scripts."""
import http.client
from http import HTTPStatus
import json
import re
import socket
import ssl
import time
import zlib
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from app.domain.documents import validate_text
from app.schemas.preview import MAX_JD_TEXT,URL_NETWORK_TIMEOUT,URL_IMPORT_TIMEOUT
from app.clients.public_url import AccessBlocked, destination, html_text
from app.clients.public_job_api import read_preview

MAX_REDIRECTS = 3
MIN_READABLE_CHARS = 200

MAX_DOWNLOAD = 2 * 1024 * 1024
AGENT = 'Mozilla/5.0 (compatible; eloPreview/1.0)'
REQUEST_HEADERS = {'User-Agent': AGENT, 'Accept': 'text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-SG,en;q=0.9', 'Accept-Encoding': 'gzip, deflate'}


class RenderRequired(ValueError):
    """An accessible page needs the isolated JavaScript renderer."""
    def __init__(self,url):
        super().__init__('This page needs JavaScript. Paste the description or upload a document.')
        self.url=url


class PageTimeout(ValueError):
    """A retryable public-page timeout, distinct from TLS or access failures."""


def network_timeout(deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise PageTimeout('The website import timed out. Retry, paste the description or upload a document.')
    return min(URL_NETWORK_TIMEOUT,remaining)


def request_page(url, deadline):
    parsed, host, port, address = destination(url)
    timeout = network_timeout(deadline)
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    response=None
    try:
        connection.sock = socket.create_connection((address, port), timeout=timeout)
        connection.sock.settimeout(network_timeout(deadline))
        if parsed.scheme == 'https':
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
        transport=connection.sock
        transport.settimeout(network_timeout(deadline))
        path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
        connection.request('GET', path, headers=REQUEST_HEADERS)
        transport.settimeout(network_timeout(deadline))
        response = connection.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, headers, b''
        if int(headers.get('content-length', '0')) > MAX_DOWNLOAD:
            raise ValueError('The webpage is too large. Paste just the job description instead.')
        data = bytearray()
        while True:
            transport.settimeout(network_timeout(deadline))
            chunk = response.read1(min(65536, MAX_DOWNLOAD + 1 - len(data)))
            data.extend(chunk)
            if len(data) > MAX_DOWNLOAD: raise ValueError('The webpage is too large. Paste the description instead.')
            if not chunk or response.isclosed(): break
        data = decode_body(bytes(data), headers.pop('content-encoding', 'identity'))
        return response.status, headers, data
    except TimeoutError as exc:
        raise PageTimeout('The website timed out while reading the webpage. Retry, paste the description or upload a document.') from exc
    except ssl.SSLCertVerificationError as exc:
        raise ValueError('The website’s TLS certificate could not be verified. Paste the description or upload a document.') from exc
    except ssl.SSLError as exc:
        raise ValueError('A secure TLS connection to the website could not be established. Retry, paste the description or upload a document.') from exc
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError('The website could not be reached. Retry, paste the description or upload a document.') from exc
    finally:
        if response is not None:response.close()
        connection.close()


def decode_body(data, encoding):
    """Decompress gzip/deflate bodies without ever producing more than MAX_DOWNLOAD bytes."""
    encoding = encoding.strip().lower()
    if encoding in ('', 'identity'):
        return data
    modes = {'gzip': (31,), 'x-gzip': (31,), 'deflate': (15, -15)}.get(encoding)
    if modes is None:
        raise ValueError('This website uses an unsupported response format. Paste the description instead.')
    for wbits in modes:
        decoder = zlib.decompressobj(wbits)
        try:
            body = decoder.decompress(data, MAX_DOWNLOAD + 1)
        except zlib.error:
            continue
        if len(body) > MAX_DOWNLOAD or decoder.unconsumed_tail:
            raise ValueError('The webpage is too large. Paste the description instead.')
        if decoder.eof:
            return body
    raise ValueError('This website returned an unreadable compressed response. Paste the description instead.')


def fetch_with_timeout_retry(url,deadline,fetch):
    for attempt in range(2):
        network_timeout(deadline)
        try:return fetch(url,deadline)
        except PageTimeout:
            if attempt or time.monotonic()>=deadline:raise


def fetch_following(url, deadline, fetch=request_page):
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, data = fetch(url, deadline)
        if status not in {301, 302, 303, 307, 308}: return url, status, headers, data
        location = headers.get('location')
        if not location: raise ValueError('The website returned an invalid redirect. Paste the description instead.')
        url = urljoin(url, location)
    raise ValueError('The website redirects too many times. Paste the description instead.')


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
    deadline = time.monotonic() + URL_IMPORT_TIMEOUT
    raw_fetch=fetch
    fetch=lambda target,limit:fetch_with_timeout_retry(target,limit,raw_fetch)
    parsed, _, _, _ = destination(url)
    public_job=read_preview(parsed,url,deadline,fetch)
    if public_job is not None:return public_job
    final, status, headers, data = fetch_following(url, deadline,
        lambda u,d: fetch(u,d) if u == url else checked_redirect(u,d,fetch))
    check_page_status(status)
    if headers.get('content-type','').split(';')[0].lower() not in {'text/html','application/xhtml+xml'}:
        raise ValueError('Use a public HTML job page, or upload the document instead.')
    check_access_page(data)
    if needs_rendering(data):raise RenderRequired(final)
    return {'kind':'url','text':extract_page(data),'source_name':urlsplit(final).hostname or 'Job page','source_url':final,
            'notices':['Check that this preview contains one complete job description. Website navigation or missing sections may need editing.', 'This is a temporary preview; no role or skills have been interpreted.']}


def checked_redirect(url, deadline, fetch):
    destination(url)
    return fetch(url,deadline)


def check_page_status(status):
    if status==HTTPStatus.OK:return
    if status in (401,403,429):raise AccessBlocked()
    if status in (404,410):message='This job page is no longer available or the link is incorrect.'
    elif status>=HTTPStatus.INTERNAL_SERVER_ERROR:message='This website is temporarily unavailable.'
    else:message='This website did not return an accessible job page.'
    raise ValueError(message+' Paste the description or upload a document.')


def check_access_page(data):
    soup=BeautifulSoup(data,'html.parser')
    heading=' '.join(node.get_text(' ',strip=True) for node in soup.select('title,h1')).lower()
    text=html_text(str(soup)).lower()
    if (any(term in heading for term in ('access denied','just a moment','security check','sign in','log in','captcha'))
        or any(term in text for term in ('verify you are human','verify that you are human','complete the captcha','enable javascript and cookies to continue'))):
        raise AccessBlocked()


def needs_rendering(data):
    soup=BeautifulSoup(data,'html.parser')
    for script in soup.find_all('script',type='application/ld+json'):
        if 'JobPosting' in (script.string or ''):return False
    text=html_text(str(soup))
    if re.search(r'(enable|requires?|turn on)\s+javascript',text,re.I):return True
    return bool(soup.find('script')) and len(text)<MIN_READABLE_CHARS

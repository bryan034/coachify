"""Read-only public board adapters. API origins are fixed and board names come from the reviewed registry."""
import json
import re
import time

import httpx

from app.normalise import SINGAPORE, plain_text

MAX_RESPONSE_BYTES = 48 * 1024 * 1024
USER_AGENT = 'elo-jobs-live/0.1'
EMPLOYMENT_METADATA = re.compile(r'employment|time type|commitment|job type', re.I)
WORKPLACE_METADATA = re.compile(r'workplace|location type|remote', re.I)


class ProviderUnavailable(Exception):
    """The whole board could not be read, so existing postings must not be treated as missing."""


def _text(value):
    return value if isinstance(value, str) else ''


def _greenhouse(job):
    location = _text((job.get('location') or {}).get('name'))
    if not SINGAPORE.search(location):
        return None
    metadata = [m for m in job.get('metadata') or [] if isinstance(m, dict) and isinstance(m.get('name'), str)]
    departments = job.get('departments') or []
    department = departments[0].get('name') if departments and isinstance(departments[0], dict) else None
    return {
        'external_id': str(job.get('id') or ''),
        'title': job.get('title'),
        'location': location,
        'department': department,
        'employment': [m.get('value') for m in metadata if EMPLOYMENT_METADATA.search(m['name'])],
        'workplace': [m.get('value') for m in metadata if WORKPLACE_METADATA.search(m['name'])],
        # updated_at changes on any edit, so it is not a posting date.
        'posted_at': job.get('first_published'),
        'application_deadline': job.get('application_deadline'),
        'description': plain_text(job.get('content'), escaped=True),
        'listing_url': job.get('absolute_url'),
        'apply_url': job.get('absolute_url'),
    }


def _lever(job):
    categories = job.get('categories') or {}
    locations = [_text(categories.get('location'))] + [_text(v) for v in categories.get('allLocations') or []]
    named = list(dict.fromkeys(v for v in locations if v))
    if not any(SINGAPORE.search(v) for v in named):
        return None
    lists = [plain_text(_text(item.get('content'))) for item in job.get('lists') or [] if isinstance(item, dict)]
    return {
        'external_id': _text(job.get('id')),
        'title': job.get('text'),
        'location': ', '.join(named),
        'department': categories.get('department') or categories.get('team'),
        'employment': [categories.get('commitment')],
        'workplace': [job.get('workplaceType')],
        'posted_at': job.get('createdAt'),
        'description': ' '.join([plain_text(job.get('descriptionPlain')), *lists]).strip(),
        'listing_url': job.get('hostedUrl'),
        'apply_url': job.get('applyUrl') or job.get('hostedUrl'),
    }


def _ashby(job):
    if job.get('isListed') is False:
        return None
    secondary = [_text(item.get('location')) for item in job.get('secondaryLocations') or [] if isinstance(item, dict)]
    named = list(dict.fromkeys(v for v in [_text(job.get('location')), *secondary] if v))
    postal = ((job.get('address') or {}).get('postalAddress') or {})
    if not any(SINGAPORE.search(v) for v in [*named, _text(postal.get('addressCountry'))]):
        return None
    return {
        'external_id': _text(job.get('id')),
        'title': job.get('title'),
        'location': ', '.join(named),
        'department': job.get('department') or job.get('team'),
        'employment': [job.get('employmentType')],
        'workplace': [job.get('workplaceType'), 'remote' if job.get('isRemote') is True else None],
        'posted_at': job.get('publishedAt'),
        'description': plain_text(job.get('descriptionPlain')) or plain_text(job.get('descriptionHtml')),
        'listing_url': job.get('jobUrl'),
        'apply_url': job.get('applyUrl') or job.get('jobUrl'),
    }


def _board_jobs(data):
    return data.get('jobs') if isinstance(data, dict) else None


PROVIDERS = {
    'greenhouse': ('https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true', _board_jobs, _greenhouse),
    'lever': ('https://api.lever.co/v0/postings/{board}?mode=json', lambda data: data, _lever),
    'ashby': ('https://api.ashbyhq.com/posting-api/job-board/{board}', _board_jobs, _ashby),
}


def fetch_json(client, url):
    deadline = time.monotonic() + 5
    try:
        with client.stream('GET', url) as response:
            if response.status_code != 200:
                raise ProviderUnavailable(f'status {response.status_code}')
            if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                raise ProviderUnavailable('unexpected content type')
            body = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise ProviderUnavailable('response timed out')
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProviderUnavailable('response too large')
        return json.loads(body)
    except (httpx.HTTPError, ValueError, RecursionError) as error:
        raise ProviderUnavailable(type(error).__name__) from None


def read_board(source, fetch):
    """Return (Singapore records, rejected count). A malformed record never fails the rest of the board."""
    template, listing, adapter = PROVIDERS[source['provider']]
    jobs = listing(fetch(template.format(board=source['board'])))
    if not isinstance(jobs, list):
        raise ProviderUnavailable('unexpected response shape')
    records, rejected = [], 0
    for job in jobs:
        try:
            record = adapter(job)
        except (AttributeError, TypeError, ValueError, KeyError, IndexError):
            rejected += 1
            continue
        if record is not None:
            records.append(record)
    return records, rejected

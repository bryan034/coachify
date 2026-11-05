import json
from datetime import timedelta

import httpx
import pytest

from app.normalise import posting_id
from app.providers import MAX_RESPONSE_BYTES, ProviderUnavailable, fetch_json, read_board
from app.store import JobsStore
from app.sync import interval_from_environment, load_sources, sync_all, sync_source
from jobs_fixtures import ASHBY, GREENHOUSE, LEVER, NOW, ashby_job, greenhouse_job, lever_job

SIX_HOURS = timedelta(hours=6)


def board(jobs):
    return lambda url: {'jobs': jobs}


@pytest.fixture
def store(database):
    jobs = JobsStore(database)
    jobs.ensure_indexes()
    return jobs


def stored(store, source, external):
    return store.postings.find_one({'_id': posting_id(source['provider'], source['board'], external)})


def test_each_provider_maps_to_the_same_catalogue_fields(store):
    assert sync_source(store, GREENHOUSE, board([greenhouse_job()]), NOW, SIX_HOURS) == 1
    assert sync_source(store, LEVER, lambda url: [lever_job()], NOW, SIX_HOURS) == 1
    assert sync_source(store, ASHBY, board([ashby_job()]), NOW, SIX_HOURS) == 1
    green, lever, ashby = stored(store, GREENHOUSE, '1'), stored(store, LEVER, 'a1'), stored(store, ASHBY, 'b1')
    assert (green['job_type'], green['workplace'], green['industry'], green['department']) == ('full_time', 'hybrid', 'financial_services', 'Engineering')
    assert (lever['job_type'], lever['workplace'], lever['industry']) == ('internship', 'onsite', 'logistics')
    assert (ashby['job_type'], ashby['workplace'], ashby['industry']) == ('contract', 'remote', 'artificial_intelligence')
    assert green['posted_at_estimated'] is False and green['posted_at'].isoformat() == '2026-10-08T06:58:03+00:00'
    assert lever['apply_url'].endswith('/apply') and ashby['apply_url'].endswith('/application')
    assert 'steal' not in green['excerpt'] and 'steal' not in green['search_terms']
    assert {'c++', 'python'} <= set(green['search_terms']) and 'sql' in lever['search_terms']


def test_full_descriptions_are_not_stored(store):
    secret = 'distinctive ' * 200
    sync_source(store, ASHBY, board([ashby_job(descriptionPlain=secret)]), NOW, SIX_HOURS)
    row = stored(store, ASHBY, 'b1')
    assert len(row['excerpt']) <= 281
    assert not {'description', 'descriptionPlain', 'descriptionHtml', 'content'} & set(row)


def test_only_singapore_roles_enter_the_catalogue(store):
    jobs = [greenhouse_job(1, location='London'), greenhouse_job(2, location='Remote, Australia; Remote, Singapore')]
    assert sync_source(store, GREENHOUSE, board(jobs), NOW, SIX_HOURS) == 1
    assert stored(store, GREENHOUSE, '1') is None
    assert stored(store, GREENHOUSE, '2')['workplace'] == 'hybrid'
    lever_abroad = lever_job(categories={'location': 'Asia', 'allLocations': ['Asia', 'Hong Kong']}, country='SG')
    assert sync_source(store, LEVER, lambda url: [lever_abroad], NOW, SIX_HOURS) == 0
    assert sync_source(store, ASHBY, board([ashby_job(isListed=False)]), NOW, SIX_HOURS) == 0


def test_postings_close_only_after_three_complete_reads_without_them(store):
    sync_source(store, GREENHOUSE, board([greenhouse_job()]), NOW, SIX_HOURS)
    for run in range(1, 4):
        store.sources.update_one({'_id': 'greenhouse:synthetic-gh'}, {'$set': {'next_attempt_at': NOW}})
        sync_source(store, GREENHOUSE, board([]), NOW + timedelta(hours=run), SIX_HOURS)
        assert stored(store, GREENHOUSE, '1')['status'] == ('closed' if run == 3 else 'open')
    store.sources.update_one({'_id': 'greenhouse:synthetic-gh'}, {'$set': {'next_attempt_at': NOW}})
    sync_source(store, GREENHOUSE, board([greenhouse_job()]), NOW + timedelta(hours=9), SIX_HOURS)
    row = stored(store, GREENHOUSE, '1')
    assert (row['status'], row['missed_syncs'], row['closed_at']) == ('open', 0, None)
    assert row['first_seen_at'] == NOW


def test_provider_outage_keeps_postings_and_backs_off(store):
    sync_source(store, GREENHOUSE, board([greenhouse_job()]), NOW, SIX_HOURS)
    def outage(url):
        raise ProviderUnavailable('status 503')
    later = NOW + timedelta(hours=7)
    for failures, delay in ((1, 6), (2, 12)):
        store.sources.update_one({'_id': 'greenhouse:synthetic-gh'}, {'$set': {'next_attempt_at': NOW}})
        assert sync_source(store, GREENHOUSE, outage, later, SIX_HOURS) is None
        state = store.sources.find_one({'_id': 'greenhouse:synthetic-gh'})
        assert state['failures'] == failures and state['next_attempt_at'] == later + timedelta(hours=delay)
    row = stored(store, GREENHOUSE, '1')
    assert (row['status'], row['missed_syncs']) == ('open', 0)
    assert state['last_synced_at'] == NOW


def test_a_malformed_record_never_closes_other_postings(store):
    sync_source(store, GREENHOUSE, board([greenhouse_job(1), greenhouse_job(2)]), NOW, SIX_HOURS)
    store.sources.update_one({'_id': 'greenhouse:synthetic-gh'}, {'$set': {'next_attempt_at': NOW}})
    malformed = {**greenhouse_job(3), 'absolute_url': 'http://not-https.test/3'}
    wrong_shape = {'id': 4, 'location': 'not-a-mapping'}
    assert sync_source(store, GREENHOUSE, board([greenhouse_job(1), malformed, wrong_shape]), NOW + timedelta(hours=7), SIX_HOURS) == 1
    assert stored(store, GREENHOUSE, '2')['missed_syncs'] == 0
    assert stored(store, GREENHOUSE, '3') is None


def test_missing_or_implausible_dates_use_first_seen_and_are_marked(store):
    sync_source(store, ASHBY, board([ashby_job('none', publishedAt=None), ashby_job('future', publishedAt='2030-01-01T00:00:00+00:00')]), NOW, SIX_HOURS)
    for external in ('none', 'future'):
        row = stored(store, ASHBY, external)
        assert row['posted_at'] == NOW and row['posted_at_estimated'] is True
    store.sources.update_one({'_id': 'ashby:synthetic-ab'}, {'$set': {'next_attempt_at': NOW}})
    sync_source(store, ASHBY, board([ashby_job('none', publishedAt=None)]), NOW + timedelta(days=2), SIX_HOURS)
    assert stored(store, ASHBY, 'none')['posted_at'] == NOW


def test_a_board_is_held_by_one_worker_and_recovers_after_its_lease(store):
    token = store.claim_source('lever:one', NOW)
    assert token and store.claim_source('lever:one', NOW) is None
    assert store.claim_source('lever:one', NOW + timedelta(minutes=11))
    store.finish_source('lever:one', token, NOW, next_attempt_at=NOW + SIX_HOURS, succeeded=True)
    assert store.sources.find_one({'_id': 'lever:one'})['last_synced_at'] is None


def test_removing_a_board_from_the_registry_removes_its_listings(store):
    pauses = []
    assert sync_all(store, [GREENHOUSE, LEVER], lambda url: {'jobs': [greenhouse_job()]} if 'greenhouse' in url else [lever_job()], SIX_HOURS, lambda: NOW, pauses.append) == 2
    assert len(pauses) == 2
    store.sources.update_many({}, {'$set': {'next_attempt_at': NOW + SIX_HOURS}})
    assert sync_all(store, [LEVER], lambda url: [], SIX_HOURS, lambda: NOW, pauses.append) == 0
    assert stored(store, GREENHOUSE, '1') is None and stored(store, LEVER, 'a1') is not None
    assert store.sources.find_one({'_id': 'greenhouse:synthetic-gh'}) is None


@pytest.mark.parametrize('status,headers,body,message', [
    (404, {'content-type': 'application/json'}, b'{}', 'status 404'),
    (302, {'content-type': 'application/json', 'location': 'https://elsewhere.test'}, b'', 'status 302'),
    (200, {'content-type': 'text/html'}, b'<html>', 'unexpected content type'),
    (200, {'content-type': 'application/json'}, b'{not json', 'JSONDecodeError'),
])
def test_fetch_rejects_unusable_responses(status, headers, body, message):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, headers=headers, content=body)), follow_redirects=False)
    with pytest.raises(ProviderUnavailable, match=message):
        fetch_json(client, 'https://boards-api.greenhouse.io/v1/boards/x/jobs')


def test_fetch_stops_at_its_size_limit():
    oversized = httpx.Response(200, headers={'content-type': 'application/json'}, content=b' ' * (MAX_RESPONSE_BYTES + 1))
    client = httpx.Client(transport=httpx.MockTransport(lambda request: oversized))
    with pytest.raises(ProviderUnavailable, match='too large'):
        fetch_json(client, 'https://api.lever.co/v0/postings/x?mode=json')


def test_unexpected_board_shapes_are_outages_not_empty_boards():
    with pytest.raises(ProviderUnavailable):
        read_board(GREENHOUSE, lambda url: {'unexpected': []})
    with pytest.raises(ProviderUnavailable):
        read_board(LEVER, lambda url: {'jobs': []})


def test_requests_use_fixed_provider_origins():
    urls = []
    def capture(url):
        urls.append(url)
        return {'jobs': []} if 'lever' not in url else []
    for source in (GREENHOUSE, LEVER, ASHBY):
        read_board(source, capture)
    assert urls == ['https://boards-api.greenhouse.io/v1/boards/synthetic-gh/jobs?content=true',
                    'https://api.lever.co/v0/postings/synthetic-lv?mode=json',
                    'https://api.ashbyhq.com/posting-api/job-board/synthetic-ab']


def test_bundled_registry_is_valid_and_unique():
    sources = load_sources()
    assert len(sources) == 40
    assert {s['provider'] for s in sources} == {'greenhouse', 'lever', 'ashby'}


@pytest.mark.parametrize('rows', [
    [{'provider': 'workday', 'board': 'x', 'company': 'X', 'industry': 'technology'}],
    [{'provider': 'lever', 'board': '../x', 'company': 'X', 'industry': 'technology'}],
    [{'provider': 'lever', 'board': 'x', 'company': 'X', 'industry': 'unknown'}],
    [{'provider': 'lever', 'board': 'x', 'company': 'X', 'industry': 'technology'}] * 2,
])
def test_registry_rejects_invalid_entries(tmp_path, rows):
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        load_sources(path)


def test_disabled_registry_entries_are_excluded(tmp_path):
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps([{'provider': 'lever', 'board': 'x', 'company': 'X', 'industry': 'technology', 'enabled': False}]))
    assert load_sources(path) == []


def test_sync_interval_is_bounded(monkeypatch):
    monkeypatch.setenv('JOBS_SYNC_INTERVAL_HOURS', '12')
    assert interval_from_environment() == timedelta(hours=12)
    monkeypatch.setenv('JOBS_SYNC_INTERVAL_HOURS', '0')
    with pytest.raises(ValueError):
        interval_from_environment()

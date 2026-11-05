"""Live search uses synthetic HTTP responses; MongoDB contains only saved applications."""
from types import SimpleNamespace
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import Problem

from app.live import LiveJobs
from app.main import create_app
from app.providers import ProviderUnavailable
from app.store import search_filter
from jobs_fixtures import GREENHOUSE, LEVER, NOW, SyntheticUpstream, greenhouse_job, lever_job

OWNER = {'Authorization': 'Bearer owner'}


def test_each_search_reads_provider_again_and_never_uses_seeded_data(database):
    calls = []
    jobs = [greenhouse_job()]
    def fetch(url):
        calls.append(url)
        return {'jobs': jobs.copy()}
    live = LiveJobs([GREENHOUSE], fetch, lambda: NOW)
    database.job_postings.insert_one({'_id': 'stale', 'title': 'Stale job'})
    app = create_app(store=SimpleNamespace(database=database), upstream=SyntheticUpstream(), catalogue=live, clock=lambda: NOW)
    with TestClient(app) as client:
        assert client.get('/api/v1/jobs/search').status_code == 401
        assert calls == []
        first = client.get('/api/v1/jobs/search', headers=OWNER).json()
        assert first['total'] == 1 and len(calls) == 1
        identifier = first['items'][0]['id']
        saved = client.post('/api/v1/jobs/applications', headers=OWNER, json={'posting_id': identifier}).json()
        assert saved['snapshot']['title'] == 'Software Engineer'
        jobs.clear()
        assert client.post('/api/v1/jobs/applications', headers=OWNER, json={'posting_id': identifier}).json()['id'] == saved['id']
        assert client.get('/api/v1/jobs/search', headers=OWNER).json()['total'] == 0
        assert client.get('/api/v1/jobs/postings/' + identifier, headers=OWNER).status_code == 404
        item = client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'][0]
        assert item['posting_status'] == 'unknown' and item['snapshot'] == saved['snapshot']
        assert database.job_postings.count_documents({}) == 1
        assert database.job_sources.count_documents({}) == 0
        assert client.get('/api/v1/jobs/applications', headers={'Authorization': 'Bearer other'}).json()['items'] == []
        assert client.patch('/api/v1/jobs/applications/' + saved['id'], headers=OWNER,
                            json={'expected_version': 1, 'status': 'applied'}).status_code == 200


def test_search_works_without_storage_and_reports_partial_provider_failure():
    def fetch(url):
        if 'lever' in url:
            raise ProviderUnavailable('status 503')
        return {'jobs': [greenhouse_job()]}
    live = LiveJobs([GREENHOUSE, LEVER], fetch, lambda: NOW)
    app = create_app(store=SimpleNamespace(database=None), upstream=SyntheticUpstream(), catalogue=live)
    with TestClient(app) as client:
        result = client.get('/api/v1/jobs/search', headers=OWNER)
        assert result.status_code == 200
        assert result.json()['unavailable_sources'] == ['lever:synthetic-lv']
        assert result.json()['retrieved_at']
        assert client.get('/api/v1/jobs/filters', headers=OWNER).status_code == 200
        assert client.get('/api/v1/jobs/applications', headers=OWNER).status_code == 503


def test_total_provider_failure_is_an_error_not_empty_results():
    def fetch(url):
        raise ProviderUnavailable('unavailable')
    with pytest.raises(Problem) as error:
        LiveJobs([GREENHOUSE], fetch).search(search_filter())
    assert error.value.status == 503


def test_live_filters_dates_and_paging():
    jobs = [greenhouse_job(1, 'C++ Engineer'), greenhouse_job(2, 'Intern', content='Operations'), greenhouse_job(3, 'Unknown date', first_published=None, content='Operations')]
    live = LiveJobs([GREENHOUSE], lambda url: {'jobs': jobs}, lambda: NOW)
    assert live.search(search_filter('c++'))['total'] == 1
    assert live.search(search_filter(job_types=['internship']))['total'] == 1
    assert live.search(search_filter(companies=['Elsewhere']))['total'] == 0
    assert live.search(search_filter(posted_from=NOW))['total'] == 0
    query = search_filter()
    first = live.search(query, limit=2)
    second = live.search(query, first['next_cursor'], limit=2)
    assert len({r['id'] for r in first['items'] + second['items']}) == 3
    unknown = second['items'][0]
    assert unknown['posted_at_estimated'] is True
    assert live.filter_options()['companies'] == [{'value': 'Synthetic Bank', 'count': 3}]


@pytest.mark.parametrize('unavailable', [False, True])
def test_overlapping_searches_and_filters_share_live_work_and_recover(monkeypatch, unavailable):
    started, release, joined = Event(), Event(), Event()
    lock = Lock()
    waiters = 0
    calls = []
    jobs = [greenhouse_job()]

    class ObservedFuture(Future):
        def result(self, timeout=None):
            nonlocal waiters
            with lock:
                waiters += 1
                if waiters == 2:
                    joined.set()
            return super().result(timeout)

    monkeypatch.setattr('app.live.Future', ObservedFuture)

    def fetch(url):
        calls.append(url)
        started.set()
        assert release.wait(5), 'Test did not release the provider'
        if unavailable:
            raise ProviderUnavailable('status 503')
        return {'jobs': jobs.copy()}

    live = LiveJobs([GREENHOUSE], fetch, lambda: NOW)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(live.search, search_filter('engineer'))
        try:
            assert started.wait(5)
            filters = pool.submit(live.filter_options)
            latest = pool.submit(live.search, search_filter('unmatched'))
            assert joined.wait(5), 'Overlapping requests did not join the provider operation'
        finally:
            release.set()
        if unavailable:
            for request in (first, filters, latest):
                with pytest.raises(Problem) as error:
                    request.result(timeout=5)
                assert error.value.code == 'providers_unavailable'
        else:
            assert first.result(timeout=5)['total'] == 1
            assert filters.result(timeout=5)['companies'] == [{'value': 'Synthetic Bank', 'count': 1}]
            assert latest.result(timeout=5)['total'] == 0
    assert len(calls) == 1
    # Neither successful results nor failed operations survive as a cache.
    unavailable = False
    jobs.append(greenhouse_job(2, 'New role'))
    assert live.search(search_filter())['total'] == 2
    assert len(calls) == 2


def test_provider_concurrency_remains_bounded():
    ready, release = Event(), Event()
    lock = Lock()
    active = peak = 0
    def fetch(url):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 8:
                ready.set()
        try:
            assert release.wait(5)
            return {'jobs': [greenhouse_job()]}
        finally:
            with lock:
                active -= 1
    sources = [{**GREENHOUSE, 'board': f'synthetic-{i}'} for i in range(10)]
    live = LiveJobs(sources, fetch, lambda: NOW)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(live.search, search_filter())
        try:
            assert ready.wait(5)
        finally:
            release.set()
        assert result.result(timeout=5)['total'] == 10
    assert peak == 8


def test_invalid_records_warn_without_discarding_valid_results():
    live = LiveJobs([GREENHOUSE], lambda url: {'jobs': [greenhouse_job(), greenhouse_job(2, absolute_url='javascript:alert(1)')]})
    result = live.search(search_filter())
    assert result['total'] == 1
    assert result['unavailable_sources'] == ['greenhouse:synthetic-gh']

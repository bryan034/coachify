from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import JobsStore
from app.sync import sync_source
from jobs_fixtures import ASHBY, GREENHOUSE, LEVER, NOW, SyntheticUpstream, ashby_job, greenhouse_job, lever_job

OWNER = {'Authorization': 'Bearer owner'}
OTHER = {'Authorization': 'Bearer other'}
SIX_HOURS = timedelta(hours=6)


@pytest.fixture
def client(database):
    store = JobsStore(database)
    store.ensure_indexes()
    sync_source(store, GREENHOUSE, lambda url: {'jobs': [
        greenhouse_job(1, 'C++ Engineer'),
        greenhouse_job(2, 'Data Analyst', first_published='2026-11-01T00:00:00+08:00', content='Analyse payments data.'),
        greenhouse_job(3, 'Quant Intern', first_published='2026-11-04T23:59:00+08:00', content='Trading research.', metadata=[]),
    ]}, NOW, SIX_HOURS)
    sync_source(store, LEVER, lambda url: [lever_job()], NOW, SIX_HOURS)
    sync_source(store, ASHBY, lambda url: {'jobs': [ashby_job()]}, NOW, SIX_HOURS)
    app = create_app(store=SimpleNamespace(database=database), upstream=SyntheticUpstream(), clock=lambda: NOW, catalogue=store)
    with TestClient(app) as test_client:
        test_client.store = store
        yield test_client


def titles(client, **params):
    response = client.get('/api/v1/jobs/search', params=params, headers=OWNER)
    assert response.status_code == 200, response.text
    return [item['title'] for item in response.json()['items']]


def test_every_route_requires_a_session(client):
    for method, path in (('GET', 'search'), ('GET', 'filters'), ('GET', 'postings/' + '0' * 32), ('GET', 'applications'), ('POST', 'applications')):
        assert client.request(method, '/api/v1/jobs/' + path).status_code == 401
    assert client.get('/api/v1/jobs/search', headers={'Authorization': 'Bearer revoked'}).status_code == 401


def test_results_are_newest_first_without_internal_fields(client):
    body = client.get('/api/v1/jobs/search', headers=OWNER).json()
    assert body['total'] == 5
    assert [i['title'] for i in body['items']][:2] == ['Quant Intern', 'Data Analyst']
    assert all('search_terms' not in i and 'source_id' not in i for i in body['items'])
    assert client.get('/api/v1/jobs/search', headers=OWNER).headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('query,expected', [
    ('c++', {'C++ Engineer'}),
    ('c+', set()),
    ('engineers', set()),
    ('engineer', {'C++ Engineer', 'Data Analyst', 'Quant Intern'}),
    ('payments analyst', {'Data Analyst'}),
    ('payments engineer', {'Data Analyst'}),
    ('payments scientist', set()),
    ('SYNTHETIC BANK', {'C++ Engineer', 'Data Analyst', 'Quant Intern'}),
    ('python.*', {'C++ Engineer'}),
    ('p.thon', set()),
])
def test_keyword_search(client, query, expected):
    assert set(titles(client, q=query)) == expected


def test_a_keyword_does_not_match_longer_unrelated_words(client):
    assert titles(client, q='int') == []


def test_a_query_of_only_symbols_is_treated_as_no_keyword(client):
    assert len(titles(client, q='.* ( [')) == 5


def test_filter_by_job_type_industry_workplace_and_company(client):
    assert set(titles(client, job_type='internship')) == {'Quant Intern', 'Operations Intern'}
    assert set(titles(client, job_type=['contract', 'full_time'])) == {'C++ Engineer', 'Data Analyst', 'Research Scientist'}
    assert titles(client, job_type='unknown') == []
    assert set(titles(client, industry='logistics')) == {'Operations Intern'}
    assert set(titles(client, industry=['logistics', 'artificial_intelligence'])) == {'Operations Intern', 'Research Scientist'}
    assert set(titles(client, workplace='remote')) == {'Research Scientist'}
    assert set(titles(client, company='Synthetic Freight')) == {'Operations Intern'}
    assert set(titles(client, job_type='internship', industry='financial_services')) == {'Quant Intern'}


def test_filter_by_posted_date_uses_singapore_calendar_days(client):
    # 00:00 on 1 November in Singapore is still 31 October in UTC, so a UTC day boundary would miss it.
    assert titles(client, posted_from='2026-11-04', posted_to='2026-11-04') == ['Quant Intern']
    assert titles(client, posted_from='2026-11-01', posted_to='2026-11-01') == ['Data Analyst']
    assert titles(client, posted_within_days=2) == ['Quant Intern']
    assert set(titles(client, posted_within_days=7)) == {'Quant Intern', 'Data Analyst'}
    assert titles(client, posted_within_days=7, posted_from='2026-11-04') == ['Quant Intern']
    response = client.get('/api/v1/jobs/search', params={'posted_from': '2026-11-02', 'posted_to': '2026-11-01'}, headers=OWNER)
    assert response.status_code == 422


@pytest.mark.parametrize('params', [{'job_type': 'astronaut'}, {'industry': 'mining'}, {'workplace': 'moon'}, {'limit': 51}, {'limit': 0}, {'q': 'x' * 121}, {'posted_within_days': 0}, {'posted_from': 'soon'}])
def test_invalid_filters_are_rejected(client, params):
    response = client.get('/api/v1/jobs/search', params=params, headers=OWNER)
    assert response.status_code == 422 and response.json()['code'] == 'validation'


def test_cursor_pages_through_every_result_once(client):
    seen, cursor = [], None
    for _ in range(5):
        params = {'limit': 2, **({'cursor': cursor} if cursor else {})}
        body = client.get('/api/v1/jobs/search', params=params, headers=OWNER).json()
        assert body['total'] == 5
        seen += [i['id'] for i in body['items']]
        cursor = body['next_cursor']
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


def test_invalid_cursor_is_rejected(client):
    for cursor in ('not-a-cursor', 'bm90fGEtY3Vyc29y'):
        assert client.get('/api/v1/jobs/search', params={'cursor': cursor}, headers=OWNER).status_code == 422


def test_filter_options_report_available_values(client):
    body = client.get('/api/v1/jobs/filters', headers=OWNER).json()
    assert {'value': 'internship', 'count': 2} in body['job_types']
    assert {'value': 'financial_services', 'count': 3} in body['industries']
    assert [c['value'] for c in body['companies']] == ['Synthetic Bank', 'Synthetic Freight', 'Synthetic Labs']
    assert body['last_synced_at'].startswith('2026-11-05T04:00')


def test_closed_postings_leave_search_but_remain_readable(client):
    identifier = client.get('/api/v1/jobs/search', params={'company': 'Synthetic Labs'}, headers=OWNER).json()['items'][0]['id']
    client.store.postings.update_one({'_id': identifier}, {'$set': {'status': 'closed'}})
    assert 'Research Scientist' not in titles(client)
    assert client.get('/api/v1/jobs/postings/' + identifier, headers=OWNER).json()['status'] == 'closed'
    assert client.get('/api/v1/jobs/postings/' + '0' * 32, headers=OWNER).status_code == 404
    assert client.get('/api/v1/jobs/postings/not-an-id', headers=OWNER).status_code == 422


def first_posting(client):
    return client.get('/api/v1/jobs/search', headers=OWNER).json()['items'][0]


def test_saving_a_job_is_idempotent_and_private_to_its_owner(client):
    posting = first_posting(client)
    created = client.post('/api/v1/jobs/applications', json={'posting_id': posting['id']}, headers=OWNER)
    assert created.status_code == 200
    saved = created.json()
    assert (saved['status'], saved['version'], saved['posting_status']) == ('saved', 1, 'open')
    assert saved['snapshot']['apply_url'] == posting['apply_url'] and 'user_id' not in saved
    assert client.post('/api/v1/jobs/applications', json={'posting_id': posting['id']}, headers=OWNER).json()['id'] == saved['id']
    assert len(client.get('/api/v1/jobs/applications', headers=OWNER).json()['items']) == 1
    assert client.get('/api/v1/jobs/applications', headers=OTHER).json()['items'] == []
    path = '/api/v1/jobs/applications/' + saved['id']
    assert client.patch(path, json={'expected_version': 1, 'status': 'applied'}, headers=OTHER).status_code == 404
    assert client.delete(path, params={'expected_version': 1}, headers=OTHER).status_code == 404
    assert client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'][0]['status'] == 'saved'
    other = client.post('/api/v1/jobs/applications', json={'posting_id': posting['id']}, headers=OTHER).json()
    assert other['id'] != saved['id']


def test_status_updates_keep_history_and_reject_stale_versions(client):
    saved = client.post('/api/v1/jobs/applications', json={'posting_id': first_posting(client)['id']}, headers=OWNER).json()
    path = '/api/v1/jobs/applications/' + saved['id']
    applied = client.patch(path, json={'expected_version': 1, 'status': 'applied'}, headers=OWNER).json()
    assert applied['version'] == 2 and [h['status'] for h in applied['history']] == ['saved', 'applied']
    stale = client.patch(path, json={'expected_version': 1, 'status': 'offer'}, headers=OWNER)
    assert stale.status_code == 409 and stale.json()['code'] == 'conflict'
    assert client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'][0]['status'] == 'applied'
    assert client.patch(path, json={'expected_version': 2, 'status': 'hired?'}, headers=OWNER).status_code == 422
    assert client.delete(path, params={'expected_version': 1}, headers=OWNER).status_code == 409
    assert client.delete(path, params={'expected_version': 2}, headers=OWNER).status_code == 204
    assert client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'] == []
    assert client.patch(path, json={'expected_version': 2, 'status': 'offer'}, headers=OWNER).status_code == 404


def test_tracked_jobs_survive_the_listing_closing_or_being_removed(client):
    posting = first_posting(client)
    saved = client.post('/api/v1/jobs/applications', json={'posting_id': posting['id']}, headers=OWNER).json()
    client.store.postings.update_one({'_id': posting['id']}, {'$set': {'status': 'closed'}})
    assert client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'][0]['posting_status'] == 'closed'
    client.store.postings.delete_one({'_id': posting['id']})
    item = client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'][0]
    assert item['posting_status'] == 'removed' and item['snapshot']['title'] == saved['snapshot']['title']
    updated = client.patch('/api/v1/jobs/applications/' + saved['id'], json={'expected_version': 1, 'status': 'rejected'}, headers=OWNER)
    assert updated.status_code == 200 and updated.json()['posting_status'] == 'removed'


def test_saving_an_unknown_job_fails_clearly(client):
    assert client.post('/api/v1/jobs/applications', json={'posting_id': '0' * 32}, headers=OWNER).status_code == 404
    assert client.post('/api/v1/jobs/applications', json={'posting_id': 'bad'}, headers=OWNER).status_code == 422
    assert client.post('/api/v1/jobs/applications', json={'posting_id': '0' * 32, 'user_id': 'other'}, headers=OWNER).status_code == 422


def test_saved_job_capacity_is_enforced(client, monkeypatch):
    monkeypatch.setattr('app.store.MAX_APPLICATIONS_PER_OWNER', 1)
    items = client.get('/api/v1/jobs/search', headers=OWNER).json()['items']
    assert client.post('/api/v1/jobs/applications', json={'posting_id': items[0]['id']}, headers=OWNER).status_code == 200
    assert client.post('/api/v1/jobs/applications', json={'posting_id': items[0]['id']}, headers=OWNER).status_code == 200
    full = client.post('/api/v1/jobs/applications', json={'posting_id': items[1]['id']}, headers=OWNER)
    assert full.status_code == 413 and full.json()['code'] == 'application_capacity'


def test_storage_must_be_configured(database):
    app = create_app(store=SimpleNamespace(database=None), upstream=SyntheticUpstream())
    with TestClient(app) as test_client:
        response = test_client.get('/api/v1/jobs/applications', headers=OWNER)
    assert response.status_code == 503 and response.json()['code'] == 'storage'


LINK = {'url': 'https://careers.example.com/roles/42?utm_source=mail&ref=a#apply', 'title': ' Markets Intern ', 'company': 'Example Bank', 'job_type': 'internship'}


def test_a_pasted_link_is_saved_cleaned_and_tracked_like_any_other_job(client):
    response = client.post('/api/v1/jobs/applications/link', json=LINK, headers=OWNER)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['source'] == 'link' and saved['status'] == 'saved' and saved['posting_status'] == 'unknown'
    assert saved['snapshot'] == {'title': 'Markets Intern', 'company': 'Example Bank', 'location': '', 'job_type': 'internship',
                                 'listing_url': 'https://careers.example.com/roles/42?ref=a', 'apply_url': 'https://careers.example.com/roles/42?ref=a'}
    assert [item['id'] for item in client.get('/api/v1/jobs/applications', headers=OWNER).json()['items']] == [saved['id']]
    moved = client.patch(f"/api/v1/jobs/applications/{saved['id']}", json={'expected_version': 1, 'status': 'applied'}, headers=OWNER)
    assert moved.status_code == 200 and moved.json()['posting_status'] == 'unknown'
    assert client.delete(f"/api/v1/jobs/applications/{saved['id']}?expected_version=2", headers=OWNER).status_code == 204


def test_saving_the_same_link_again_returns_the_record_and_keeps_owners_apart(client):
    first = client.post('/api/v1/jobs/applications/link', json=LINK, headers=OWNER).json()
    client.patch(f"/api/v1/jobs/applications/{first['id']}", json={'expected_version': 1, 'status': 'applied'}, headers=OWNER)
    again = client.post('/api/v1/jobs/applications/link', json={**LINK, 'url': 'https://CAREERS.example.com/roles/42?ref=a'}, headers=OWNER).json()
    assert again['id'] == first['id'] and again['status'] == 'applied'
    other = client.post('/api/v1/jobs/applications/link', json=LINK, headers=OTHER).json()
    assert other['id'] != first['id'] and other['status'] == 'saved'
    assert len(client.get('/api/v1/jobs/applications', headers=OTHER).json()['items']) == 1


def test_a_link_matching_a_saved_listing_returns_that_listing(client):
    posting = client.get('/api/v1/jobs/search', headers=OWNER).json()['items'][0]
    saved = client.post('/api/v1/jobs/applications', json={'posting_id': posting['id']}, headers=OWNER).json()
    pasted = client.post('/api/v1/jobs/applications/link', json={**LINK, 'url': posting['listing_url']}, headers=OWNER).json()
    assert pasted['id'] == saved['id'] and pasted['source'] == 'listing'


@pytest.mark.parametrize('url', ['http://careers.example.com/a', 'javascript:alert(1)', 'https://user:pw@example.com/a', 'https://example.com:8443/a',
                                 'https://localhost/a', 'https://127.0.0.1/a', 'https://[::1]/a', 'https://printer.local/a', 'not a link'])
def test_unsafe_links_are_refused(client, url):
    assert client.post('/api/v1/jobs/applications/link', json={**LINK, 'url': url}, headers=OWNER).status_code == 422
    assert client.get('/api/v1/jobs/applications', headers=OWNER).json()['items'] == []


@pytest.mark.parametrize('change', [{'title': '   '}, {'company': '<b></b>'}, {'title': 'x' * 201}, {'job_type': 'gig'}, {'owner': 'someone'}])
def test_incomplete_or_unexpected_link_details_are_refused(client, change):
    assert client.post('/api/v1/jobs/applications/link', json={**LINK, **change}, headers=OWNER).status_code == 422


def test_saved_links_count_towards_the_limit(client, monkeypatch):
    monkeypatch.setattr('app.store.MAX_APPLICATIONS_PER_OWNER', 1)
    assert client.post('/api/v1/jobs/applications/link', json=LINK, headers=OWNER).status_code == 200
    assert client.post('/api/v1/jobs/applications/link', json={**LINK, 'url': 'https://careers.example.com/b'}, headers=OWNER).status_code == 413


def test_external_searches_encode_only_the_keywords(client):
    response = client.get('/api/v1/jobs/external-searches', params={'q': '  C++ & SQL #1  '}, headers=OWNER)
    assert response.status_code == 200
    sites = {item['name']: urlsplit(item['url']) for item in response.json()['items']}
    assert list(sites) == ['Prosple', 'Huzzle', 'LinkedIn', 'Indeed']
    assert all(site.scheme == 'https' for site in sites.values())
    assert parse_qs(sites['Prosple'].query)['keywords'] == ['C++ & SQL #1']
    assert parse_qs(sites['Huzzle'].query) == {'search': ['C++ & SQL #1'], 'type': ['jobs']}
    assert parse_qs(sites['LinkedIn'].query) == {'keywords': ['C++ & SQL #1'], 'location': ['Singapore']}
    assert parse_qs(sites['Indeed'].query) == {'q': ['C++ & SQL #1'], 'l': ['Singapore']}


@pytest.mark.parametrize('params', [{}, {'q': '   '}, {'q': 'x' * 121}])
def test_external_searches_need_keywords(client, params):
    assert client.get('/api/v1/jobs/external-searches', params=params, headers=OWNER).status_code == 422


def test_new_routes_require_a_session(client):
    assert client.post('/api/v1/jobs/applications/link', json=LINK).status_code == 401
    assert client.get('/api/v1/jobs/external-searches', params={'q': 'sql'}).status_code == 401

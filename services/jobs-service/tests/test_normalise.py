from datetime import datetime, timezone

import pytest

from app.normalise import build, excerpt, job_type, plain_text, query_terms, safe_url, terms, timestamp, workplace
from jobs_fixtures import GREENHOUSE


@pytest.mark.parametrize('title,employment,expected', [
    ('Software Engineering Intern', ['Full-time'], 'internship'),
    ('Summer Internship 2027', [], 'internship'),
    ('Operations Trainee', [], 'internship'),
    ('Internal Auditor', ['Full-time'], 'full_time'),
    ('International Sales Lead', ['Permanent, Full-time'], 'full_time'),
    ('Graduate Analyst', ['Full-time'], 'graduate'),
    ('Undergraduate Tutor', [], 'unknown'),
    ('Trader', ['Jump Trading - Intern'], 'internship'),
    ('Analyst', ['Temporary, Part-time'], 'temporary'),
    ('Analyst', ['Contract, Full-time'], 'contract'),
    ('Analyst', ['PartTime'], 'part_time'),
    ('Analyst', ['FullTime'], 'full_time'),
    ('Analyst', ['Regular'], 'full_time'),
    ('Analyst', [None, False, 'Standard'], 'unknown'),
])
def test_job_type_prefers_the_title_for_early_career_roles(title, employment, expected):
    assert job_type(title, employment) == expected


def test_workplace_uses_explicit_labels_before_location_text():
    assert workplace('OnSite', 'Remote - Singapore') == 'onsite'
    assert workplace(None, 'Remote - Singapore') == 'remote'
    assert workplace('unspecified', 'Singapore') == 'unknown'


@pytest.mark.parametrize('url,allowed', [
    ('https://jobs.example.test/1', True),
    ('https://jobs.example.test:443/1', True),
    ('http://jobs.example.test/1', False),
    ('javascript:alert(1)', False),
    ('https://user:secret@jobs.example.test/1', False),
    ('https://jobs.example.test:8443/1', False),
    ('https://jobs.example.test:bad/1', False),
    (None, False),
])
def test_only_plain_https_links_reach_the_browser(url, allowed):
    assert (safe_url(url) is not None) is allowed


def test_html_is_reduced_to_visible_text():
    assert plain_text('&lt;p&gt;Hello&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;&lt;li&gt;World&lt;/li&gt;', escaped=True) == 'Hello World'
    assert plain_text(None) == ''


def test_excerpt_is_bounded_and_removes_contact_details():
    assert excerpt('Email jane.tan@example.test or call +65 6123 4567.') == 'Email [email removed] or call [phone removed].'
    long = excerpt('word ' * 200)
    assert len(long) <= 281 and long.endswith('…') and not long.endswith(' …')


def test_terms_keep_symbols_and_do_not_retain_description_word_order():
    index = terms('C++ Developer', 'Synthetic', description='zebra uses C# and .NET; apple reads node.js. Mail a@b.test')
    assert index[:3] == ['c++', 'developer', 'synthetic']
    rest = index[3:]
    assert rest == sorted(rest)
    assert {'c#', '.net', 'node.js', 'zebra'} <= set(rest)
    assert 'a@b.test' not in index and 'b.test' not in index


def test_query_terms_are_bounded():
    assert query_terms(' C++  c++ & SQL ') == ['c++', 'sql']
    assert len(query_terms(' '.join(f'w{n}' for n in range(30)))) == 8


def test_timestamps_become_utc_at_millisecond_precision():
    assert timestamp('2026-10-08T02:58:03.123456-04:00') == datetime(2026, 10, 8, 6, 58, 3, 123000, tzinfo=timezone.utc)
    assert timestamp(1785824225174).tzinfo == timezone.utc
    for invalid in (None, '', 'soon', True, '2026-10-08T02:58:03', 10**30):
        assert timestamp(invalid) is None


@pytest.mark.parametrize('change', [{'title': ''}, {'title': None}, {'location': None}, {'apply_url': 'http://x.test'}, {'external_id': ''}, {'external_id': 5}])
def test_records_missing_required_fields_are_rejected(change):
    raw = {'external_id': '1', 'title': 'Analyst', 'location': 'Singapore', 'apply_url': 'https://x.test/1'}
    assert build(GREENHOUSE, raw) is not None
    assert build(GREENHOUSE, {**raw, **change}) is None

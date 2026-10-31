from app.domain import employment


def test_default_company_suggestions_are_alphabetical_before_limiting(monkeypatch):
    rows = [
        {'id': 'z', 'name': 'Zulu employer', 'employees': 10000},
        {'id': 'b', 'name': 'beta employer', 'employees': 100},
        {'id': 'e', 'name': 'Écho employer', 'employees': 10},
        {'id': 'a', 'name': 'Alpha employer', 'employees': None},
    ]
    monkeypatch.setattr(employment, 'snapshot', lambda: {'companies': rows})
    for query in ('', '   '):
        assert [row['id'] for row in employment.search('companies', query, 3)] == ['a', 'b', 'e']
    assert [row['id'] for row in rows] == ['z', 'b', 'e', 'a']


def test_typed_company_search_preserves_snapshot_ranking(monkeypatch):
    rows = [
        {'id': 'z', 'name': 'Zulu employer'},
        {'id': 'a', 'name': 'Alpha employer'},
    ]
    monkeypatch.setattr(employment, 'snapshot', lambda: {'companies': rows})
    assert employment.search('companies', 'employer', 1) == rows[:1]


def test_default_industry_order_is_preserved(monkeypatch):
    rows = [{'id': 'z', 'name': 'Zulu industry'}, {'id': 'a', 'name': 'Alpha industry'}]
    monkeypatch.setattr(employment, 'snapshot', lambda: {'industries': rows})
    assert employment.search('industries', '', 2) == rows

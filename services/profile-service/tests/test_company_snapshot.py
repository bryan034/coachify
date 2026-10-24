import importlib.util
from pathlib import Path
from app.domain import employment

spec = importlib.util.spec_from_file_location('refresh_companies', Path(__file__).parents[1] / 'scripts' / 'refresh_companies.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def statement(identifier, name, count, as_of=None, rank='NormalRank'):
    row = {'company':{'value':f'https://www.wikidata.org/entity/{identifier}'},'companyLabel':{'value':name},
           'count':{'value':str(count)},'rank':{'value':f'https://wikiba.se/ontology#{rank}'}}
    if as_of:
        row['asOf']={'value':as_of+'T00:00:00Z'}
    return row


def test_snapshot_has_over_5000_unique_ranked_companies_and_singapore_coverage():
    data = employment.snapshot()
    companies = data['companies']
    assert len(companies) >= 5000
    assert len({row['id'] for row in companies}) == len(companies)
    assert len({' '.join(row['name'].casefold().split()) for row in companies}) == len(companies)
    counts = [row['employees'] or 0 for row in companies]
    assert counts == sorted(counts, reverse=True)
    assert sum(count > 0 for count in counts) >= 5000
    assert sum(bool(row.get('singapore_based')) for row in companies) >= 700
    assert data['selection']['singapore_supplement_count'] == sum(bool(row.get('singapore_based')) for row in companies)
    assert data['selection']['ranked_company_count'] == sum(count > 0 for count in counts)
    assert all(not row['employees_as_of'] or row['employees_as_of'] <= data['snapshot_date'] for row in companies)
    for name in ('Walmart','Microsoft','DBS Bank','Singtel','United Overseas Bank','Keppel Ltd.','CapitaLand','ST Engineering','Sembcorp','NTUC FairPrice','Sheng Siong','StarHub','BreadTalk','ComfortDelGro','Venture Corporation','SMRT Corporation','ShopBack'):
        assert any(row['name'] == name for row in companies)


def test_latest_dated_headcount_wins_over_older_larger_and_undated_values():
    rows = [statement('Q1','Synthetic employer',9000,'2020-01-01'),statement('Q1','Synthetic employer',7000,'2024-01-01'),
            statement('Q1','Synthetic employer',9500),statement('Q1','Synthetic employer',12000,'2025-01-01','DeprecatedRank'),
            statement('Q1','Synthetic employer',15000,'2099-01-01')]
    result = refresh.build(rows, [], '2026-10-25')
    assert len(result) == 1
    assert result[0]['employees'] == 7000
    assert result[0]['employees_as_of'] == '2024-01-01'


def test_ranked_search_uses_larger_employers_first_but_manual_supplements_remain(monkeypatch):
    monkeypatch.setattr(employment, 'snapshot', lambda: {'companies': [
        {'id':'large','name':'Synthetic large employer','employees':10000},
        {'id':'small','name':'Synthetic small employer','employees':10},
        {'id':'unknown','name':'Synthetic unknown employer','employees':None}]})
    assert [row['id'] for row in employment.search('companies','synthetic',2)] == ['large','small']
    assert employment.search('companies','unknown',8)[0]['id'] == 'unknown'


def test_anomalous_counts_are_withheld_without_losing_the_company_name():
    rows=[statement('Q1','Synthetic employer',100,'2020-01-01'),statement('Q1','Synthetic employer',1000000,'2024-01-01')]
    result=refresh.build(rows, [], '2026-10-25')
    assert result[0]['employees'] is None
    assert result[0]['employee_count_note']


def test_duplicate_names_empty_labels_zero_and_invalid_employee_counts_are_not_ranked():
    rows=[statement('Q1','Synthetic duplicate',100),statement('Q2','Synthetic duplicate',200),
          statement('Q3','Q3',100),statement('Q4','Synthetic zero',0),statement('Q5','Synthetic invalid','NaN')]
    result=refresh.build(rows, [], '2026-10-25')
    assert len(result) == 1 and result[0]['id'] == 'Q2'


def test_singapore_seed_without_employee_count_remains_searchable_after_refresh(monkeypatch):
    rows=[{'company':{'value':'https://www.wikidata.org/entity/Q1'},'companyLabel':{'value':'Synthetic Singapore employer'},'countryCode':{'value':'SG'}}]
    result=refresh.build(rows,[{'id':'Q1','name':'Synthetic Singapore employer','singapore_based':True}],'2026-10-25')
    assert result[0]['singapore_based'] is True
    assert result[0]['employees'] is None
    monkeypatch.setattr(employment,'snapshot',lambda:{'companies':result})
    assert employment.search('companies','Singapore',8)[0]['name'] == 'Synthetic Singapore employer'

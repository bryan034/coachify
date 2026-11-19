from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

import pytest

from elo_shared import model_budget as budget

PAYLOAD = {'model': 'fixture-model', 'messages': [{'role': 'user', 'content': 'fixture'}], 'max_tokens': 10}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / 'usage.sqlite3'
    monkeypatch.setenv('MODEL_BUDGET_PATH', str(path))
    return path


def test_parallel_calls_have_independent_account_allowances(ledger, monkeypatch):
    monkeypatch.setenv('MODEL_BUDGET_GLOBAL_CALLS_PER_DAY', '1')
    monkeypatch.setenv('MODEL_BUDGET_OWNER_CALLS_PER_DAY', '1')

    def reserve(owner):
        try:
            budget.reserve_provider_call(owner, PAYLOAD)
            return True
        except budget.ModelBudgetExceeded as exc:
            assert 1 <= exc.retry_after <= 86400
            return False

    assert reserve('private-account') and not reserve('private-account')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, (f'owner-{n}' for n in range(10)))) == 10
    with sqlite3.connect(ledger) as conn:
        counters = conn.execute('SELECT subject, calls, units FROM daily_usage').fetchall()
    assert dict((key, calls) for key, calls, _ in counters)['deployment'] == 0
    assert len(counters) == 12
    assert b'private-account' not in ledger.read_bytes() and b'fixture-model' not in ledger.read_bytes()


def test_legacy_ledger_preserves_calls_and_ignores_unit_and_global_budgets(ledger, monkeypatch):
    clock = [datetime(2026, 1, 2, 23, 59, tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, zone):
            return clock[0]
    monkeypatch.setattr(budget, 'datetime', Clock)
    monkeypatch.setenv('MODEL_BUDGET_OWNER_UNITS_PER_DAY', '1')
    monkeypatch.setenv('MODEL_BUDGET_GLOBAL_UNITS_PER_DAY', '1')
    monkeypatch.setenv('MODEL_BUDGET_OWNER_CALLS_PER_DAY', '2')
    budget.reserve_provider_call('other', PAYLOAD)
    with sqlite3.connect(ledger) as conn:
        conn.execute("UPDATE daily_usage SET calls=4000, units=160000000 WHERE subject='deployment'")
        conn.execute('INSERT INTO daily_usage VALUES(?,?,1,8000000)', (budget._owner_hash('owner'), '2026-01-02'))
    budget.reserve_provider_call('owner', {**PAYLOAD, 'max_tokens': 150})
    with pytest.raises(budget.ModelBudgetExceeded) as denied:
        budget.reserve_provider_call('owner', {**PAYLOAD, 'max_tokens': 150})
    assert denied.value.retry_after == 60
    clock[0] = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(budget.ModelBudgetExceeded):
        budget.reserve_provider_call('owner', {**PAYLOAD, 'max_tokens': 150})
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    budget.reserve_provider_call('owner', PAYLOAD)


def test_storage_configuration_missing_identity_and_unbounded_output_fail_closed(ledger, monkeypatch):
    for owner, payload in [(None, PAYLOAD), ('owner', {'messages': []})]:
        with pytest.raises(budget.ModelBudgetUnavailable):
            budget.reserve_provider_call(owner, payload)
    monkeypatch.setenv('MODEL_BUDGET_PATH', ':memory:')
    with pytest.raises(budget.ModelBudgetUnavailable):
        budget.reserve_provider_call('owner', PAYLOAD)
    monkeypatch.setenv('MODEL_BUDGET_PATH', str(ledger / 'missing' / 'daily.sqlite3'))
    with pytest.raises(budget.ModelBudgetUnavailable):
        budget.reserve_provider_call('owner', PAYLOAD)



def test_search_allowance_is_per_account_and_never_spends_model_allowance(ledger, monkeypatch):
    budget.reserve_search('owner', 2)
    budget.reserve_search('owner', 2)
    with pytest.raises(budget.ModelBudgetExceeded) as denied:
        budget.reserve_search('owner', 2)
    assert denied.value.scope == 'owner' and 1 <= denied.value.retry_after <= 86400
    budget.reserve_search('other', 2)
    for _ in range(3):
        budget.reserve_search('unlimited', None)
    with pytest.raises(budget.ModelBudgetExceeded):
        budget.reserve_search('blocked', 0)
    with sqlite3.connect(ledger) as conn:
        assert conn.execute("SELECT calls FROM daily_usage WHERE subject='deployment'").fetchone()[0] == 0
    assert b'owner' not in ledger.read_bytes()


def test_search_counters_reset_on_a_new_utc_day_without_model_calls(ledger, monkeypatch):
    clock = [datetime(2026, 1, 2, 12, tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, zone):
            return clock[0]
    monkeypatch.setattr(budget, 'datetime', Clock)
    budget.reserve_search('owner', 1)
    with pytest.raises(budget.ModelBudgetExceeded):
        budget.reserve_search('owner', 1)
    clock[0] = datetime(2026, 1, 3, tzinfo=timezone.utc)
    budget.reserve_search('owner', 1)


def test_invalid_search_allowance_and_missing_account_fail_closed(ledger):
    with pytest.raises(budget.ModelBudgetUnavailable):
        budget.reserve_search('owner', -1)
    with pytest.raises(budget.ModelBudgetUnavailable):
        budget.reserve_search('', 5)

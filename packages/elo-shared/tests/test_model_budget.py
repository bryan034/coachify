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


def test_parallel_owners_cannot_overdraw_global_allowance_and_denials_rollback(ledger, monkeypatch):
    monkeypatch.setenv('MODEL_BUDGET_GLOBAL_CALLS_PER_DAY', '3')
    monkeypatch.setenv('MODEL_BUDGET_OWNER_CALLS_PER_DAY', '1')

    def reserve(owner):
        try:
            budget.reserve_provider_call(owner, PAYLOAD)
            return True
        except budget.ModelBudgetExceeded as exc:
            assert 1 <= exc.retry_after <= 86400
            return False

    # An owner rejection must not spend the deployment's remaining allowance.
    assert reserve('private-account') and not reserve('private-account')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, (f'owner-{n}' for n in range(10)))) == 2
    with sqlite3.connect(ledger) as conn:
        counters = conn.execute('SELECT subject, calls, units FROM daily_usage').fetchall()
    assert dict((key, calls) for key, calls, _ in counters)['deployment'] == 3
    assert len(counters) == 4
    assert b'private-account' not in ledger.read_bytes() and b'fixture-model' not in ledger.read_bytes()


def test_provider_output_and_input_share_utc_allowance_after_restart(ledger, monkeypatch):
    clock = [datetime(2026, 1, 2, 23, 59, tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, zone):
            return clock[0]
    monkeypatch.setattr(budget, 'datetime', Clock)
    monkeypatch.setenv('MODEL_BUDGET_OWNER_UNITS_PER_DAY', '200')
    budget.reserve_provider_call('owner', PAYLOAD)
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

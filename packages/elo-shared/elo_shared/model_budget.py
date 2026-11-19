"""Reserve model attempts and web searches against durable, per-account UTC-day budgets."""
import hashlib
import math
import os
import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

_OWNER = ContextVar('elo_model_budget_owner', default=None)
LEDGER_PATH = '/var/lib/elo-model-budget/usage.sqlite3'


class ModelBudgetUnavailable(Exception):
    def __init__(self):
        super().__init__('Model usage could not be reserved. Retry when the service is available.')


class ModelBudgetExceeded(Exception):
    def __init__(self, scope, retry_after):
        super().__init__('Your account has reached its daily model allowance. Retry after the next UTC day.')
        self.retry_after = retry_after
        self.scope = scope


@contextmanager
def budget_owner(owner):
    token = _OWNER.set(owner)
    try:
        yield
    finally:
        _OWNER.reset(token)


def current_budget_owner():
    return _OWNER.get()


def _limit(name, default):
    value = int(os.getenv('MODEL_BUDGET_' + name, default))
    if not 0 <= value <= 2**53:
        raise ValueError('Invalid daily allowance')
    return value


def _owner_hash(owner):
    if not isinstance(owner, str) or not owner or len(owner) > 200:
        raise ModelBudgetUnavailable()
    return hashlib.sha256(owner.encode('utf-8')).hexdigest()


def _charge(subject, calls_limit):
    """Atomically check and charge one account in the shared SQLite ledger."""
    path = os.environ.get('MODEL_BUDGET_PATH', LEDGER_PATH)
    if not os.path.isabs(path):
        raise ValueError('Use an absolute path on the persistent budget volume')
    with closing(sqlite3.connect(path, timeout=3)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TABLE IF NOT EXISTS daily_usage (subject TEXT PRIMARY KEY, day TEXT NOT NULL, '
                     'calls INTEGER NOT NULL, units INTEGER NOT NULL)')
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        # A backwards clock must never renew capacity.
        watermark = conn.execute("SELECT day FROM daily_usage WHERE subject='deployment'").fetchone()
        if watermark and day > watermark[0]:
            conn.execute('DELETE FROM daily_usage')
        elif watermark:
            day = watermark[0]
        if not watermark or day > watermark[0]:
            conn.execute("INSERT OR IGNORE INTO daily_usage(subject,day,calls,units) VALUES('deployment',?,0,0)", (day,))
        used = conn.execute('SELECT calls FROM daily_usage WHERE subject=?', (subject,)).fetchone()
        if calls_limit is not None and (used[0] if used else 0) >= calls_limit:
            reset = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1)
            raise ModelBudgetExceeded('owner', max(1, math.ceil((reset - now).total_seconds())))
        conn.execute('INSERT INTO daily_usage(subject,day,calls,units) VALUES(?,?,1,0) '
                     'ON CONFLICT(subject) DO UPDATE SET calls=calls+1', (subject, day))


def reserve_provider_call(owner, payload):
    """Charge one attempt to the account before dispatch; charges are retained on errors."""
    owner_hash = _owner_hash(owner)
    output = next((payload[k] for k in ('max_tokens', 'max_completion_tokens', 'max_output_tokens') if k in payload), None)
    if type(output) is not int or output < 1:
        raise ModelBudgetUnavailable()
    try:
        _charge(owner_hash, _limit('OWNER_CALLS_PER_DAY', 250))
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError) as error:
        raise ModelBudgetUnavailable() from error


def reserve_search(owner, per_account_limit):
    """Charge one public web search to the account's daily search allowance.

    ``per_account_limit`` None means unlimited (the search is still recorded).
    """
    owner_hash = _owner_hash(owner)
    try:
        if per_account_limit is not None and not 0 <= per_account_limit <= 2**53:
            raise ValueError('Invalid daily allowance')
        _charge('search:' + owner_hash, per_account_limit)
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError) as error:
        raise ModelBudgetUnavailable() from error

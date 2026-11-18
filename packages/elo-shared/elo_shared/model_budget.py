"""Reserve each cloud model attempt against one durable, deployment-wide UTC-day budget."""
import hashlib
import json
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
        who = 'Your account has' if scope == 'owner' else 'The service has'
        super().__init__(f'{who} reached its daily model allowance. Retry after the next UTC day.')
        self.retry_after = retry_after


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


def reserve_provider_call(owner, payload):
    """Charge one attempt, including its serialized input bytes and maximum output tokens.

    All services use the same Docker volume. An uncertain commit never permits a
    dispatch. Charges are retained on errors because the provider may have billed them.
    """
    if not isinstance(owner, str) or not owner or len(owner) > 200:
        raise ModelBudgetUnavailable()
    output = next((payload[k] for k in ('max_tokens', 'max_completion_tokens', 'max_output_tokens') if k in payload), None)
    if type(output) is not int or output < 1:
        raise ModelBudgetUnavailable()
    owner_hash = hashlib.sha256(owner.encode('utf-8')).hexdigest()
    try:
        size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) + output
        limits = (
            ('deployment', _limit('GLOBAL_CALLS_PER_DAY', 4000), _limit('GLOBAL_UNITS_PER_DAY', 160_000_000)),
            (owner_hash, _limit('OWNER_CALLS_PER_DAY', 250), _limit('OWNER_UNITS_PER_DAY', 8_000_000)),
        )
        path = os.environ.get('MODEL_BUDGET_PATH', LEDGER_PATH)
        if not os.path.isabs(path):
            raise ValueError('Use an absolute path on the persistent budget volume')
        with closing(sqlite3.connect(path, timeout=3)) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS daily_usage (subject TEXT PRIMARY KEY, day TEXT NOT NULL, '
                         'calls INTEGER NOT NULL, units INTEGER NOT NULL)')
            now = datetime.now(timezone.utc)
            day = now.date().isoformat()
            # The deployment row is also the watermark: a backwards clock must never renew capacity.
            watermark = conn.execute("SELECT day FROM daily_usage WHERE subject='deployment'").fetchone()
            if watermark and day > watermark[0]:
                conn.execute('DELETE FROM daily_usage')
            elif watermark:
                day = watermark[0]
            for subject, calls_limit, units_limit in limits:
                used = conn.execute('SELECT calls, units FROM daily_usage WHERE subject=?', (subject,)).fetchone() or (0, 0)
                if used[0] >= calls_limit or used[1] + size > units_limit:
                    reset = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1)
                    raise ModelBudgetExceeded('deployment' if subject == 'deployment' else 'owner',
                                              max(1, math.ceil((reset - now).total_seconds())))
                conn.execute('INSERT INTO daily_usage(subject,day,calls,units) VALUES(?,?,1,?) '
                             'ON CONFLICT(subject) DO UPDATE SET calls=calls+1, units=units+excluded.units',
                             (subject, day, size))
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError) as error:
        raise ModelBudgetUnavailable() from error

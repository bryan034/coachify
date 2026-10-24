"""Explicit, development-only mapping; data/history remain under their existing owner."""
import re
from pymongo.errors import DuplicateKeyError
from app.core.security import now


def map_legacy_owner(database, settings, account_id, legacy_owner, apply=False):
    if settings.environment != 'development' or settings.mode != 'local_test':
        raise ValueError('Legacy mapping is allowed only in local development mode.')
    if not re.fullmatch(r'local_test:[A-Za-z0-9_-]{1,64}', legacy_owner):
        raise ValueError('Supply the exact old local_test owner, not a Google/email identity.')
    account = database.accounts.find_one({'id': account_id, 'provider': 'local_test', 'email_verified': True})
    if not account:
        raise ValueError('Select an existing verified local account.')
    if account['owner'] == legacy_owner:
        return {'mapped': True, 'changed': False}
    if database.accounts.find_one({'owner': legacy_owner, 'id': {'$ne': account_id}}):
        raise ValueError('This legacy owner is already mapped to another account.')
    if database.profile_versions.find_one({'owner': account['owner']}):
        raise ValueError('The target account already has profile data. Refusing to overwrite or merge it.')
    records = database.profile_versions.count_documents({'owner': legacy_owner})
    if not records:
        raise ValueError('No saved profile/history was found for that legacy owner.')
    if not apply:
        return {'mapped': False, 'changed': False, 'versions': records}
    database.accounts.update_one({'id': account_id, 'owner': account['owner']}, {'$set': {'migration_pending': True}})
    # Reject sessions while maintenance is pending; rerunning after failure is safe.
    database.auth_sessions.update_many({'account_id': account_id}, {'$set': {'revoked': True}})
    try:
        result = database.accounts.update_one({'id': account_id, 'owner': account['owner'], 'migration_pending': True},
            {'$set': {'owner': legacy_owner, 'legacy_mapping_at': now()}, '$unset': {'migration_pending': ''}})
    except DuplicateKeyError as exc:
        raise ValueError('Legacy owner was claimed concurrently. Account remains locked for review.') from exc
    if not result.modified_count:
        raise ValueError('Account mapping changed concurrently. Recheck before retrying.')
    return {'mapped': True, 'changed': True, 'versions': records}

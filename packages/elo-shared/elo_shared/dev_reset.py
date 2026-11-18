"""Development-only "start afresh": delete one account's data from a service database.

Never active outside APP_ENV=development. Shared caches without an owner field (for example job postings)
and the collections a service names in `keep` are left alone."""
import os

OWNER_FIELDS = ('user_id', 'owner', 'account_id')


def dev_reset_enabled():
    return os.getenv('APP_ENV') == 'development'


def reset_owner_data(database, owner, keep=()):
    """Delete every document owned by `owner`; returns {collection: deleted_count} for non-empty deletions."""
    if database is None or not isinstance(owner, str) or not owner:
        return {}
    match = {'$or': [{field: owner} for field in OWNER_FIELDS] + [{'_id': owner}]}
    deleted = {}
    for name in database.list_collection_names():
        if name.startswith('system.') or name in keep:
            continue
        count = database[name].delete_many(match).deleted_count
        if count:
            deleted[name] = count
    return deleted

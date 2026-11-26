"""Mark a synthetic account Premium in an explicitly disposable browser-test stack."""
import json
import os
import sys
from uuid import UUID

from pymongo import MongoClient


def main():
    if os.getenv('ELO_SYNTHETIC_TEST_FIXTURES') != '1':
        raise RuntimeError('Plan fixtures are available only in the disposable test override.')
    if os.environ.get('MONGODB_DATABASE') != 'elo_profile':
        raise ValueError('Unexpected disposable database name.')
    body = json.loads(sys.stdin.read(4096))
    owner = str(UUID(body['owner']))
    if owner != body['owner']:
        raise ValueError('Use a canonical synthetic account id.')
    client = MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000)
    try:
        result = client['elo_profile'].accounts.update_one(
            {'id': owner, 'name': {'$regex': '^Synthetic '}}, {'$set': {'account_type': 'premium'}})
        if result.matched_count != 1:
            raise ValueError('Synthetic account was not found.')
        print(json.dumps({'id': owner, 'account_type': 'premium'}))
    finally:
        client.close()


if __name__ == '__main__':
    main()

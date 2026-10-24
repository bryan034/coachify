"""Run with the Profile environment. Dry run by default; never copy records."""
import argparse
import os
from pymongo import MongoClient
from app.core.auth import auth_settings
from app.domain.legacy import map_legacy_owner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--legacy-owner', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    settings = auth_settings()
    with MongoClient(os.environ['MONGODB_URI'], serverSelectionTimeoutMS=5000) as client:
        database = client[os.getenv('MONGODB_DATABASE', 'coachify_profile')]
        print(map_legacy_owner(database, settings, args.account_id, args.legacy_owner, args.apply))


if __name__ == '__main__':
    main()

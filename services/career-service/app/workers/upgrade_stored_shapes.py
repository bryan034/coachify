"""Rewrite saved Career records into current shapes. Dry run unless --apply is given."""
import argparse
import json
import os
from pymongo import MongoClient
from app.repositories.stored_shapes import StoredShapes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='write the changes instead of counting them')
    args = parser.parse_args(argv)
    with MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000) as client:
        counts = StoredShapes(client[os.getenv('MONGODB_DATABASE', 'elo_career')]).upgrade(args.apply)
    print(json.dumps({'applied': args.apply, 'records': counts}, indent=2))


if __name__ == '__main__':
    main()

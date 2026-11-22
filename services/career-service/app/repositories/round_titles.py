from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from app.repositories.goals import now

TITLE_TIMEOUT_SECONDS = 20
CLAIM_SECONDS = 25


class RoundTitleStore:
    def __init__(self, collection):
        self.rows = collection

    def reserve(self, key):
        row = {'kind': 'round_titles', 'state': 'running', 'deadline': now() + timedelta(seconds=CLAIM_SECONDS), 'titles': {}}
        try:
            result = self.rows.update_one({'_id': key}, {'$setOnInsert': row}, upsert=True)
            return result.upserted_id is not None
        except DuplicateKeyError:
            return False

    def read(self, key):
        return self.rows.find_one({'_id': key})

    def finish(self, key, titles):
        self.rows.update_one({'_id': key, 'state': 'running'}, {'$set': {'state': 'done', 'titles': titles}})

"""Career owns career_goals and operational career_target_selections only."""
from copy import deepcopy
from threading import RLock
from pymongo.errors import DuplicateKeyError
from app.domain.targets import conflict


def empty_selection(owner):
    return {'_id': owner, 'career_target_id': None, 'career_target_version': None,
            'version': 0, 'revision': 0, 'receipts': {}}


class TargetRepository:
    def __init__(self, database):
        self.collection = database.career_goals
        self.selections = database.career_target_selections
        self.collection.create_index([('user_id', 1), ('create_key', 1)], unique=True)
        self.collection.create_index([('user_id', 1), ('created_at', -1), ('_id', -1)])

    def get(self, owner, identifier):
        return self.collection.find_one({'_id': identifier, 'user_id': owner})

    def list(self, owner, after=None):
        query = {'user_id': owner}
        if after is not None:
            query['$or'] = [{'created_at': {'$lt': after['created_at']}},
                {'created_at': after['created_at'], '_id': {'$lt': after['id']}}]
        # Apply the bound on Mongo's cursor before materializing any history.
        return list(self.collection.find(query).sort([('created_at', -1), ('_id', -1)]).limit(21))

    def insert(self, document):
        try: self.collection.insert_one(deepcopy(document))
        except DuplicateKeyError:
            current = self.get(document['user_id'], document['_id'])
            if not current or current['create_fingerprint'] != document['create_fingerprint']:
                raise conflict('This request key was used for different target content.')
            return current
        return deepcopy(document)

    def confirm(self, previous, candidate):
        result = self.collection.replace_one({'_id': previous['_id'], 'user_id': previous['user_id'], 'version': previous['version']}, deepcopy(candidate))
        if not result.modified_count: raise conflict()
        return deepcopy(candidate)

    def selection(self, owner):
        return self.selections.find_one({'_id': owner}) or empty_selection(owner)

    def select(self, previous, candidate):
        if previous['revision'] == 0:
            try: self.selections.insert_one(deepcopy(candidate))
            except DuplicateKeyError as exc: raise conflict() from exc
        elif not self.selections.replace_one({'_id': previous['_id'], 'revision': previous['revision']}, deepcopy(candidate)).modified_count:
            raise conflict()
        return deepcopy(candidate)


class MemoryTargetRepository:
    """Explicit test adapter; never a production fallback."""
    def __init__(self): self.documents, self.selections, self.lock = {}, {}, RLock()

    def get(self, owner, identifier):
        with self.lock:
            document = self.documents.get(identifier)
            return deepcopy(document) if document and document['user_id'] == owner else None

    def list(self, owner, after=None):
        with self.lock:
            rows = (doc for doc in self.documents.values() if doc['user_id'] == owner and
                (after is None or (doc['created_at'], doc['_id']) < (after['created_at'], after['id'])))
            return [deepcopy(doc) for doc in sorted(rows, key=lambda doc: (doc['created_at'], doc['_id']), reverse=True)[:21]]

    def insert(self, document):
        with self.lock:
            current = self.documents.get(document['_id'])
            if current:
                if current['create_fingerprint'] != document['create_fingerprint']: raise conflict('This request key was used for different target content.')
                return deepcopy(current)
            self.documents[document['_id']] = deepcopy(document)
            return deepcopy(document)

    def confirm(self, previous, candidate):
        with self.lock:
            current = self.documents.get(previous['_id'])
            if not current or current['version'] != previous['version']: raise conflict()
            self.documents[previous['_id']] = deepcopy(candidate)
            return deepcopy(candidate)

    def selection(self, owner):
        with self.lock: return deepcopy(self.selections.get(owner, empty_selection(owner)))

    def select(self, previous, candidate):
        with self.lock:
            if self.selection(previous['_id'])['revision'] != previous['revision']: raise conflict()
            self.selections[previous['_id']] = deepcopy(candidate)
            return deepcopy(candidate)

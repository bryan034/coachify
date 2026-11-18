"""The latest saved graph state per CV. Each save replaces the one before it."""
from copy import deepcopy
from threading import RLock


class ExtractionStateStore:
    def __init__(self, database):
        self.collection = database.cv_extraction_states

    def get(self, identifier):
        return self.collection.find_one({'_id': identifier, 'erased': {'$ne': True}})

    def save(self, document):
        # The marker and the checkpoint share one MongoDB document. A late write
        # cannot recreate CV text once erasure has won, even if its worker dies.
        self.collection.update_one({'_id': document['_id']}, [{'$replaceWith': {
            '$cond': [{'$eq': ['$erased', True]}, '$$ROOT', {'$literal': document}]
        }}], upsert=True)

    def erase(self, identifier):
        self.collection.replace_one({'_id': identifier}, {'_id': identifier, 'erased': True}, upsert=True)

    def page(self, after, limit):
        query = {'_id': {'$gt': after}} if after is not None else {}
        return list(self.collection.find(query, {'erased': 1}).sort('_id', 1).limit(limit))

    def set_writes(self, identifier, checkpoint_id, writes):
        self.collection.update_one({'_id': identifier, 'checkpoint_id': checkpoint_id, 'erased': {'$ne': True}},
                                   {'$set': {'writes': writes}})

    def discard(self, identifier):
        self.collection.update_one({'_id': identifier, 'erased': {'$ne': True}}, {'$set': {'discarded': True}})

    def delete(self, identifier):
        self.collection.delete_one({'_id': identifier, 'erased': {'$ne': True}})


class MemoryExtractionStateStore:
    def __init__(self):
        self.documents = {}
        self.lock = RLock()

    def get(self, identifier):
        with self.lock:
            row = self.documents.get(identifier)
            if row and not row.get('erased'): return deepcopy(row)

    def save(self, document):
        with self.lock:
            if not self.documents.get(document['_id'], {}).get('erased'):
                self.documents[document['_id']] = deepcopy(document)

    def erase(self, identifier):
        with self.lock: self.documents[identifier] = {'_id': identifier, 'erased': True}

    def page(self, after, limit):
        with self.lock:
            ids = sorted(k for k in self.documents if after is None or k > after)[:limit]
            return [{'_id': k, 'erased': self.documents[k].get('erased', False)} for k in ids]

    def set_writes(self, identifier, checkpoint_id, writes):
        with self.lock:
            document = self.documents.get(identifier)
            if document and not document.get('erased') and document['checkpoint_id'] == checkpoint_id:
                document['writes'] = deepcopy(writes)

    def discard(self, identifier):
        with self.lock:
            document = self.documents.get(identifier)
            if document and not document.get('erased'): document['discarded'] = True

    def delete(self, identifier):
        with self.lock:
            if not self.documents.get(identifier, {}).get('erased'): self.documents.pop(identifier, None)

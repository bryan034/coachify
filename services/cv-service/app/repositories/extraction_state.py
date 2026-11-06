"""The latest saved graph state per CV. Each save replaces the one before it."""
from copy import deepcopy
from threading import RLock


class ExtractionStateStore:
    def __init__(self, database):
        self.collection = database.cv_extraction_states

    def get(self, identifier):
        return self.collection.find_one({'_id': identifier})

    def save(self, document):
        self.collection.replace_one({'_id': document['_id']}, document, upsert=True)

    def set_writes(self, identifier, checkpoint_id, writes):
        self.collection.update_one({'_id': identifier, 'checkpoint_id': checkpoint_id}, {'$set': {'writes': writes}})

    def discard(self, identifier):
        self.collection.update_one({'_id': identifier}, {'$set': {'discarded': True}})

    def delete(self, identifier):
        self.collection.delete_one({'_id': identifier})


class MemoryExtractionStateStore:
    def __init__(self):
        self.documents = {}
        self.lock = RLock()

    def get(self, identifier):
        with self.lock: return deepcopy(self.documents.get(identifier))

    def save(self, document):
        with self.lock: self.documents[document['_id']] = deepcopy(document)

    def set_writes(self, identifier, checkpoint_id, writes):
        with self.lock:
            document = self.documents.get(identifier)
            if document and document['checkpoint_id'] == checkpoint_id: document['writes'] = deepcopy(writes)

    def discard(self, identifier):
        with self.lock:
            if identifier in self.documents: self.documents[identifier]['discarded'] = True

    def delete(self, identifier):
        with self.lock: self.documents.pop(identifier, None)

"""The latest saved graph state per CV. Each save replaces the one before it."""


class ExtractionStateStore:
    def __init__(self, database):
        self.collection = database.cv_extraction_states

    def get(self, identifier):
        return self.collection.find_one({'_id': identifier, 'erased': {'$ne': True}})

    def save(self, document):
        # The marker and the checkpoint share one MongoDB document.
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

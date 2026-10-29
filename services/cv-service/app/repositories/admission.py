"""One bounded compare-and-set ledger; no transactions or expiring counters."""
from copy import deepcopy
from threading import RLock
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern


class AdmissionLedger:
    def __init__(self, database):
        self.collection = database.cv_upload_capacity.with_options(write_concern=WriteConcern(w=1, j=True))

    def read(self):
        return self.collection.find_one({'_id': 'uploads'})

    def replace(self, previous, document):
        if previous is None:
            try:
                self.collection.insert_one(deepcopy(document))
                return True
            except DuplicateKeyError:
                return False
        return bool(self.collection.replace_one(
            {'_id': 'uploads', 'revision': previous['revision']}, deepcopy(document)).modified_count)


class MemoryAdmissionLedger:
    def __init__(self):
        self.document = None
        self.lock = RLock()

    def read(self):
        with self.lock:
            return deepcopy(self.document)

    def replace(self, previous, document):
        with self.lock:
            if (self.document is None) != (previous is None): return False
            if previous is not None and self.document['revision'] != previous['revision']: return False
            self.document = deepcopy(document)
            return True

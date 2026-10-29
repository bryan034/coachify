"""Bounded upload admission and recovery for standalone MongoDB/local files.

One ledger CAS reserves both a record and its bytes. Files and MongoDB are not a
transaction: an uncertain publication stays charged until recovery holds the
same file lock and establishes whether the CV record committed.
"""
from copy import deepcopy
from heapq import nsmallest
from time import time
from uuid import UUID, uuid4
from bson import BSON
from app.domain.errors import Conflict, CvError


MAX_LEDGER_ENTRIES = 20_000
MAX_LEDGER_BYTES = 12 * 1024 * 1024
BOOTSTRAP_LOCK = '00000000-0000-0000-0000-000000000000'


class CapacityError(CvError):
    code = 'cv_capacity_exceeded'

    def __init__(self, detail):
        super().__init__(detail, 409)


class CapacityUnavailable(CvError):
    code = 'cv_capacity_unavailable'

    def __init__(self):
        super().__init__('CV storage admission is recovering or unavailable. Keep your file and retry shortly.', 503)


class UploadCapacity:
    def __init__(self, repository, files, settings):
        self.repository, self.files, self.settings = repository, files, settings
        self.ledger = repository.admission
        self.recovery_cursor = None
        self.orphan_cursor = None
        self.ensure()

    def ensure(self):
        if self.ledger.read() is not None: return
        with self.files.lock(BOOTSTRAP_LOCK):
            if self.ledger.read() is not None: return
            entries, blocked = {}, None
            for record in self.repository.capacity_records(MAX_LEDGER_ENTRIES + 1):
                if len(entries) == MAX_LEDGER_ENTRIES:
                    blocked = 'Existing saved records exceed the bounded storage ledger. Existing CVs remain readable; an administrator must review capacity.'
                    break
                identifier, owner = record['_id'], record.get('user_id')
                try: UUID(identifier)
                except (ValueError, TypeError, AttributeError):
                    blocked = 'Existing CV storage needs an administrator review before new uploads.'
                    break
                if not isinstance(owner, str) or not 1 <= len(owner) <= 200:
                    blocked = 'Existing CV storage needs an administrator review before new uploads.'
                    break
                entries[identifier] = {'owner': owner, 'record': True,
                    'bytes': self.files.size(identifier), 'generation': str(uuid4()),
                    'state': 'published', 'key': '', 'fingerprint': '', 'at': time()}
            # Orphans need durable identities too: a crash after unlink but before
            # credit must leave enough information to finish recovery. Overflow
            # stays conservatively charged and blocks admission for admin review.
            untracked = 0
            for path in self.files.storage_files():
                identifier = self.files.stored_identifier(path)
                if identifier in entries: continue
                if len(entries) == MAX_LEDGER_ENTRIES:
                    untracked += path.stat().st_size
                    blocked = blocked or 'Existing upload storage exceeds the bounded ledger. Existing CVs remain readable; an administrator must review capacity.'
                    continue
                entries[identifier] = {'owner': None, 'record': False,
                    'bytes': self.files.size(identifier), 'generation': str(uuid4()),
                    'state': 'orphan', 'key': '', 'fingerprint': '', 'at': path.stat().st_mtime}
            document = {'_id': 'uploads', 'revision': 1, 'entries': entries,
                        'untracked_bytes': untracked, 'blocked': blocked}
            if len(BSON.encode(document)) > MAX_LEDGER_BYTES:
                document.update(entries={}, untracked_bytes=sum(path.stat().st_size for path in self.files.storage_files()),
                    blocked='Existing CV storage exceeds the bounded ledger. Existing CVs remain readable; an administrator must review capacity.')
            self.ledger.replace(None, document)

    def _change(self, transform):
        for _ in range(30):
            previous = self.ledger.read()
            if previous is None: raise CapacityUnavailable()
            document = deepcopy(previous)
            result = transform(document)
            if document == previous: return result
            document['revision'] += 1
            if len(BSON.encode(document)) > MAX_LEDGER_BYTES: raise CapacityUnavailable()
            if self.ledger.replace(previous, document): return result
        raise CapacityUnavailable()

    def entry(self, identifier):
        document = self.ledger.read()
        if document is None: raise CapacityUnavailable()
        return document['entries'].get(identifier)

    def reserve(self, owner, identifier, byte_count, key, fingerprint, existing=False):
        """Caller holds the file lock through publication and commit/recovery."""
        def change(document):
            if document.get('blocked'): raise CapacityError(document['blocked'])
            entries = document['entries']
            current = entries.get(identifier)
            if current:
                if current['owner'] != owner: raise Conflict('The upload reservation belongs to another source.')
                if current['state'] == 'pending': raise CapacityUnavailable()
                if current['bytes']:
                    if current['bytes'] != byte_count: raise Conflict('The saved original size changed.')
                    return current['generation']
            owner_entries = [entry for entry in entries.values() if entry['owner'] == owner]
            new_record = current is None
            saved_count = sum(entry['owner'] is not None for entry in entries.values())
            if new_record and (saved_count >= self.settings.max_saved_cvs_global or len(entries) >= MAX_LEDGER_ENTRIES):
                raise CapacityError('Saved CV capacity is full. Existing sources remain available; contact the administrator before uploading another CV.')
            if new_record and len(owner_entries) >= self.settings.max_saved_cvs_per_owner:
                raise CapacityError('You have reached the saved CV limit. Existing sources remain available; reuse a saved source or contact the administrator.')
            owner_bytes = sum(entry['bytes'] for entry in owner_entries)
            global_bytes = sum(entry['bytes'] for entry in entries.values()) + document['untracked_bytes']
            if owner_bytes + byte_count > self.settings.max_original_bytes_per_owner:
                raise CapacityError('Your private upload storage is full. Existing CVs are safe; wait for original-file expiry before uploading more.')
            if global_bytes + byte_count > self.settings.max_original_bytes_global:
                raise CapacityError('Private upload storage is full. Existing CVs are safe; retry after original-file cleanup or contact the administrator.')
            generation = str(uuid4())
            entries[identifier] = {'owner': owner, 'record': bool(current or existing), 'bytes': byte_count,
                'generation': generation, 'state': 'pending', 'key': key, 'fingerprint': fingerprint, 'at': time()}
            return generation
        return self._change(change)

    def commit(self, identifier, generation):
        def change(document):
            entry = document['entries'].get(identifier)
            if not entry or entry['generation'] != generation: raise CapacityUnavailable()
            entry.update(record=True, state='published', key='', fingerprint='')
        self._change(change)

    def release_bytes(self, identifier, generation, byte_count=0):
        """Only call after durable physical removal while holding the file lock."""
        def change(document):
            entry = document['entries'].get(identifier)
            if entry is None:
                document['untracked_bytes'] = max(0, document['untracked_bytes'] - byte_count)
            elif entry['generation'] == generation:
                if entry['record']:
                    entry.update(bytes=0, state='published', key='', fingerprint='')
                else: del document['entries'][identifier]
            else: raise CapacityUnavailable()
        self._change(change)

    def recover_one(self, identifier):
        """A lock, never an elapsed lease, proves a writer is no longer active."""
        with self.files.lock(identifier, blocking=False) as acquired:
            if not acquired: return
            entry = self.entry(identifier)
            if entry is None or entry['state'] not in {'pending', 'orphan'}: return
            if entry['state'] == 'orphan' and entry['at'] > time() - 3600: return
            record = self.repository.capacity_record(identifier)
            if entry['state'] == 'orphan':
                if record is not None and record.get('original_available'): return
                self.files.remove(identifier)
                self.release_bytes(identifier, entry['generation'])
                return
            if record is not None and record.get('user_id') != entry['owner']: raise CapacityUnavailable()
            if record is not None and record.get('original_available') and record.get('storage_generation') == entry['generation']:
                if self.files.exists(identifier):
                    self.commit(identifier, entry['generation'])
                    return
                # Never credit a committed original before its durable removal.
            self.files.remove(identifier)
            if record is not None: self.commit(identifier, entry['generation'])
            self.release_bytes(identifier, entry['generation'])

    def recover(self):
        document = self.ledger.read()
        if document is None: raise CapacityUnavailable()
        pending = nsmallest(10, (identifier for identifier, entry in document['entries'].items()
            if (entry['state'] == 'pending' or entry['state'] == 'orphan' and entry['at'] <= time() - 3600)
            and (self.recovery_cursor is None or identifier > self.recovery_cursor)))
        if not pending:
            self.recovery_cursor = None
            return
        for identifier in pending:
            self.recovery_cursor = identifier
            try: self.recover_one(identifier)
            except Exception:
                # Leave the reservation charged. Advance to other owners' records.
                continue

    def cleanup_orphans(self, before):
        paths = nsmallest(100, (path for path in self.files.storage_files()
            if self.orphan_cursor is None or path.name > self.orphan_cursor), key=lambda path: path.name)
        if not paths:
            self.orphan_cursor = None
            return
        for path in paths:
            self.orphan_cursor = path.name
            try:
                identifier = self.files.stored_identifier(path)
                with self.files.lock(identifier, blocking=False) as acquired:
                    if not acquired or not path.exists() or path.stat().st_mtime >= before: continue
                    entry = self.entry(identifier)
                    if entry is not None and entry['state'] == 'pending': continue
                    record = self.repository.capacity_record(identifier)
                    if record is not None and record.get('original_available'): continue
                    size = self.files.size(identifier)
                    self.files.remove(identifier)
                    self.release_bytes(identifier, entry['generation'] if entry else None, size)
            except Exception:
                continue

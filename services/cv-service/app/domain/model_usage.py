"""Fair bounded provider admission, held inside the synchronous provider call.

The slot guard is an OS lock, not an expiring lease: cancelling an async waiter
cannot release capacity while its provider thread continues. A short gate makes
slot-owner tags consistent across processes; it is never held during MongoDB or
provider I/O. Every process must share the volume and capacity configuration.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
from bson import BSON


MAX_OWNER_ENTRIES = 10_000
MAX_COUNTER_BYTES = 2 * 1024 * 1024


class ModelAdmissionError(ValueError):
    pass


UNAVAILABLE = 'CV model usage could not be reserved. Your saved inputs are safe; retry shortly.'
OWNER_BUSY = 'Another CV model request for your account is still running. Your saved inputs are safe; retry shortly.'
GLOBAL_BUSY = 'CV model processing is busy. Your saved inputs are safe; retry shortly.'
OWNER_DAILY = 'Your daily CV model-call limit has been reached. Your saved inputs are safe; retry after the next UTC day.'
GLOBAL_DAILY = 'The daily CV model-call capacity has been reached. Your saved inputs are safe; retry after the next UTC day.'


def utc_day(): return datetime.now(timezone.utc).date().isoformat()


class ModelUsage:
    def __init__(self, store, directory, settings, day=utc_day):
        self.store, self.settings, self.day = store, settings, day
        self.directory = Path(directory) / '.model-slots'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def _slot(self, owner_hash):
        gate, selected = None, None
        descriptors = []
        try:
            gate = os.open(self.directory / 'gate', os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(gate, fcntl.LOCK_EX)
            owner_active = 0
            for index in range(self.settings.model_concurrent_global):
                descriptor = os.open(self.directory / str(index), os.O_RDWR | os.O_CREAT, 0o600)
                descriptors.append(descriptor)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if selected is None: selected = descriptor
                except BlockingIOError:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    tag = os.read(descriptor, 65)
                    if re.fullmatch(rb'[0-9a-f]{64}', tag) is None:
                        raise ModelAdmissionError(UNAVAILABLE)
                    if tag.decode('ascii') == owner_hash: owner_active += 1
            if owner_active >= self.settings.model_concurrent_per_owner: raise ModelAdmissionError(OWNER_BUSY)
            if selected is None: raise ModelAdmissionError(GLOBAL_BUSY)
            os.lseek(selected, 0, os.SEEK_SET)
            os.ftruncate(selected, 0)
            if os.write(selected, owner_hash.encode('ascii')) != 64: raise ModelAdmissionError(UNAVAILABLE)
            descriptors.remove(selected)
            return selected
        except ModelAdmissionError:
            raise
        except OSError as exc:
            raise ModelAdmissionError(UNAVAILABLE) from exc
        finally:
            for descriptor in descriptors: os.close(descriptor)
            if gate is not None:
                fcntl.flock(gate, fcntl.LOCK_UN)
                os.close(gate)

    @staticmethod
    def _validate(document):
        if (not isinstance(document, dict) or document.get('_id') != 'daily'
                or type(document.get('revision')) is not int or document['revision'] < 1
                or type(document.get('total')) is not int or document['total'] < 0
                or not isinstance(document.get('owners'), dict)
                or len(document['owners']) > MAX_OWNER_ENTRIES):
            raise ModelAdmissionError(UNAVAILABLE)
        try:
            if date.fromisoformat(document['day']).isoformat() != document['day']: raise ValueError
        except (ValueError, TypeError, KeyError) as exc: raise ModelAdmissionError(UNAVAILABLE) from exc
        for owner_hash, count in document['owners'].items():
            if not isinstance(owner_hash, str) or re.fullmatch('[0-9a-f]{64}', owner_hash) is None or type(count) is not int or count < 1:
                raise ModelAdmissionError(UNAVAILABLE)
        if sum(document['owners'].values()) != document['total']: raise ModelAdmissionError(UNAVAILABLE)

    def _consume(self, owner_hash):
        today = self.day()
        if date.fromisoformat(today).isoformat() != today: raise ModelAdmissionError(UNAVAILABLE)
        for _ in range(30):
            previous = self.store.read()
            if previous is None:
                document = {'_id': 'daily', 'revision': 0, 'day': today, 'total': 0, 'owners': {}}
            else:
                self._validate(previous)
                document = deepcopy(previous)
                if today > previous['day']:
                    document.update(day=today, total=0, owners={})
                # A backwards clock never resets or rewinds a consumed window.
            count = document['owners'].get(owner_hash, 0)
            if count >= self.settings.model_calls_per_owner_per_day: raise ModelAdmissionError(OWNER_DAILY)
            if document['total'] >= self.settings.model_calls_global_per_day: raise ModelAdmissionError(GLOBAL_DAILY)
            if not count and len(document['owners']) >= MAX_OWNER_ENTRIES: raise ModelAdmissionError(GLOBAL_DAILY)
            document['owners'][owner_hash] = count + 1
            document['total'] += 1
            document['revision'] += 1
            if len(BSON.encode(document)) > MAX_COUNTER_BYTES: raise ModelAdmissionError(UNAVAILABLE)
            if self.store.replace(previous, document): return
        raise ModelAdmissionError(UNAVAILABLE)

    def run(self, owner, callback, *args, configured=True):
        if configured is False:
            # Preserve the provider's normal disabled-configuration response.
            return callback(*args)
        if not isinstance(owner, str) or not 1 <= len(owner) <= 200: raise ModelAdmissionError(UNAVAILABLE)
        owner_hash = hashlib.sha256(owner.encode('utf-8')).hexdigest()
        descriptor = self._slot(owner_hash)
        try:
            try: self._consume(owner_hash)
            except ModelAdmissionError: raise
            except Exception as exc:
                # A write may have committed. Never refund or call the provider
                # after an uncertain reservation, and do not disclose DB details.
                raise ModelAdmissionError(UNAVAILABLE) from exc
            return callback(*args)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

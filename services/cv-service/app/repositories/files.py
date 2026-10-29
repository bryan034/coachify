"""Originals are private, finite-lived retry material, not public file URLs."""
import os
import fcntl
import hashlib
from contextlib import contextmanager
from pathlib import Path
from threading import RLock, local
from uuid import UUID


class FileStore:
    def __init__(self, path):
        self.root = Path(path)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.lock_root = self.root / '.locks'
        self.lock_root.mkdir(exist_ok=True, mode=0o700)
        self._locks = [RLock() for _ in range(256)]
        self._local = local()

    def path(self, identifier):
        # User filenames never participate in filesystem paths.
        UUID(identifier)
        return self.root / identifier

    @contextmanager
    def lock(self, identifier, blocking=True):
        """Bounded stable lock files; collisions merely serialize unrelated CVs.

        Never unlink lock files: replacing their inodes would defeat flock across
        processes. All deployments must share this POSIX-locking upload volume.
        """
        UUID(identifier)
        stripe = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) % 256
        mutex = self._locks[stripe]
        acquired = mutex.acquire(blocking=blocking)
        if not acquired:
            yield False
            return
        held = getattr(self._local, 'held', {})
        self._local.held = held
        descriptor = None
        try:
            if stripe not in held:
                descriptor = os.open(self.lock_root / str(stripe), os.O_RDWR | os.O_CREAT, 0o600)
                try: fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                except BlockingIOError:
                    yield False
                    return
            held[stripe] = held.get(stripe, 0) + 1
            try: yield True
            finally:
                held[stripe] -= 1
                if not held[stripe]: del held[stripe]
        finally:
            if descriptor is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            mutex.release()

    def temporary(self, identifier):
        return self.root / ('.upload-' + self.path(identifier).name)

    def write(self, identifier, data):
        with self.lock(identifier):
            path, temporary = self.path(identifier), self.temporary(identifier)
            if path.exists():
                if path.read_bytes() != data: raise FileExistsError('Saved original bytes differ.')
                return
            # A crashed writer's deterministic temporary is covered by the same
            # reservation. Its replacement never consumes a second file allowance.
            temporary.unlink(missing_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, 'wb') as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
                self._sync_directory()
            finally:
                temporary.unlink(missing_ok=True)

    def _sync_directory(self):
        descriptor = os.open(self.root, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

    def read(self, identifier):
        with self.lock(identifier): return self.path(identifier).read_bytes()

    def remove(self, identifier):
        with self.lock(identifier):
            self.path(identifier).unlink(missing_ok=True)
            self.temporary(identifier).unlink(missing_ok=True)
            self._sync_directory()

    def exists(self, identifier): return self.path(identifier).is_file()

    def size(self, identifier):
        # A temporary and final name must never contain separate live copies.
        return sum(path.stat().st_size for path in (self.path(identifier), self.temporary(identifier)) if path.is_file())

    def originals(self):
        for path in self.root.iterdir():
            try: UUID(path.name)
            except ValueError: continue
            if path.is_file(): yield path

    @staticmethod
    def stored_identifier(path):
        value = path.name.removeprefix('.upload-')
        UUID(value)
        return value

    def storage_files(self):
        for path in self.root.iterdir():
            try: self.stored_identifier(path)
            except ValueError: continue
            if path.is_file(): yield path

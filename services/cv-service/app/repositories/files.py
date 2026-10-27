"""Originals are private, finite-lived retry material, not public file URLs."""
import os
from pathlib import Path
from uuid import UUID, uuid4


class FileStore:
    def __init__(self, path):
        self.root = Path(path)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def path(self, identifier):
        # User filenames never participate in filesystem paths.
        UUID(identifier)
        return self.root / identifier

    def write(self, identifier, data):
        path = self.path(identifier)
        temporary = self.path(str(uuid4()))
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                # Publish complete immutable bytes atomically. Concurrent exact-byte
                # resupplies may reuse them; no worker ever observes a partial file.
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != data: raise
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, identifier): return self.path(identifier).read_bytes()
    def remove(self, identifier): self.path(identifier).unlink(missing_ok=True)
    def exists(self, identifier): return self.path(identifier).is_file()

    def cleanup_orphans(self, tracked, before):
        for path in self.root.iterdir():
            try: UUID(path.name)
            except ValueError: continue
            if path.is_file() and path.name not in tracked and path.stat().st_mtime < before:
                path.unlink(missing_ok=True)

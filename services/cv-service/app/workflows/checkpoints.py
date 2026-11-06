"""LangGraph checkpointer that keeps only the newest state for each CV."""
from time import time
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP

# LangGraph records a failed step's exception as a write. Its text can quote model
# output, and a failed step reruns on resume anyway, so it is never saved.
ERROR_CHANNEL = '__error__'


class LatestStateSaver(BaseCheckpointSaver):
    """A saved state only applies to its own thread, so a new upload or workflow version starts fresh."""

    def __init__(self, store, cv_id, owner, may_write=None):
        super().__init__()
        self.store, self.cv_id, self.owner = store, cv_id, owner
        self.may_write = may_write or (lambda: True)

    def _row(self, config):
        row = self.store.get(self.cv_id)
        wanted = config['configurable'].get('checkpoint_id')
        if (not row or row.get('discarded') or row['thread_id'] != config['configurable']['thread_id']
                or (wanted and wanted != row['checkpoint_id'])):
            return None
        return row

    def _load(self, stored):
        return self.serde.loads_typed((stored['type'], bytes(stored['data'])))

    def _dump(self, value):
        kind, data = self.serde.dumps_typed(value)
        return {'type': kind, 'data': data}

    def get_tuple(self, config):
        row = self._row(config)
        if not row: return None
        return CheckpointTuple(
            config={'configurable': {'thread_id': row['thread_id'], 'checkpoint_ns': '', 'checkpoint_id': row['checkpoint_id']}},
            checkpoint=self._load(row['checkpoint']), metadata=self._load(row['metadata']), parent_config=None,
            pending_writes=[(write['task_id'], write['channel'], self._load(write['value'])) for write in row['writes']])

    def list(self, config, *, filter=None, before=None, limit=None):
        found = self.get_tuple(config) if config else None
        if found: yield found

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = config['configurable']['thread_id']
        saved = {'configurable': {'thread_id': thread_id, 'checkpoint_ns': '', 'checkpoint_id': checkpoint['id']}}
        # A worker that lost its lease, or a CV deleted mid-run, must not write again.
        if self.may_write():
            self.store.save({'_id': self.cv_id, 'user_id': self.owner, 'thread_id': thread_id, 'checkpoint_id': checkpoint['id'],
                             'checkpoint': self._dump(checkpoint), 'metadata': self._dump(metadata), 'writes': [], 'updated_at': time()})
        return saved

    def put_writes(self, config, writes, task_id, task_path=''):
        row = self._row(config)
        if not row or not self.may_write(): return
        kept = {(write['task_id'], write['idx']): write for write in row['writes']}
        for position, (channel, value) in enumerate(writes):
            if channel == ERROR_CHANNEL: continue
            index = WRITES_IDX_MAP.get(channel, position)
            kept[(task_id, index)] = {'task_id': task_id, 'idx': index, 'channel': channel, 'value': self._dump(value)}
        self.store.set_writes(self.cv_id, row['checkpoint_id'], list(kept.values()))

    def delete_thread(self, thread_id):
        row = self.store.get(self.cv_id)
        if row and row['thread_id'] == thread_id: self.store.delete(self.cv_id)

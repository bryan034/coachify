import pytest
from fastapi.testclient import TestClient
from elo_shared import runtime
from elo_shared.dev_reset import reset_owner_data
from elo_shared.runtime import MemoryStore, application


class FakeCollection:
    def __init__(self, rows): self.rows = rows
    def delete_many(self, match):
        keep = [r for r in self.rows if not any(all(r.get(k) == v for k, v in clause.items()) for clause in match['$or'])]
        count = len(self.rows) - len(keep); self.rows[:] = keep
        return type('Result', (), {'deleted_count': count})()


class FakeDatabase:
    def __init__(self, **collections): self.collections = {k: FakeCollection(v) for k, v in collections.items()}
    def list_collection_names(self): return list(self.collections)
    def __getitem__(self, name): return self.collections[name]


def test_reset_deletes_only_the_owners_rows_and_honours_keep():
    db = FakeDatabase(goals=[{'user_id': 'a'}, {'user_id': 'b'}], state=[{'_id': 'a'}, {'_id': 'b'}],
                      jobs=[{'owner': 'a'}], postings=[{'source_id': 'x'}], system_x=[{'owner': 'a'}])
    assert reset_owner_data(db, 'a', keep=('system_x',)) == {'goals': 1, 'state': 1, 'jobs': 1}
    assert db['goals'].rows == [{'user_id': 'b'}] and db['postings'].rows == [{'source_id': 'x'}] and db['system_x'].rows
    assert reset_owner_data(db, '') == {} and reset_owner_data(None, 'a') == {}


class Upstream:
    async def account(self, token): return {'id': 'a' if token.endswith('a') else 'b'}


def client(monkeypatch, enabled):
    monkeypatch.setattr(runtime, 'dev_reset_enabled', lambda: enabled)
    store = MemoryStore(); store.data.update(a={'_id': 'a'}, b={'_id': 'b'}); store.results[('a', 'r1')] = {}; store.results[('b', 'r2')] = {}
    return TestClient(application('T', 'ROADMAP', store=store, upstream=Upstream(), model=object())), store


def test_route_resets_only_the_caller_in_development(monkeypatch):
    http, store = client(monkeypatch, True)
    with http:
        assert http.post('/api/v1/roadmaps/dev/reset').status_code == 401
        assert http.post('/api/v1/roadmaps/dev/reset', headers={'Authorization': 'Bearer a'}).status_code == 200
    assert list(store.data) == ['b'] and list(store.results) == [('b', 'r2')]


def test_route_is_absent_outside_development(monkeypatch):
    http, store = client(monkeypatch, False)
    with http:
        assert http.post('/api/v1/roadmaps/dev/reset', headers={'Authorization': 'Bearer a'}).status_code == 404
    assert 'a' in store.data

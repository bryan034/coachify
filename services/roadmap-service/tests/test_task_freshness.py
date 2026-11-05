"""Task reads expose source freshness without mutating saved plans."""
import copy

from elo_shared.runtime import Problem
from planner_fixtures import draft
from test_planner_flow import H, OWNER, Scripted, Sources, accepted, client_for

URL = '/api/v1/roadmaps/planner/tasks'


class ContextSources(Sources):
    error = None

    async def read(self, service, path, token, params=None):
        if path.endswith('/context') and self.error:
            raise self.error
        return await super().read(service, path, token, params)


def test_task_freshness_distinguishes_current_stale_and_unready_without_writes():
    source = ContextSources()
    with client_for(Scripted([draft()]), source) as client:
        accepted(client)
        before = copy.deepcopy(client.app.state.store.data[OWNER])
        current = client.get(URL, headers=H)
        assert current.status_code == 200
        assert current.json()['freshness'] == 'current'
        assert current.json()['stale'] is False and current.json()['source_unavailable'] is False

        source.hash = 'changed-inputs'
        changed = client.get(URL, headers=H).json()
        assert changed['freshness'] == 'stale' and changed['stale'] is True

        # A reachable service with missing inputs is not a verified current plan,
        # even when it still reports the old matching hash.
        source.hash = 'hash1'
        source.ready = False
        missing = client.get(URL, headers=H).json()
        assert missing['freshness'] == 'not_ready'
        assert missing['source_unavailable'] is False
        source.hash = None
        assert client.get(URL, headers=H).json()['freshness'] == 'not_ready'
        source.ready = True
        assert client.get(URL, headers=H).json()['freshness'] == 'not_ready'
        assert client.app.state.store.data[OWNER] == before


def test_task_freshness_reports_unavailable_but_preserves_authentication_errors():
    source = ContextSources()
    with client_for(Scripted([draft()]), source) as client:
        accepted(client)
        before = copy.deepcopy(client.app.state.store.data[OWNER])
        source.error = Problem('Source unavailable.', 503, 'upstream')
        response = client.get(URL, headers=H)
        assert response.status_code == 200
        assert response.json()['freshness'] == 'unavailable'
        assert response.json()['source_unavailable'] is True
        assert client.app.state.store.data[OWNER] == before
        source.error = Problem('Session expired.', 401, 'session')
        assert client.get(URL, headers=H).status_code == 401
        assert client.get(URL).status_code == 401

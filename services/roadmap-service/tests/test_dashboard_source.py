"""Read-only dashboard projection and immutable accepted pace baselines."""
import copy
from uuid import uuid4
from planner_fixtures import OWNER, draft
from test_planner_flow import H, Scripted, Sources, accepted, client_for, generate
from test_editable_tasks import by_title, definition, save

URL = '/api/v1/roadmaps/dashboard-source'


def test_passive_read_does_not_launch_pending_work_or_query_sources(monkeypatch):
    source = Sources()
    model = Scripted([draft()])
    with client_for(model, source) as client:
        assert client.get(URL).status_code == 401
        empty = client.get(URL, headers=H)
        assert empty.status_code == 200
        assert empty.json() == {'version': 0, 'active': None, 'active_review': None, 'task_readiness': {}}
        state = accepted(client)
        owner = source.owner
        row = client.app.state.store.data[owner]
        row['pending'] = {'id': 'pending', 'kind': 'generate', 'status': 'pending', 'stage': 'preparing'}
        before = copy.deepcopy(row)
        reads = list(source.reads)
        monkeypatch.setattr('app.main.launch', lambda *args: (_ for _ in ()).throw(AssertionError('must not launch')))
        response = client.get(URL, headers=H)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['active']['id'] == state['planner']['active']['id']
        assert data['active_review']['milestones']
        assert data['task_readiness'][data['active']['editable_tasks'][0]['id']]['actionable']
        assert source.reads == reads
        assert client.app.state.store.data[owner] == before
        source.owner = '22222222-2222-4222-8222-222222222222'
        assert client.get(URL, headers=H).json()['active'] is None
        assert client.get('/api/v1/roadmaps/history/'+data['active']['id'], headers=H).status_code == 404

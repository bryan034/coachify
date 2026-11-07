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


def test_baseline_is_the_exact_accepted_snapshot_and_survives_task_mutations():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        active = state['planner']['active']
        baseline = active['pace_baseline_id']
        assert baseline == active['id']
        snapshot = client.get('/api/v1/roadmaps/history/'+baseline, headers=H)
        assert snapshot.status_code == 200
        assert snapshot.json()['pace_baseline_id'] == baseline
        state = save(client, 'add', state, task=definition(title='Added work'))
        task = by_title(state, 'Added work')
        state = save(client, 'status', state, task_id=task['id'], status='completed')
        source = client.get(URL, headers=H).json()
        assert source['active']['id'] != baseline
        assert source['active']['pace_baseline_id'] == baseline
        assert not any(t['id'] == task['id'] for t in snapshot.json()['editable_tasks'])
        assert client.get('/api/v1/roadmaps/history/'+baseline, headers=H).json() == snapshot.json()


def test_accepting_revision_resets_baseline_and_retry_is_idempotent():
    with client_for(Scripted([draft(), draft()])) as client:
        state = accepted(client)
        first = state['planner']['active']['pace_baseline_id']
        state = generate(client, state)
        body = {'expected_version': state['version'], 'mutation_id': str(uuid4())}
        response = client.post('/api/v1/roadmaps/planner/accept', headers=H, json=body)
        assert response.status_code == 200, response.text
        active = response.json()['planner']['active']
        assert active['pace_baseline_id'] == active['id'] != first
        assert client.get('/api/v1/roadmaps/history/'+active['id'], headers=H).json()['pace_baseline_id'] == active['id']
        retry = client.post('/api/v1/roadmaps/planner/accept', headers=H, json=body)
        assert retry.status_code == 200 and retry.json()['planner']['active']['id'] == active['id']


def test_legacy_snapshot_gets_no_invented_baseline_or_read_migration():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        row = client.app.state.store.data[OWNER]
        row['planner']['active'].pop('pace_baseline_id', None)
        row['planner']['active'].pop('editable_tasks', None)
        before = copy.deepcopy(row)
        response = client.get(URL, headers=H)
        assert response.status_code == 200
        assert response.json()['active']['pace_baseline_id'] is None
        assert response.json()['active']['editable_tasks']
        assert client.app.state.store.data[OWNER] == before


def test_completions_capture_estimate_through_task_and_legacy_endpoints():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        assignment = state['planner']['active']['assignments'][0]
        response = client.post('/api/v1/roadmaps/planner/assignments/status', headers=H, json={
            'expected_version':state['version'], 'mutation_id':str(uuid4()),
            'assignment_id':assignment['id'], 'status':'completed'})
        assert response.status_code == 200, response.text
        state = response.json()
        task = next(t for t in state['planner']['active']['editable_tasks'] if t['id'] == assignment['id'])
        event = task['history'][-1]
        assert event['estimated_minutes_at_completion'] == assignment['duration_minutes']
        assert event['at'] == task['completed_at'] and event['completion_definition'] == task['completion_outcome']
        state = save(client, 'status', state, task_id=task['id'], status='not_started')
        state = save(client, 'edit', state, task_id=task['id'], changes={'estimated_minutes': 90})
        state = save(client, 'status', state, task_id=task['id'], status='completed')
        task = next(t for t in state['planner']['active']['editable_tasks'] if t['id'] == assignment['id'])
        completions = [event for event in task['history'] if event.get('to') == 'completed']
        assert [e['estimated_minutes_at_completion'] for e in completions] == [assignment['duration_minutes'], 90]
        assert completions[-1]['at'] == task['completed_at']


def test_legacy_events_are_not_given_invented_effort_on_read():
    with client_for(Scripted([draft()])) as client:
        accepted(client)
        row = client.app.state.store.data[OWNER]
        plan = row['planner']['active']
        plan.pop('editable_tasks', None)
        plan['assignments'][0]['history'] = [{'at':'2029-12-01T00:00:00Z', 'from':'scheduled', 'to':'completed'}]
        original = copy.deepcopy(row)
        response = client.get(URL, headers=H)
        event = response.json()['active']['editable_tasks'][0]['history'][0]
        assert 'estimated_minutes_at_completion' not in event
        assert row == original

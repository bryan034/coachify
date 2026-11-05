"""Editable roadmap tasks through owner-scoped HTTP APIs, using synthetic plans."""
import copy
from uuid import uuid4

from planner_fixtures import assignment, draft
from test_planner_flow import H, Scripted, Sources, accepted, client_for, generate, read

PREFIX = '/api/v1/roadmaps/planner'


def request(client, endpoint, state, **data):
    return client.post(PREFIX + '/tasks/' + endpoint, headers=H,
                       json={'expected_version': state['version'], 'mutation_id': str(uuid4()), **data})


def save(client, endpoint, state, **data):
    response = request(client, endpoint, state, **data)
    assert response.status_code == 200, response.text
    return response.json()


def definition(**changes):
    return {'title': 'Practise explaining a project', 'instructions': 'Record a short explanation.',
            'completion_outcome': 'A recording exists.', 'estimated_minutes': 45,
            'requirement_refs': [], 'prerequisites': [], 'milestone_key': None, 'schedule': [], **changes}


def tasks(client, **params):
    response = client.get(PREFIX + '/tasks', headers=H, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def by_title(state, title):
    return next(t for t in state['planner']['active']['editable_tasks'] if t['title'] == title)

def test_validation_rejects_invalid_definitions_and_stale_or_reused_keys():
    with client_for(Scripted([draft()])) as client:
        state = accepted(client)
        for bad in (definition(title='  '), definition(instructions=' '), definition(completion_outcome=''),
                    definition(estimated_minutes=0), definition(estimated_minutes=-1)):
            assert request(client, 'add', state, task=bad).status_code == 422
        body = {'expected_version': state['version'], 'mutation_id': str(uuid4()), 'task': definition()}
        first = client.post(PREFIX + '/tasks/add', headers=H, json=body)
        assert first.status_code == 200, first.text
        saved = first.json()
        replay = client.post(PREFIX + '/tasks/add', headers=H, json=body)
        assert replay.status_code == 200, replay.text
        assert replay.json()['version'] == saved['version']
        assert len([t for t in replay.json()['planner']['active']['editable_tasks'] if t['title'] == body['task']['title']]) == 1
        changed = copy.deepcopy(body); changed['task']['title'] = 'Different change'
        assert client.post(PREFIX + '/tasks/add', headers=H, json=changed).status_code == 409
        assert request(client, 'add', state, task=definition(title='Stale save')).status_code == 409

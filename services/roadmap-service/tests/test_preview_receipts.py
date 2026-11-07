"""Preview mutation receipts bind the action, including pre-namespace compatibility."""
import copy
from uuid import uuid4
import pytest
from elo_shared.runtime import digest
from planner_fixtures import OWNER, draft
from test_planner_flow import H, Scripted, client_for, configure, generate

PREFIX = '/api/v1/roadmaps/planner/'


@pytest.mark.parametrize('first,second', [('accept', 'discard'), ('discard', 'accept')])
def test_preview_retry_is_action_bound(first, second):
    with client_for(Scripted([draft()])) as client:
        state = generate(client, configure(client))
        assert state['planner']['candidate']
        body = {'expected_version': state['version'], 'mutation_id': str(uuid4())}
        result = client.post(PREFIX + first, headers=H, json=body)
        assert result.status_code == 200, result.text
        before = copy.deepcopy(client.app.state.store.data[OWNER])
        replay = client.post(PREFIX + first, headers=H, json=body)
        assert replay.status_code == 200 and replay.json()['version'] == result.json()['version']
        mismatch = client.post(PREFIX + second, headers=H, json=body)
        assert mismatch.status_code == 409
        assert client.app.state.store.data[OWNER] == before


@pytest.mark.parametrize('action', ['accept', 'discard'])
def test_legacy_untagged_receipt_is_not_claimed_as_same_action(action):
    with client_for(Scripted([draft()])) as client:
        state = generate(client, configure(client))
        body = {'expected_version': state['version'], 'mutation_id': str(uuid4())}
        row = client.app.state.store.data[OWNER]
        row['receipts'].append({'id': body['mutation_id'], 'hash': digest(body)})
        before = copy.deepcopy(row)
        result = client.post(PREFIX + action, headers=H, json=body)
        assert result.status_code == 409
        assert result.json()['code'] == 'legacy_preview_retry_ambiguous'
        assert client.app.state.store.data[OWNER] == before
        assert row['planner']['candidate'] is not None

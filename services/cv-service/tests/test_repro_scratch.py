from copy import deepcopy
from tests.test_cv_interview import start, evaluate
from tests.test_conversation_security import send

def test_repro(harness):
    client, _, *_ = harness
    _, chat, provider = start(harness)
    def flaky(context):
        result = evaluate(context)
        if not context['schema_retry']:
            result = deepcopy(result)
            result['interpretations'][0]['claims'][0]['skill_id'] = 'skill:python3'
        return result
    provider.evaluation = flaky
    chat = send(client, chat, 'I built the Python API with guidance.')
    route = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'route') if chat['messages'][-1]['actions'] else None
    print('LAST', [(m['role'], m['text'][:120], [(a['kind'], a['status'], a.get('error')) for a in m.get('actions', [])]) for m in chat['messages'][-2:]])
    print('CALLS', len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']))
    assert chat['active_question']['question'] == 'What was the scope of your task?'


def test_repro_replay(harness):
    from uuid import uuid4
    from tests.test_conversation_security import PREFIX, settled
    client, _, *_ = harness
    _, chat, provider = start(harness)
    def flaky(context):
        result = deepcopy(evaluate(context))
        if not context['schema_retry'] and not getattr(provider, 'seen', False):
            provider.seen = True
            result['actions'][0]['question_id'] = 'not-a-question'
        return result
    provider.evaluation = flaky
    chat = send(client, chat, 'I built the Python API with guidance.')
    route = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'route')
    print('FIRST', route['status'], route.get('error'))
    client.post(PREFIX + '/' + chat['id'] + '/actions/' + route['id'], json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'decision': 'retry'})
    chat = settled(client, chat['id'])
    route = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'route')
    print('AFTER RETRY', route['status'], route.get('error'))
    print('CALLS', len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']))

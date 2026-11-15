"""Provider-free checks of operation boundaries and privacy in usage events."""
import json
import logging
from elo_shared.model_telemetry import Measurement, fingerprint
from tests.conftest import upload, mutation
from tests.test_conversation import Router, source_chat
from tests.test_conversation_security import open_chat, send
from tests.test_interpretation import PERSONAL, mixed_output, project_question

LOGGER = 'uvicorn.error.model_usage'


def record(stage):
    Measurement({'model': 'synthetic'}, {'service': 'cv', 'stage': stage}).finish()


def events(caplog):
    return [json.loads(record.getMessage().removeprefix('model_usage ')) for record in caplog.records if record.name == LOGGER]


def test_extraction_and_repair_share_operation_scope(harness, caplog, monkeypatch):
    client, app, extractor, *_ = harness
    original = extractor.extract
    def invalid(*args, **kwargs):
        record('extraction')
        output, metadata = original(*args, **kwargs)
        output['items'][0]['explicit'] = 'invalid'
        return output, metadata
    monkeypatch.setattr(extractor, 'extract', invalid)
    uploaded = upload(client).json()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        app.state.worker.run_once()
    captured = events(caplog)
    assert len(captured) == 2
    assert captured[0]['operation_id'] == captured[1]['operation_id'] == fingerprint('elo-model-operation:' + uploaded['operation_id'])
    assert uploaded['operation_id'] not in json.dumps(captured) and 'Example University' not in json.dumps(captured)


def test_chat_turn_scope_survives_threads_and_changes_for_each_message(harness, caplog):
    client, app, *_ = harness
    chat = open_chat(client)
    router = app.state.conversations.provider = Router()
    router.callback = lambda: (record('interpret'), record('plan'))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        chat = send(client, chat, 'Private synthetic first message')
        chat = send(client, chat, 'Private synthetic second message')
    captured = events(caplog)
    assert len(captured) == 4
    ids = [event['operation_id'] for event in captured]
    assert ids[0] == ids[1] and ids[2] == ids[3] and ids[0] != ids[2]
    assert all(value.startswith('sha256:') for value in ids)
    assert 'Private synthetic' not in caplog.text and 'owner-a' not in caplog.text


def test_direct_answer_and_retry_share_revision_scope(harness, caplog):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.before_return = lambda: record('interpret')
    app.state.interpreter.failure = 'synthetic failure'
    with caplog.at_level(logging.INFO, logger=LOGGER):
        failed = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
        app.state.interpreter.failure = None
        app.state.interpreter.payload = mixed_output
        assert client.post(path + '/interpretation/retry', json=mutation(failed['version'])).status_code == 200
    captured = events(caplog)
    assert len(captured) == 2 and captured[0]['operation_id'] == captured[1]['operation_id']
    assert captured[0]['operation_id'].startswith('sha256:')
    assert question['id'] not in caplog.text and PERSONAL not in caplog.text


def test_chat_interpretation_inherits_parent_turn_scope(harness, caplog):
    client, app, *_ = harness
    _, question, chat = source_chat(harness)
    router = app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    router.callback = lambda: record('route')
    app.state.interpreter.before_return = lambda: record('interpret')
    app.state.interpreter.payload = mixed_output
    with caplog.at_level(logging.INFO, logger=LOGGER):
        send(client, chat, PERSONAL)
    captured = events(caplog)
    assert [event['stage'] for event in captured] == ['route', 'interpret']
    assert captured[0]['operation_id'] == captured[1]['operation_id'] and captured[0]['operation_id'] is not None
    assert PERSONAL not in caplog.text

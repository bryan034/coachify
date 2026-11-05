"""Failed chat steps are diagnosable from logs without exposing private text."""
import json
import logging
import httpx
import pytest
from pydantic import ValidationError
from app.clients.conversation import ConversationRouter
from tests.test_conversation_security import send
from tests.test_cv_interview import opened

PRIVATE = 'PRIVATE-synthetic-answer'


def router(monkeypatch, handler):
    monkeypatch.setenv('CV_LLM_BASE_URL', 'https://synthetic-provider.example/v1')
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-fixture')
    monkeypatch.setenv('CV_LLM_API_KEY', 'synthetic-secret-for-test')
    real_client = httpx.Client
    monkeypatch.setattr('app.clients.conversation.Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    return ConversationRouter()


def completion(content, finish_reason='stop'):
    return httpx.Response(200, json={'choices': [{'finish_reason': finish_reason, 'message': {'content': content}}]})


def test_failed_turn_logs_category_and_provider_status_without_private_text(harness, caplog):
    client, *_ = harness
    _, chat, provider = opened(harness)
    def broken(context):
        request = httpx.Request('POST', 'https://synthetic-provider.example/v1')
        cause = httpx.HTTPStatusError(PRIVATE, request=request, response=httpx.Response(503, request=request))
        raise ValueError('Chat interpretation is unavailable. ' + PRIVATE) from cause
    provider.plans = [broken]
    with caplog.at_level(logging.WARNING):
        send(client, chat, 'Review my CV', command='review')
    assert 'CV chat failed stage=route' in caplog.text
    assert 'category=provider_status' in caplog.text and 'provider_status_code=503' in caplog.text
    assert 'where=' in caplog.text and PRIVATE not in caplog.text


@pytest.mark.parametrize('reply, expected', [
    (lambda request: httpx.Response(429, text=PRIVATE), ["outcome=provider_error", "'status': 429"]),
    (lambda request: completion(json.dumps({'reply': PRIVATE, 'actions': []}), 'length'), ['outcome=incomplete', "'finish_reason': 'length'"]),
    (lambda request: completion('not json ' + PRIVATE), ['outcome=invalid_schema']),
])
def test_model_call_failures_are_logged_with_codes_only(monkeypatch, caplog, reply, expected):
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError):
        router(monkeypatch, reply).route({'task': 'cv_interview_plan', 'message': PRIVATE})
    assert 'task=cv_interview_plan' in caplog.text and 'elapsed_seconds=' in caplog.text
    assert all(text in caplog.text for text in expected) and PRIVATE not in caplog.text


def test_timeout_names_the_exception(monkeypatch, caplog):
    def slow(request): raise httpx.ReadTimeout(PRIVATE, request=request)
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError, match='unavailable'):
        router(monkeypatch, slow).route({'task': 'cv_interview_interpret', 'message': PRIVATE})
    assert "'exception': 'ReadTimeout'" in caplog.text and PRIVATE not in caplog.text


def test_schema_failure_logs_field_paths_not_values(monkeypatch, caplog):
    output = json.dumps({'action': PRIVATE, 'reply': PRIVATE})
    with caplog.at_level(logging.WARNING), pytest.raises(ValidationError):
        router(monkeypatch, lambda request: completion(output)).route({'task': 'cv_interview_plan'})
    assert "'field': 'action'" in caplog.text and PRIVATE not in caplog.text


def overloaded(monkeypatch, responses):
    calls, sleeps = [], []
    def handler(request):
        calls.append(request)
        return responses(len(calls))
    monkeypatch.setattr('app.clients.conversation.time.sleep', sleeps.append)
    return router(monkeypatch, handler), calls, sleeps


def test_temporary_overload_retries_and_returns_the_model_reply(monkeypatch, caplog):
    answer = completion(json.dumps({'reply': 'Understood.', 'actions': []}))
    chat, calls, sleeps = overloaded(monkeypatch, lambda count: httpx.Response(503, text=PRIVATE) if count < 3 else answer)
    with caplog.at_level(logging.WARNING):
        output, _ = chat.route({'task': 'cv_conversation', 'message': PRIVATE})
    assert output.reply == 'Understood.' and len(calls) == 3 and sleeps == [2, 5]
    assert caplog.text.count('outcome=overloaded_retrying') == 2 and PRIVATE not in caplog.text


def test_persistent_overload_stops_after_three_attempts(monkeypatch, caplog):
    chat, calls, sleeps = overloaded(monkeypatch, lambda count: httpx.Response(503))
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError, match='unavailable') as failure:
        chat.route({'task': 'cv_conversation'})
    assert len(calls) == 3 and sleeps == [2, 5]
    assert failure.value.__cause__.response.status_code == 503 and 'outcome=provider_error' in caplog.text


@pytest.mark.parametrize('status', [400, 429, 500])
def test_other_provider_errors_are_not_retried(monkeypatch, status):
    chat, calls, sleeps = overloaded(monkeypatch, lambda count: httpx.Response(status))
    with pytest.raises(ValueError, match='unavailable'):
        chat.route({'task': 'cv_conversation'})
    assert len(calls) == 1 and sleeps == []


def test_overload_retries_stop_when_the_turn_budget_is_spent(monkeypatch):
    monkeypatch.setattr('app.clients.conversation.OVERLOAD_RETRY_BUDGET_SECONDS', 0)
    chat, calls, sleeps = overloaded(monkeypatch, lambda count: httpx.Response(503))
    with pytest.raises(ValueError, match='unavailable'):
        chat.route({'task': 'cv_conversation'})
    assert len(calls) == 1 and sleeps == []

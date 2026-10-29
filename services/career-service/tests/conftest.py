import json
import os
import socket
from pathlib import Path
import httpx
import pytest
import requests


def isolate_application_settings():
    """Never inherit a developer's application connections in synthetic tests.

    MONGODB_TEST_URI is an explicit disposable-test opt-in. Individual tests can
    still inject a database, mock transport or synthetic settings after setup.
    """
    for name in tuple(os.environ):
        if name == 'MONGODB_TEST_URI':
            continue
        if name.startswith(('MONGODB_', 'AI_', 'GEMINI_', 'BRAVE_', 'OPPORTUNITY_', 'DISCOVERY_', 'LANGSMITH_', 'LANGCHAIN_')) or name in ('PROFILE_SERVICE_URL', 'CV_SERVICE_URL'):
            os.environ.pop(name, None)


def blocked_http(*args, **kwargs):
    raise AssertionError('Synthetic tests must use an explicit mock HTTP transport.')


async def blocked_async_http(*args, **kwargs):
    raise AssertionError('Synthetic tests must use an explicit mock HTTP transport.')


# Run before importing test modules: module-level app construction and live-test
# decorators must never observe inherited production settings.
isolate_application_settings()
httpx.HTTPTransport.handle_request = blocked_http
httpx.AsyncHTTPTransport.handle_async_request = blocked_async_http
socket.create_connection = blocked_http  # Career's pinned preview HTTP client.
requests.sessions.Session.request = blocked_http  # Includes uncached tokenizer downloads.


@pytest.fixture(autouse=True)
def isolated_application(monkeypatch):
    isolate_application_settings()
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked_http)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', blocked_async_http)
    monkeypatch.setattr(socket, 'create_connection', blocked_http)
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked_http)


@pytest.fixture
def documents():
    return json.loads((Path(__file__).parent / 'fixtures/analysis.json').read_text())

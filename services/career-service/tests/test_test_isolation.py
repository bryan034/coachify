"""The test harness cannot inherit real application connections or call providers."""
import asyncio
import os
import socket
import httpx
import pytest
import requests
from tests.conftest import isolate_application_settings


def test_hostile_inherited_settings_are_cleared_but_disposable_opt_in_remains(monkeypatch):
    unsafe = {'MONGODB_URI': 'mongodb://unintended.invalid/private',
              'MONGODB_DATABASE': 'private', 'GEMINI_API_KEY': 'synthetic-hostile',
              'BRAVE_API_KEY': 'synthetic-hostile', 'AI_ENABLED': 'true',
              'OPPORTUNITY_LIVE_TEST': '1', 'PROFILE_SERVICE_URL': 'https://unintended.invalid',
              'CV_SERVICE_URL': 'https://unintended.invalid', 'LANGSMITH_API_KEY': 'synthetic-hostile'}
    for key, value in unsafe.items(): monkeypatch.setenv(key, value)
    monkeypatch.setenv('MONGODB_TEST_URI', 'mongodb://explicit-disposable.invalid/test')
    isolate_application_settings()
    assert not set(unsafe).intersection(os.environ)
    assert os.environ['MONGODB_TEST_URI'] == 'mongodb://explicit-disposable.invalid/test'


def test_application_startup_does_not_construct_inherited_database(monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('MONGODB_URI', 'mongodb://unintended.invalid/private')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-hostile')
    isolate_application_settings()
    def forbidden(*args, **kwargs): pytest.fail('Implicit application database was constructed.')
    monkeypatch.setattr('app.main.MongoClient', forbidden)
    async def run():
        app = create_app()
        async with app.router.lifespan_context(app):
            assert app.state.goal_store is None
            assert app.state.workflow is None and app.state.opportunities is None
            assert not app.state.ai.settings.enabled
    asyncio.run(run())


def test_real_http_is_blocked_while_explicit_transports_work():
    with pytest.raises(AssertionError, match='explicit mock HTTP'):
        httpx.get('https://unintended.invalid')
    with pytest.raises(AssertionError, match='explicit mock HTTP'):
        socket.create_connection(('unintended.invalid', 443))
    with pytest.raises(AssertionError, match='explicit mock HTTP'):
        requests.get('https://unintended.invalid')
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        assert client.get('https://synthetic.invalid').status_code == 200
    async def run():
        async with httpx.AsyncClient() as client:
            with pytest.raises(AssertionError, match='explicit mock HTTP'):
                await client.get('https://unintended.invalid')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
            assert (await client.get('https://synthetic.invalid')).status_code == 200
    asyncio.run(run())

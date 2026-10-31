"""Regression: configured research must not depend on legacy chat/search switches."""
import json
import asyncio
from app.schemas.opportunity import CATEGORIES
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.ai.adapter import AIAdapter,Operation
from app.ai.config import AISettings,GeminiSettings
from app.ai.contracts import AIInput
from app.ai.opportunity_config import OpportunitySettings
from app.ai.routing import ModelRouter,opportunity_models
from app.clients.search_sources import SourceAPIs
from app.main import create_app
from app.workflows.opportunity.engine import availability_issues


def test_research_uses_configured_gemini_even_when_gemini_chat_is_disabled():
    async def run():
        calls=[]
        def response(request):
            calls.append(request)
            assert request.headers['authorization']=='Bearer synthetic-gemini'
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({category:['Example Analyst Singapore '+category] for category in CATEGORIES})}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            primary=AIAdapter(GeminiSettings(enabled=True,api_key='synthetic-gemini'),client)
            gemini=GeminiSettings(enabled=False,api_key='synthetic-gemini')
            router=opportunity_models(primary,None,gemini,OpportunitySettings(),client)
            assert router.context_enabled and router.context.settings.model=='gemini-3.5-flash-lite'
            assert not gemini.enabled  # Research does not enable the separate chat feature.
            await router.generate(AIInput(stage='opportunity_plan',context='{}'),Operation('synthetic','1','opportunity_plan'),current_revision=lambda:'1')
        assert len(calls)==1 and calls[0].url.host=='generativelanguage.googleapis.com'
    asyncio.run(run())


@pytest.mark.parametrize('mode',['search','answers','llm_context'])
def test_startup_enables_research_with_keys_independently_of_legacy_modes(monkeypatch,mode):
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['elo_startup_test_'+uuid4().hex]
    monkeypatch.setattr(AISettings,'from_env',classmethod(lambda cls:AISettings(enabled=True,api_key='synthetic-gemini')))
    monkeypatch.setattr(OpportunitySettings,'from_env',classmethod(lambda cls:OpportunitySettings()))
    monkeypatch.setattr(SourceAPIs,'from_environment',classmethod(lambda cls,client:SourceAPIs(client,brave_key='synthetic-brave',brave_mode=mode)))
    profile=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={})))
    try:
        with TestClient(create_app(database=db,profile_client=profile)) as client:
            state=client.app.state
            assert isinstance(state.ai,ModelRouter) and state.ai.settings.provider=='gemini'
            assert state.ai.primary is state.ai.context
            assert state.opportunities.ai.primary is state.ai.primary
            assert state.discovery.ai.settings.model=='gemini-3.5-flash-lite'
            assert state.research_client.brave_mode=='llm_context'
            assert state.opportunities.available and state.opportunities.availability_issues==[]
            assert state.opportunities.source.brave_mode=='llm_context'
            assert state.opportunities.ai.context.settings.enabled
    finally:
        mongo.drop_database(db.name);mongo.close()


@pytest.mark.parametrize('changes,expected',[
    ({'enabled':False},['research_disabled']),
    ({'primary':False},['reasoning_disabled']),
    ({'gemini':False},['gemini_not_configured']),
    ({'key':''},['brave_not_configured']),
    ({'mode':'search'},['brave_llm_context_required']),
])
def test_unavailability_identifies_the_failed_gate_without_exposing_credentials(changes,expected):
    ai=SimpleNamespace(settings=SimpleNamespace(enabled=changes.get('primary',True)),context_enabled=changes.get('gemini',True))
    source=SourceAPIs(None,brave_key=changes.get('key','PRIVATE_SYNTHETIC_KEY'),brave_mode=changes.get('mode','llm_context'))
    if 'mode' in changes:source.brave_mode=changes['mode']  # Simulate an incompatible injected adapter.
    issues=availability_issues(OpportunitySettings(enabled=changes.get('enabled',True)),ai,source)
    assert issues==expected and 'PRIVATE' not in str(issues)


def test_disabled_reasoning_does_not_create_a_fallback_adapter():
    primary=AIAdapter(GeminiSettings(enabled=False),None)
    router=opportunity_models(primary,None,GeminiSettings(enabled=False,api_key='synthetic-gemini'),OpportunitySettings(),None)
    assert router.primary is primary and router.context is primary
    assert not router.settings.enabled and not router.context_enabled

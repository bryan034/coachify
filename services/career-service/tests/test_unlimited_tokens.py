import json

import pytest

from app.ai.adapter import AIAdapter,DEFAULT_OUTPUT_TOKENS,STAGE_OUTPUT_TOKENS
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.opportunity_config import OpportunitySettings
from app.ai.opportunity_contracts import structure_input
from app.schemas.analysis import ResearchSource


def unlimited():
    return AISettings(enabled=True,model='synthetic',api_key='synthetic')


def test_token_settings_default_to_blank():
    settings=unlimited()
    assert settings.max_output_tokens is None and settings.context_tokens is None


@pytest.mark.parametrize('parameter',['max_tokens','max_completion_tokens'])
def test_blank_environment_limits_load_as_blank_and_keep_stage_caps(monkeypatch,parameter):
    monkeypatch.setenv('CAREER_LLM_API_KEY','synthetic')
    monkeypatch.setenv('CAREER_LLM_TOKEN_PARAMETER',parameter)
    monkeypatch.setenv('AI_MAX_OUTPUT_TOKENS','')
    monkeypatch.setenv('AI_CONTEXT_TOKENS','')
    settings=AISettings.from_env()
    assert settings.max_output_tokens is None and settings.context_tokens is None
    payload=AIAdapter(settings,None)._payload(AIInput(stage='context_answer',context='{}',
        conversation=[{'role':'user','content':'What is the salary?'}]))
    assert payload[parameter]==STAGE_OUTPUT_TOKENS['context_answer']


def test_configured_limits_above_previous_ceilings_are_accepted(monkeypatch):
    monkeypatch.setenv('CAREER_LLM_API_KEY','synthetic')
    monkeypatch.setenv('AI_MAX_OUTPUT_TOKENS','32768')
    monkeypatch.setenv('AI_CONTEXT_TOKENS','1000000')
    settings=AISettings.from_env()
    assert settings.max_output_tokens==32768 and settings.context_tokens==1000000


@pytest.mark.parametrize('stage',['opportunity_plan','role_summary','goal_summary','discovery_extract'])
def test_blank_output_limit_keeps_each_stage_safety_cap(stage):
    payload=AIAdapter(unlimited(),None)._payload(AIInput(stage=stage,context='{}'))
    assert payload['max_tokens']==STAGE_OUTPUT_TOKENS[stage]


@pytest.mark.parametrize('ceiling,expected',[(512,512),(32768,1024)])
def test_configured_output_limit_only_lowers_a_stage_cap(ceiling,expected):
    settings=AISettings(enabled=True,model='synthetic',api_key='synthetic',max_output_tokens=ceiling)
    assert AIAdapter(settings,None)._payload(AIInput(stage='opportunity_plan',context='{}'))['max_tokens']==expected


def test_unknown_stages_fall_back_to_the_default_cap():
    payload=AIAdapter(unlimited(),None)._payload(AIInput(stage='exploration',context='{}',conversation=[{'role':'user','content':'Hi'}]))
    assert payload['max_tokens']==DEFAULT_OUTPUT_TOKENS


def test_unlimited_context_sends_large_evidence_whole():
    sources=[ResearchSource(source_id=f's{i}',platform='other',url=f'https://example.test/{i}',
        evidence=f'Source {i}: interns in Singapore report a monthly allowance and mentorship. '*100) for i in range(30)]
    context=structure_input({'company':'Example','role':'Analyst Intern'},'internship_insights',sources)
    encoded=json.dumps(context)
    assert len(encoded)>200000
    payload=AIAdapter(unlimited(),None)._payload(AIInput(stage='opportunity_structure',context=encoded))
    assert payload['max_tokens']==STAGE_OUTPUT_TOKENS['opportunity_structure']
    assert json.loads(payload['messages'][1]['content'])['evidence']==context['evidence']


def test_unlimited_chat_keeps_the_full_conversation():
    history=[{'role':'user' if i%2==0 else 'assistant','content':f'Turn {i}'+' career detail'*280} for i in range(29)]
    payload=AIAdapter(unlimited(),None)._payload(AIInput(stage='career_guidance',context='{}',conversation=history))
    assert json.loads(payload['messages'][1]['content'])['conversation']==history


def test_blank_opportunity_evidence_budget_is_unlimited(monkeypatch):
    monkeypatch.setenv('OPPORTUNITY_EVIDENCE_TOKENS','')
    assert OpportunitySettings.from_env().evidence_tokens is None
    monkeypatch.setenv('OPPORTUNITY_EVIDENCE_TOKENS','65536')
    assert OpportunitySettings.from_env().evidence_tokens==65536

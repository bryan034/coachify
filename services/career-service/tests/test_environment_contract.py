"""Public deployment template and service-scoped credential contract; no real env files."""
import re
from pathlib import Path
import pytest
from app.ai.config import AISettings
from app.clients.search_sources import SourceAPIs

ROOT=Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('new,legacy,expected',[
    ('synthetic-new','synthetic-old','synthetic-new'),
    ('  synthetic-new  ',None,'synthetic-new'),
    ('','synthetic-old',''),
    (None,'synthetic-old','synthetic-old'),
    (None,None,''),
])
def test_canonical_career_keys_take_precedence_including_explicit_blank(monkeypatch,new,legacy,expected):
    for canonical,alias in [('CAREER_LLM_API_KEY','GEMINI_API_KEY'),('CAREER_RESEARCH_API_KEY','BRAVE_API_KEY')]:
        if new is not None:monkeypatch.setenv(canonical,new)
        if legacy is not None:monkeypatch.setenv(alias,legacy)
    settings=AISettings.from_env()
    sources=SourceAPIs.from_environment(None)
    assert settings.api_key.get_secret_value()==expected
    assert settings.enabled==bool(expected)
    assert sources.brave_key==expected and sources.configured==bool(expected)


def test_enabled_but_missing_career_key_names_new_configuration_without_leaking_values(monkeypatch):
    monkeypatch.setenv('AI_ENABLED','true')
    monkeypatch.setenv('GEMINI_API_KEY','synthetic-old-must-not-be-used')
    monkeypatch.setenv('CAREER_LLM_API_KEY','')
    with pytest.raises(ValueError) as error:AISettings.from_env()
    assert 'CAREER_LLM_API_KEY' in str(error.value)
    assert 'synthetic-old-must-not-be-used' not in str(error.value)


def test_public_example_covers_every_active_compose_input_without_real_secrets():
    example=(ROOT/'infrastructure/docker/.env.example').read_text()
    pairs=re.findall(r'^([A-Z][A-Z0-9_]*)=(.*)$',example,re.M)
    keys={key for key,_ in pairs}
    assert len(keys)==len(pairs)
    compose=(ROOT/'infrastructure/docker/compose.yaml').read_text()
    inputs=set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)',compose))
    aliases={'GEMINI_API_KEY','BRAVE_API_KEY'}
    assert inputs-aliases==keys
    values=dict(pairs)
    for name in ('CAREER_LLM_API_KEY','CAREER_RESEARCH_API_KEY','CV_LLM_API_KEY',
                 'SMTP_PASSWORD','OTP_HASH_SECRET','MONGO_ROOT_PASSWORD',
                 'PROFILE_DB_PASSWORD','CAREER_DB_PASSWORD','CV_DB_PASSWORD'):
        assert values[name]==''
    assert not keys.intersection(aliases)
    career=compose.split('  career-service:\n',1)[1].split('  cv-service:\n',1)[0]
    assert '      CAREER_LLM_API_KEY:' in career and '      CAREER_RESEARCH_API_KEY:' in career
    assert '      GEMINI_API_KEY:' not in career and '      BRAVE_API_KEY:' not in career
    other_services=compose.replace(career,'')
    assert '      CAREER_LLM_API_KEY:' not in other_services
    assert '      CAREER_RESEARCH_API_KEY:' not in other_services

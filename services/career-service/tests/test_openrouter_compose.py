"""Rendered public deployment configuration, using synthetic credentials only."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.ai.adapter import AIAdapter
from app.ai.config import AISettings
from app.ai.contracts import AIInput

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = shutil.which('docker-compose')
DOCKER = shutil.which('docker')


def render(tmp_path, env_file, overrides):
    # An explicit env file and isolated project directory prevent Compose from
    # loading the developer's private infrastructure/docker/.env.
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': os.environ.get('HOME', str(tmp_path))}
    env.update({name: 'synthetic-password' for name in (
        'MONGO_ROOT_PASSWORD', 'PROFILE_DB_PASSWORD', 'CAREER_DB_PASSWORD', 'CV_DB_PASSWORD',
        'ASSESSMENT_DB_PASSWORD', 'ROADMAP_DB_PASSWORD', 'JOBS_DB_PASSWORD')})
    env.update(overrides)
    command = ([COMPOSE] if COMPOSE else [DOCKER, 'compose']) + ['--project-directory', str(tmp_path),
        '--env-file', str(env_file), '-f', str(ROOT / 'infrastructure/docker/compose.yaml'),
        'config', '--format', 'json']
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)['services']


@pytest.mark.skipif(COMPOSE is None and DOCKER is None, reason='Docker Compose is required to render the deployment template')
def test_openrouter_template_renders_and_career_discovery_uses_strict_schema(tmp_path, monkeypatch):
    services = render(tmp_path, ROOT / 'infrastructure/docker/.env.example', {
        'OPENROUTER_API_KEY': 'synthetic-openrouter', 'OPENROUTER_MODEL': '@preset/synthetic',
    })
    prefixes = {'career-service': 'CAREER', 'cv-service': 'CV',
                'assessment-service': 'ASSESSMENT', 'roadmap-service': 'ROADMAP'}
    for service, prefix in prefixes.items():
        settings = services[service]['environment']
        assert settings['OPENROUTER_API_KEY'] == 'synthetic-openrouter'
        assert settings[prefix + '_LLM_MODEL'] == '@preset/synthetic'
        assert settings[prefix + '_LLM_BASE_URL'] == 'https://openrouter.ai/api/v1'
    for service, settings in services.items():
        if service not in prefixes:
            assert 'OPENROUTER_API_KEY' not in settings.get('environment', {})
    career = services['career-service']['environment']
    for name, value in career.items():
        if name.startswith(('CAREER_LLM_', 'OPENROUTER_', 'AI_')) and value is not None:
            monkeypatch.setenv(name, str(value))
    settings = AISettings.from_env()
    assert settings.provider == 'compatible'
    assert settings.api_key.get_secret_value() == 'synthetic-openrouter'
    payload = AIAdapter(settings, None)._payload(AIInput(stage='discovery_turn', context='{}'))
    assert payload['model'] == '@preset/synthetic'
    assert payload['response_format']['type'] == 'json_schema'
    assert payload['response_format']['json_schema']['strict'] is True


@pytest.mark.skipif(COMPOSE is None and DOCKER is None, reason='Docker Compose is required to render mixed-provider configuration')
def test_openrouter_model_does_not_override_other_provider_models(tmp_path):
    services = render(tmp_path, '/dev/null', {
        'OPENROUTER_API_KEY': 'synthetic-openrouter', 'OPENROUTER_MODEL': '@preset/synthetic',
        'CAREER_LLM_PROVIDER': 'compatible',
        'CAREER_LLM_BASE_URL': 'https://openrouter.ai/api/v1',
        'CV_LLM_BASE_URL': 'https://api.openai.com/v1',
        'CV_LLM_MODEL': 'openai-specific-model',
    })
    assert services['career-service']['environment']['CAREER_LLM_MODEL'] == 'openai/gpt-4o-mini'
    assert services['cv-service']['environment']['CV_LLM_MODEL'] == 'openai-specific-model'
    for service, prefix in [('assessment-service', 'ASSESSMENT'), ('roadmap-service', 'ROADMAP')]:
        assert services[service]['environment'][prefix + '_LLM_MODEL'] == 'openai/gpt-4o-mini'

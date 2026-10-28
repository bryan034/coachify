"""Live-reproduced JD schema rejection: simplify decoding, retain validation."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.ai.adapter import AIAdapter, AIError, MODEL_OUTPUTS, Operation, compact_schema
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.gemini_schema import gemini_schema


def nodes(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key == 'properties':
                for item in child.values():yield from nodes(item)
            else:yield from nodes(child)
    elif isinstance(value, list):
        for child in value:yield from nodes(child)


@pytest.mark.parametrize('stage', MODEL_OUTPUTS)
def test_every_stage_keeps_its_output_shape_without_reference_or_bound_expansion(stage):
    original = compact_schema(MODEL_OUTPUTS[stage].model_json_schema())
    before = deepcopy(original)
    projected = gemini_schema(original)
    assert original == before
    assert projected['properties'].keys() == original['properties'].keys()
    for item in nodes(projected):
        assert not {'$ref', '$defs', 'maxItems', 'maxLength', 'minimum', 'maximum'} & item.keys()
        if item.get('type') == 'object' and 'properties' in item:
            assert item['required'] == list(item['properties'])


def test_jd_projection_preserves_skill_condition_types_nulls_enums_and_private_metadata_boundary():
    original = compact_schema(MODEL_OUTPUTS['jd_extraction'].model_json_schema())
    projected = gemini_schema(original)
    for field, definition in [('skills', 'ExtractedSkill'), ('non_skill_requirements', 'ExtractedCondition')]:
        item = projected['properties'][field]['items']
        assert item['additionalProperties'] is False
        assert item['properties'].keys() == original['$defs'][definition]['properties'].keys()
        assert item['properties']['priority'] == original['$defs'][definition]['properties']['priority']
        assert item['properties']['origin'] == original['$defs'][definition]['properties']['origin']
        assert item['properties']['group_id']['anyOf'][-1] == {'type': 'null'}
    assert original['properties']['skills']['maxItems'] == 60
    assert original['$defs']['ExtractedSkill']['properties']['name']['maxLength'] == 160
    assert original['$defs']['ExtractedSkill']['properties']['required_experience_months']['anyOf'][0]['maximum'] == 1200


@pytest.mark.parametrize('defect', ['name_length', 'skill_count', 'duration', 'evidence_length', 'condition_count', 'extra', 'enum'])
def test_provider_success_cannot_publish_data_that_violates_original_domain_limits(defect):
    async def run():
        skill = {'name': 'SQL', 'category': 'Technical', 'priority': 'required', 'origin': 'employer'}
        output = {'role': 'Analyst', 'field': 'Data', 'company': None, 'skills': [skill]}
        if defect == 'name_length':skill['name'] = 'x' * 161
        elif defect == 'skill_count':output['skills'] = [skill] * 61
        elif defect == 'duration':skill['required_experience_months'] = 1201
        elif defect == 'evidence_length':skill['evidence'] = 'x' * 601
        elif defect == 'condition_count':output['non_skill_requirements'] = [
            {'category': 'qualification', 'description': 'Computing degree', 'priority': 'required', 'evidence': 'Computing degree'}] * 31
        elif defect == 'extra':skill['invented_field'] = 'untrusted'
        elif defect == 'enum':skill['priority'] = 'invented'
        calls = []
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = AIAdapter(AISettings(enabled=True, api_key='synthetic'), client)
            with pytest.raises(AIError, match='invalid_output'):
                await adapter.generate(AIInput(stage='jd_extraction', source_text='Analyst. SQL and a computing degree required.'),
                    Operation('synthetic', '1', 'jd_extraction'), current_revision=lambda: '1')
        assert len(calls) == 2
        assert all(call['response_format']['type'] == 'json_schema' for call in calls)
    asyncio.run(run())


def test_schema_keyword_property_names_survive_and_invalid_references_fail_closed():
    result = gemini_schema({'type': 'object', 'properties': {'maxItems': {'type': 'integer', 'minimum': 1}}})
    assert result['properties'] == {'maxItems': {'type': 'integer'}}
    for schema in ({'$ref': 'https://example.test/schema'}, {'$ref': '#/$defs/missing'},
                   {'$defs': {'loop': {'$ref': '#/$defs/loop'}}, '$ref': '#/$defs/loop'}):
        with pytest.raises(ValueError):gemini_schema(schema)


def test_compatible_test_endpoints_keep_their_requested_schema():
    request = AIInput(stage='jd_extraction', source_text='Analyst. SQL required.')
    adapter = AIAdapter(AISettings(provider='compatible', base_url='https://compatible.example.test/v1'), None)
    payload = adapter._payload(request)
    assert payload['response_format']['json_schema']['schema'] == compact_schema(MODEL_OUTPUTS['jd_extraction'].model_json_schema())

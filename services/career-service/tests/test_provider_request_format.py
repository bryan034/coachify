"""Every Career model request stays within what OpenAI accepts through OpenRouter."""
import json
import pytest
from app.ai.adapter import AIAdapter, MODEL_OUTPUTS
from app.ai.errors import AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput, Message
from app.ai.opportunity_contracts import FIELDS
from app.schemas.analysis import ResearchContext

STRICT_KEYWORDS = frozenset({'$ref', 'additionalProperties', 'anyOf', 'description', 'enum', 'items', 'maxItems',
    'maxLength', 'maximum', 'minItems', 'minLength', 'minimum', 'pattern', 'required', 'type'})
CONTEXTS = {
    'goal_summary': {'goal': {'reference': 'g1'}, 'categories': {'skills': {'reference': 'c1', 'findings': [{'reference': 'f1'}]}}},
    'interview_prep': {'gaps': [{'round_number': 1, 'field': 'interview_questions'}]},
    'role_summary': {'cards': [{'card_id': 'card-1', 'items': [{'ref': 'r1'}]}], 'missing': [{'card_id': 'card-2'}]},
    'opportunity_triage': {'topics': {'compensation': 'Intern pay.'},
        'pages': [{'ref': 0, 'url': 'https://example.test/pay', 'title': 'Pay', 'description': 'Interns earn.'}]},
}
STAGES = [stage for stage in MODEL_OUTPUTS if stage != 'opportunity_structure'] + ['opportunity_structure:' + category for category in FIELDS]


def request_for(label):
    stage, _, category = label.partition(':')
    if category:
        context = {'category': category, 'sources': [{'ref': 0}],
                   'evidence': [{'ref': 0, 'source_ref': 0, 'text': 'Synthetic passage.'}]}
    else:
        context = CONTEXTS.get(stage, {})
    encoded = json.dumps(context)
    for fields in ({'context': encoded}, {'context': encoded, 'source_text': 'Synthetic analyst role in Singapore.'},
                   {'context': encoded, 'conversation': [Message(role='user', content='Synthetic question.')]},
                   {'public_context': ResearchContext(field='Data', role='Analyst')}):
        try:
            return AIInput(stage=stage, **fields)
        except ValueError:
            continue
    return AIInput.model_construct(stage=stage, context=encoded)


def strict_violations(node, path='$'):
    """Paths that break OpenAI strict structured output rules or use an unverified keyword."""
    found = []
    if isinstance(node, dict):
        if node.get('type') == 'object' or 'properties' in node:
            if node.get('additionalProperties') is not False:
                found.append(path + ': additionalProperties must be false')
            if sorted(node.get('required', [])) != sorted(node.get('properties', {})):
                found.append(path + ': every property must be required')
        for key, value in node.items():
            if key in ('properties', '$defs'):
                for name, child in value.items():
                    found += strict_violations(child, f'{path}.{key}.{name}')
            elif key not in STRICT_KEYWORDS:
                found.append(f'{path}: unverified keyword {key}')
            else:
                found += strict_violations(value, f'{path}.{key}')
    elif isinstance(node, list):
        for index, child in enumerate(node):
            found += strict_violations(child, f'{path}[{index}]')
    return found


@pytest.mark.parametrize('label', STAGES)
def test_json_object_requests_name_json_in_the_system_prompt(label):
    adapter = AIAdapter(AISettings(response_mode='json_object'), None)
    try:
        payload = adapter._payload(request_for(label))
    except AIError as error:
        assert error.code == 'unsupported_structured_output'
        return
    assert payload['response_format'] == {'type': 'json_object'}
    assert 'json' in payload['messages'][0]['content'].lower()


@pytest.mark.parametrize('label', STAGES)
def test_strict_schemas_follow_openai_structured_output_rules(label):
    payload = AIAdapter(AISettings(response_mode='json_schema_strict'), None)._payload(request_for(label))
    response_format = payload['response_format']
    assert response_format['type'] == 'json_schema' and response_format['json_schema']['strict'] is True
    schema = response_format['json_schema']['schema']
    assert schema.get('type') == 'object'
    assert strict_violations(schema) == []

"""Keep the prompt's worked example compatible with the real evidence checks.

These synthetic responses verify the contract, not live model compliance.
"""
from copy import deepcopy
import json
import httpx
import pytest
from app.clients.extractor import EXAMPLE, Extractor, PROMPT_VERSION
from app.domain.capabilities import validate_extraction


def example_blocks():
    return [{**block, 'location': 'Synthetic example'} for block in EXAMPLE['source_blocks']]


def test_prompt_example_survives_adapter_and_evidence_validation(monkeypatch):
    monkeypatch.setenv('CV_LLM_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-test-model')
    monkeypatch.setenv('CV_LLM_BASE_URL', 'https://provider.example/v1')
    captured = []

    def transport(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(EXAMPLE['extraction'])}}]})

    original = httpx.Client
    monkeypatch.setattr('app.clients.extractor.Client',
                        lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    blocks = example_blocks()
    output, metadata = Extractor().extract(blocks)
    items = validate_extraction(output, blocks, 'synthetic-prompt-example')
    assert len(items) == len({item['id'] for item in items}) == 5
    assert items[0]['start_date'] == '2023' and items[0]['end_date'] == '2024'
    assert all(item['experience_months'] is None for item in items)
    assert items[1]['provenance'] == 'inferred'
    assert items[1]['supporting_item_ids'] == [items[0]['id']]
    assert items[-1]['proficiency'] == 'native'
    assert metadata['prompt_version'] == PROMPT_VERSION == 'cv-extraction-8'
    assert json.dumps(EXAMPLE) in captured[0]['messages'][0]['content']
    assert json.loads(captured[0]['messages'][1]['content']) == {'source_blocks': blocks}
    assert len(captured) == 1


def test_paraphrased_explicit_skill_is_still_rejected():
    output = deepcopy(EXAMPLE['extraction'])
    output['items'][0]['skill_names'].append('Data cleaning')
    with pytest.raises(ValueError, match='unsupported skill as explicit'):
        validate_extraction(output, example_blocks(), 'synthetic-explicit-check')


def test_reusing_whole_skill_list_is_still_rejected():
    output = deepcopy(EXAMPLE['extraction'])
    for item in output['items'][2:]:
        item['evidence'] = [{'block_id': 'example2', 'excerpt': EXAMPLE['source_blocks'][1]['text']}]
    with pytest.raises(ValueError, match='duplicated a source claim'):
        validate_extraction(output, example_blocks(), 'synthetic-duplicate-check')

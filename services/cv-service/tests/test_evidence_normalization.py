"""Source-preserving quote splitting must not hide unsupported evidence."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.domain.capabilities import normalize_extraction_evidence, validate_extraction
from app.domain.extraction_errors import EvidenceValidationError


def candidate(text, **fields):
    return {'items': [{'kind': 'project', 'title': 'Synthetic project',
        'description': 'Built with Python.', 'explicit': True, 'skill_names': ['Python'],
        'evidence': [{'block_id': 'b1', 'excerpt': text}], **fields}]}


def blocks(text):
    return [{'id': 'b1', 'text': text, 'location': 'Page 1'}]


@pytest.mark.parametrize('text', [
    'Project ' + 'a' * 490 + ' Python',
    ('Synthetic sentence with spaces.\n' * 25) + 'Python',
    ('Synthetic résumé 漢字 🐍\n' * 35) + 'Python',
])
def test_splitting_preserves_every_character_input_and_explicit_skill(text):
    payload = candidate(text)
    before = deepcopy(payload)
    result = validate_extraction(payload, blocks(text), 'synthetic-cv')
    assert payload == before
    evidence = result[0]['evidence']
    assert 2 <= len(evidence) <= 6
    assert all(1 <= len(ref['excerpt']) <= 500 for ref in evidence)
    assert ''.join(ref['excerpt'] for ref in evidence) == text
    assert result[0]['skill_names'] == ['Python']
    normalized = normalize_extraction_evidence(payload, blocks(text))
    assert normalize_extraction_evidence(normalized, blocks(text)) == normalized


def test_invented_suffix_cannot_be_removed_to_make_an_excerpt_pass():
    source = 'Python ' + 'a' * 500
    payload = candidate(source + ' invented suffix')
    with pytest.raises(EvidenceValidationError) as error:
        validate_extraction(payload, blocks(source), 'synthetic-cv')
    assert error.value.rule == 'source_excerpt'


def test_splitting_does_not_bypass_explicit_skill_validation():
    text = 'Other work ' + 'a' * 600
    with pytest.raises(EvidenceValidationError) as error:
        validate_extraction(candidate(text), blocks(text), 'synthetic-cv')
    assert error.value.rule == 'literal_skill'


def test_splitting_cannot_discard_text_to_fit_six_citations():
    text = 'Python ' + 'a' * 3000
    with pytest.raises(ValidationError) as error:
        validate_extraction(candidate(text), blocks(text), 'synthetic-cv')
    assert any(issue['loc'] == ('items', 0, 'evidence') and issue['type'] == 'too_long'
               for issue in error.value.errors())


def test_splitting_keeps_unknown_fields_for_schema_rejection():
    text = 'Python ' + 'a' * 600
    payload = candidate(text)
    payload['items'][0]['evidence'][0]['unexpected'] = 'untrusted'
    with pytest.raises(ValidationError) as error:
        validate_extraction(payload, blocks(text), 'synthetic-cv')
    assert all(issue['type'] == 'extra_forbidden' for issue in error.value.errors())

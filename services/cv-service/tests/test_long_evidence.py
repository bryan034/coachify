"""Evidence has no length limit, and long evidence must still be supported by its source."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.domain.capabilities import validate_extraction
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
    'Python ' + 'a' * 20_000,
])
def test_long_evidence_is_kept_whole_as_one_citation(text):
    payload = candidate(text)
    before = deepcopy(payload)
    result = validate_extraction(payload, blocks(text), 'synthetic-cv')
    assert payload == before
    assert [ref['excerpt'] for ref in result[0]['evidence']] == [text]
    assert result[0]['skill_names'] == ['Python']


def test_a_long_excerpt_with_an_invented_suffix_is_still_rejected():
    source = 'Python ' + 'a' * 500
    with pytest.raises(EvidenceValidationError) as error:
        validate_extraction(candidate(source + ' invented suffix'), blocks(source), 'synthetic-cv')
    assert error.value.rule == 'source_excerpt'


def test_long_evidence_does_not_bypass_explicit_skill_validation():
    text = 'Other work ' + 'a' * 600
    with pytest.raises(EvidenceValidationError) as error:
        validate_extraction(candidate(text), blocks(text), 'synthetic-cv')
    assert error.value.rule == 'literal_skill'


def test_empty_evidence_and_unknown_fields_are_still_rejected():
    with pytest.raises(ValidationError):
        validate_extraction(candidate(''), blocks('Python'), 'synthetic-cv')
    text = 'Python ' + 'a' * 600
    payload = candidate(text)
    payload['items'][0]['evidence'][0]['unexpected'] = 'untrusted'
    with pytest.raises(ValidationError) as error:
        validate_extraction(payload, blocks(text), 'synthetic-cv')
    assert all(issue['type'] == 'extra_forbidden' for issue in error.value.errors())

"""Interview research is organised by round; only rounds the evidence states are kept."""
import json
import pytest
from pydantic import ValidationError

from app.ai.adapter import AIAdapter
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.opportunity_contracts import PROMPTS, ReferencedFindings, findings_schema, structure_input
from app.schemas.analysis import ResearchSource
from app.schemas.opportunity import FIELDS, Finding
from app.workflows.opportunity.domain import supported_claims

STAGES = ('Round 1 is an online assessment with two coding problems. '
          'Round 2 is a technical interview with live coding. '
          'The final HR interview covers motivation.')


def source(index=0, text=STAGES):
    return ResearchSource(source_id=f's{index}', platform='other', url=f'https://example.test/{index}', evidence=text)


def claim(**changes):
    return {'field': 'round_format', 'value': 'Two timed coding problems.', 'evidence_ref': 0,
            'confidence': 'medium', 'evidence_type': 'candidate_reported', 'scope': 'exact',
            'conflict_group': None, **changes}


def resolve(*claims, category='interview_intelligence', sources=None):
    sources = sources or [source()]
    context = structure_input({}, category, sources)
    findings, rejected = supported_claims(ReferencedFindings(findings=list(claims)).to_domain(context), category, sources)
    return findings, rejected


def test_findings_keep_the_round_their_passage_names():
    findings, rejected = resolve(
        claim(round_number=1, round_name='Online assessment'),
        claim(field='interview_questions', value='Live coding.', round_number=2, round_name='Technical interview'),
        claim(field='recruitment_stages', value='Three stages are reported.'))
    assert rejected == 0
    assert [(f.round_number, f.round_name) for f in findings] == [(1, 'Online assessment'), (2, 'Technical interview'), (None, None)]


def test_a_job_with_fewer_rounds_records_only_what_the_evidence_supports():
    findings, _ = resolve(claim(round_number=1, round_name='Online assessment'),
                          sources=[source(text='There is a single round: an online assessment.')])
    assert {f.round_number for f in findings} == {1}


def test_an_unsupported_round_is_dropped_but_the_finding_is_kept():
    findings, rejected = resolve(claim(round_number=4, round_name='Case study presentation'))
    assert rejected == 0 and len(findings) == 1
    assert findings[0].round_number is None and findings[0].round_name is None


def test_a_round_name_without_a_number_is_not_saved():
    findings, _ = resolve(claim(round_name='Online assessment'))
    assert findings[0].round_name is None


def test_the_same_fact_in_two_rounds_stays_two_findings():
    findings, _ = resolve(claim(value='Live coding.', round_number=1, round_name='Online assessment'),
                          claim(value='Live coding.', round_number=2, round_name='Technical interview'))
    assert len({f.finding_id for f in findings}) == 2


def test_only_interview_research_offers_round_fields_to_the_model():
    sources = [source()]
    interview = findings_schema(structure_input({}, 'interview_intelligence', sources))
    other = findings_schema(structure_input({}, 'internship_insights', sources))
    assert {'round_number', 'round_name'} <= set(interview['$defs']['ReferencedClaim']['properties'])
    assert not {'round_number', 'round_name'} & set(other['$defs']['ReferencedClaim']['properties'])
    assert 'round_format' in FIELDS['interview_intelligence']
    payload = AIAdapter(AISettings(provider='compatible', response_mode='json_schema'), None)._payload(
        AIInput(stage='opportunity_structure', context=json.dumps(structure_input({}, 'internship_insights', sources))))
    schema = payload['response_format']['json_schema']['schema']
    item = schema['properties']['findings']['items']
    properties = (schema['$defs'][item['$ref'].split('/')[-1]] if '$ref' in item else item)['properties']
    assert 'round_number' not in properties


def test_rounds_outside_interview_research_are_ignored():
    sources = [source(text='Round 1 interns receive SGD 1500 monthly.')]
    findings, _ = resolve(claim(field='compensation', value='Interns receive SGD 1500 monthly.', round_number=1, round_name='Round 1'),
                          category='internship_insights', sources=sources)
    assert findings[0].round_number is None


def test_saved_findings_reject_impossible_rounds():
    base = {'finding_id': 'f' + '0' * 16, 'field': 'round_format', 'value': 'Coding test.', 'confidence': 'low',
            'evidence_type': 'candidate_reported', 'source_ids': ['s0'], 'quotes': ['Coding test.'], 'scope': 'exact',
            'last_verified_at': '2026-11-10T00:00:00Z'}
    assert Finding(**base).round_number is None
    for bad in ({'round_number': 0}, {'round_number': 11}, {'round_name': 'Online assessment'}):
        with pytest.raises(ValidationError):
            Finding(**base, **bad)


def test_the_prompt_asks_for_every_round_without_padding():
    prompt = PROMPTS['opportunity_structure']
    assert 'cover every interview round' in prompt and 'never pad to a typical count' in prompt
    assert 'every interview round' in PROMPTS['opportunity_plan']


def test_public_finding_contract_matches_the_application():
    from pathlib import Path
    from app.main import create_app
    saved = json.loads((Path(__file__).resolve().parents[3] / 'contracts/api/career.yaml').read_text())
    assert saved['components']['schemas']['PublicFinding'] == create_app().openapi()['components']['schemas']['PublicFinding']

import copy
import json
from pathlib import Path
from bson import BSON, ObjectId
from bson.codec_options import CodecOptions
import pytest
from pydantic import ValidationError
from app.domain.analysis import ContractConflict, validate_analysis, validate_inputs
from app.domain.skills import canonical_skill_id
from app.schemas.analysis import (CareerGoal, CvSnapshot, InterviewResearch, ResearchContext,
    SkillGapAnalysis, mongo_document)


@pytest.mark.parametrize('scenario', ['specific_job', 'career_exploration'])
def test_both_goal_scenarios_preserve_null_company_and_unknown_proficiency(documents, scenario):
    data = documents['goal']
    data['target_type'] = scenario
    if scenario == 'career_exploration':
        data['requirements_source'] = 'career_exploration'
        data['skills'][0]['origin'] = 'generated_guidance'
    goal = CareerGoal.model_validate(data)
    assert goal.company is None
    assert goal.skills[0].required_proficiency is None
    assert goal.model_dump(by_alias=True)['_id'] == data['_id']


def test_objectids_roundtrip_bson_without_changing_account_uuid(documents):
    goal = CareerGoal.model_validate(documents['goal'])
    data = mongo_document(goal)
    assert isinstance(data['_id'], ObjectId)
    assert isinstance(data['user_id'], str)
    restored = BSON(BSON.encode(data)).decode(codec_options=CodecOptions(tz_aware=True))
    assert CareerGoal.model_validate(restored) == goal


@pytest.mark.parametrize('field,value', [('source_text', 'full description'), ('raw_jd', 'full description'),
    ('extracted_text', 'full description'), ('career_target_id', '000000000000000000000002')])
def test_raw_jd_and_obsolete_fields_are_rejected(documents, field, value):
    data = documents['goal']; data[field] = value
    with pytest.raises(ValidationError): CareerGoal.model_validate(data)


@pytest.mark.parametrize('field,value', [('user_id', 'not-an-account'), ('_id', 'bad'), ('version', 0),
    ('version', True), ('created_at', '2026-01-01T00:00:00'), ('role', 'x'*161)])
def test_invalid_identity_versions_dates_and_bounds(documents, field, value):
    data = documents['goal']; data[field] = value
    with pytest.raises(ValidationError): CareerGoal.model_validate(data)


@pytest.mark.parametrize('field,value', [('experience_months', -1), ('experience_months', True),
    ('proficiency', 'excellent'), ('evidence', 'x'*601)])
def test_cv_capabilities_are_bounded_and_honest(documents, field, value):
    data = documents['cv']; data['skills'][0][field] = value
    with pytest.raises(ValidationError): CvSnapshot.model_validate(data)


def test_personal_declaration_is_sufficient_no_evidence_upload(documents):
    cv = CvSnapshot.model_validate(documents['cv'])
    assert cv.skills[0].evidence_type == 'user_declaration'
    assert cv.skills[0].original_evidence != cv.skills[0].evidence
    assert cv.skills[0].proficiency is None


def test_same_name_different_context_is_not_merged(documents):
    aliases = {('language', 'python'): 'language.python', ('tool', 'python'): 'tool.python'}
    assert canonical_skill_id(' Python ', 'LANGUAGE', aliases) != canonical_skill_id('Python', 'tool', aliases)
    with pytest.raises(ValueError): canonical_skill_id('unknown', 'language', aliases)


def test_research_reuse_normalizes_spacing_and_case_but_preserves_context():
    a = ResearchContext(field='Software', role='Engineer', company=None)
    b = ResearchContext(field=' software ', role='ENGINEER', company=None)
    c = ResearchContext(field='Software', role='Engineer', company='Example')
    assert a.reuse_key() == b.reuse_key() != c.reuse_key()


@pytest.mark.parametrize('defect', ['source_id', 'duplicate_source', 'duplicate_url', 'report_count', 'private_data'])
def test_research_rejects_forged_or_duplicate_sources_and_private_fields(documents, defect):
    research = documents['research']
    if defect == 'source_id': research['skills'][0]['source_ids'] = ['forged']
    if defect == 'duplicate_source': research['sources'].append(copy.deepcopy(research['sources'][0]))
    if defect == 'duplicate_url':
        second = copy.deepcopy(research['sources'][0]); second['source_id'] = 'other'
        second['url'] += '#duplicate'; research['sources'].append(second)
    if defect == 'report_count': research['skills'][0]['independent_report_count'] = 2
    if defect == 'private_data': research['user_id'] = documents['goal']['user_id']
    with pytest.raises(ValidationError): InterviewResearch.model_validate(research)


def test_reposts_count_once(documents):
    data = documents['research']
    second = copy.deepcopy(data['sources'][0]); second.update(source_id='repost', url='https://example.test/repost')
    data['sources'].append(second); data['skills'][0]['source_ids'].append('repost')
    assert InterviewResearch.model_validate(data).skills[0].independent_report_count == 1


def test_three_source_analysis_matches_exact_versions(documents):
    result = SkillGapAnalysis.model_validate(documents['analysis'])
    validate_analysis(result, CvSnapshot.model_validate(documents['cv']), CareerGoal.model_validate(documents['goal']),
        [InterviewResearch.model_validate(documents['research'])], 1)


@pytest.mark.parametrize('defect', ['owner', 'missing', 'cv_version', 'profile_version', 'goal_version',
    'research_version', 'context', 'mapping', 'failed_cv', 'unavailable_research'])
def test_analysis_rejects_foreign_missing_and_stale_snapshots(documents, defect):
    cv, goal, research = documents['cv'], documents['goal'], documents['research']
    owner = goal['user_id']; profile_version = 1
    if defect == 'owner': cv['user_id'] = '22222222-2222-4222-8222-222222222222'
    if defect == 'cv_version': cv['version'] = 2
    if defect == 'goal_version': goal['version'] = 2
    if defect == 'research_version': research['version'] = 2
    if defect == 'context': research['role'] = 'Different role'
    if defect == 'mapping': cv['skill_mapping_version'] = 'new-map'
    if defect == 'profile_version': profile_version = 2
    if defect == 'failed_cv': cv.update(extraction_status='failed', skills=[])
    if defect == 'unavailable_research': research.update(research_status='failed', skills=[])
    result = SkillGapAnalysis.model_validate(documents['analysis'])
    with pytest.raises(ContractConflict):
        validate_inputs(owner, result.inputs, None if defect == 'missing' else CvSnapshot.model_validate(cv),
            CareerGoal.model_validate(goal), [InterviewResearch.model_validate(research)], profile_version)


def test_missing_research_is_partial_and_unknown_not_shortfall(documents):
    data = documents['analysis']; data['research_ids'] = []; data['inputs']['research'] = []
    data['interview_prep_gaps'] = []
    with pytest.raises(ValidationError): SkillGapAnalysis.model_validate(data)
    data['analysis_status'] = 'partial'
    assert SkillGapAnalysis.model_validate(data).analysis_status == 'partial'
    data['job_skill_gaps'][0]['match_status'] = 'confirmed_shortfall'
    with pytest.raises(ValidationError): SkillGapAnalysis.model_validate(data)


def test_json_schema_artifacts_match_models():
    root = Path(__file__).resolve().parents[3] / 'contracts/api/models'
    for name, model in [('career-goal', CareerGoal), ('interview-research', InterviewResearch),
                        ('skill-gap-analysis', SkillGapAnalysis), ('cv', CvSnapshot)]:
        assert json.loads((root / f'{name}.schema.json').read_text()) == model.model_json_schema(by_alias=True)


def test_mutated_model_instances_cannot_bypass_validation(documents):
    goal = CareerGoal.model_validate(documents['goal'])
    goal.skills.append({'skill_id': 'invalid'})
    with pytest.raises(ValidationError): CareerGoal.model_validate(goal)


def test_nested_source_dates_and_generation_roundtrip_as_bson_dates(documents):
    from datetime import datetime
    data=documents['research']
    data['sources'][0]['published_date']='2025-01-01'
    data['generation']['generated_at']='2026-01-01T00:00:00.123456Z'
    record=InterviewResearch.model_validate(data)
    stored=mongo_document(record)
    assert isinstance(stored['sources'][0]['published_date'],datetime)
    assert isinstance(stored['generation']['generated_at'],datetime)
    restored=BSON(BSON.encode(stored)).decode(codec_options=CodecOptions(tz_aware=True))
    assert InterviewResearch.model_validate(restored)==record


def test_unmapped_research_remains_readable_but_cannot_establish_gaps(documents):
    from app.domain.analysis import validate_inputs,ContractConflict
    from app.schemas.analysis import InputVersions
    cv=CvSnapshot.model_validate(documents['cv']);goal=CareerGoal.model_validate(documents['goal'])
    data=documents['research'];data['skills'][0]['skill_id']=None
    research=InterviewResearch.model_validate(data)
    with pytest.raises(ContractConflict,match='need skill mapping'):
        validate_inputs(goal.user_id,InputVersions.model_validate(documents['analysis']['inputs']),cv,goal,[research],1)


def test_legacy_importance_normalizes_and_conflicts_block_readiness(documents):
    data=documents['goal'];data['skills'][0]['priority']='essential'
    assert CareerGoal.model_validate(data).skills[0].priority=='required'
    data['skills'][0]['priority']='conflicting'
    with pytest.raises(ValidationError):CareerGoal.model_validate(data)
    data['readiness']='pending'
    assert CareerGoal.model_validate(data).skills[0].priority=='conflicting'

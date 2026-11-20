import copy
import json
from pathlib import Path
from bson import BSON, ObjectId
from bson.codec_options import CodecOptions
import pytest
from pydantic import ValidationError
from app.domain.skills import canonical_skill_id
from app.schemas.analysis import CareerGoal, CvSnapshot, InterviewResearch, ResearchContext, mongo_document


def read_stored_goal(document):
    """Exercise the real repository boundary for operational storage metadata."""
    from app.repositories.analysis import AnalysisRepository
    class Collection:
        def find_one(self,query):
            assert query=={'_id':document['_id'],'user_id':document['user_id']}
            return copy.deepcopy(document)
    class Database:
        def with_options(self,**_):return self
        def __getitem__(self,name):
            assert name=='career_goals'
            return Collection()
    return AnalysisRepository(Database()).get_private('career_goals',str(document['_id']),document['user_id'])


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
    assert 'create_key' not in restored
    assert read_stored_goal(restored)==goal


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


def test_json_schema_artifacts_match_models():
    root = Path(__file__).resolve().parents[3] / 'contracts/api/models'
    for name, model in [('career-goal', CareerGoal), ('interview-research', InterviewResearch),
                        ('career-cv-snapshot', CvSnapshot)]:
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


def test_legacy_importance_normalizes_and_conflicts_block_readiness(documents):
    data=documents['goal'];data['skills'][0]['priority']='essential'
    assert CareerGoal.model_validate(data).skills[0].priority=='required'
    data['skills'][0]['priority']='conflicting'
    with pytest.raises(ValidationError):CareerGoal.model_validate(data)
    data['readiness']='pending'
    assert CareerGoal.model_validate(data).skills[0].priority=='conflicting'


@pytest.mark.parametrize('cv_id', ['22222222-2222-4222-8222-222222222222', '000000000000000000000001'])
def test_cv_references_roundtrip_without_remapping_career_identity(documents, cv_id):
    from app.schemas.goals import CvContext, StartExploration
    goal = CareerGoal.model_validate({**documents['goal'], 'source_cv_id': cv_id})
    stored = mongo_document(goal)
    assert isinstance(stored['_id'], ObjectId)
    assert stored['source_cv_id'] == (ObjectId(cv_id) if len(cv_id) == 24 else cv_id)
    restored = BSON(BSON.encode(stored)).decode(codec_options=CodecOptions(tz_aware=True))
    restored_goal=read_stored_goal(restored)
    assert restored_goal.id==goal.id and restored_goal.user_id==goal.user_id
    assert restored_goal.source_cv_id==cv_id
    assert CvContext(mode='saved', cv_id=cv_id).cv_id == cv_id
    assert StartExploration(consent=True, cv_id=cv_id).cv_id == cv_id


@pytest.mark.parametrize('cv_id', ['not-a-reference', '../other', '22222222-2222-4222-8222-22222222222Z'])
def test_cv_reference_validation_does_not_relax_career_domain_ids(documents, cv_id):
    from app.schemas.goals import StartExploration
    with pytest.raises(ValidationError): StartExploration(consent=True, cv_id=cv_id)
    with pytest.raises(ValidationError): CareerGoal.model_validate({**documents['goal'], '_id': '22222222-2222-4222-8222-222222222222'})


def test_shared_skill_identity_preserves_legacy_keys_and_never_guesses_unknowns(documents):
    from app.schemas.analysis import TargetSkill
    data=documents['goal']['skills'][0]
    skill=TargetSkill.model_validate({**data,'name':'Structured Query Language','category':'Unspecified','skill_id':None})
    assert skill.canonical_skill_id=='language.sql'
    assert skill.skill_id is None
    assert skill.skill_registry_version=='skills-v2'
    unknown=TargetSkill.model_validate({**data,'name':'Unregistered niche tool','skill_id':None})
    assert unknown.canonical_skill_id is None


def test_job_dates_preserve_partial_wording_and_full_date_requires_exact_source_text():
    from elo_shared.dates import JobDate
    partial=JobDate(kind='job_start',text='April 2030',evidence='The role starts in April 2030.')
    assert partial.date is None
    exact=JobDate(kind='job_start',text='1 April 2030',evidence='Start date: 1 April 2030.')
    assert exact.date=='2030-04-01'
    with pytest.raises(ValidationError):JobDate(kind='job_start',text='1 April 2030',evidence='Start sometime in April.')

import asyncio
import json
import httpx
import pytest
from app.clients.cvs import CvClient
from app.repositories.goals import GoalError


def test_cv_api_boundary_uses_metadata_then_owner_scoped_effective_snapshot(documents):
    row=documents['cv'];seen=[]
    summary={key:row[key] for key in ('_id','user_id','file_name','extraction_status','extraction_version','version')}
    def handler(request):
        seen.append(request.url.path)
        assert request.headers['Authorization']=='Bearer synthetic'
        return httpx.Response(200,json={'items':[summary]} if request.url.path=='/api/v1/cv' else row)
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test',transport=httpx.MockTransport(handler)) as http:
            client=CvClient(http)
            assert (await client.list('Bearer synthetic'))[0].id==row['_id']
            assert (await client.get(row['_id'],'Bearer synthetic',row['user_id'])).skills[0].proficiency is None
            with pytest.raises(GoalError): await client.get(row['_id'],'Bearer synthetic','foreign-owner')
    asyncio.run(check())
    assert seen==['/api/v1/cv','/api/v1/cv/'+row['_id'],'/api/v1/cv/'+row['_id']]


def test_saved_cv_pagination_keeps_later_legacy_choices_and_owner_header(saved_cv):
    first={**saved_cv,'id':'11111111-1111-4111-8111-111111111111'}
    seen=[]
    def handler(request):
        seen.append(str(request.url));assert request.headers['Authorization']=='Bearer synthetic'
        if request.url.params.get('cursor')=='older/page+key':
            return httpx.Response(200,json={'cvs':[saved_cv],'selection':{'cv_id':saved_cv['id'],'version':1},'next_cursor':None})
        return httpx.Response(200,json={'cvs':[first],'selection':{'cv_id':saved_cv['id'],'version':1},'next_cursor':'older/page+key'})
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test',transport=httpx.MockTransport(handler)) as http:
            assert [row.id for row in await CvClient(http).list('Bearer synthetic')]==[first['id'],saved_cv['id']]
    asyncio.run(check())
    assert len(seen)==2 and 'older%2Fpage%2Bkey' in seen[1]


@pytest.mark.parametrize('continuation',['repeat','empty','bytes'])
def test_saved_cv_pagination_rejects_loops_and_enforces_one_total_budget(saved_cv,monkeypatch,continuation):
    from app.clients import cvs
    calls=[]
    if continuation=='bytes':monkeypatch.setattr(cvs,'MAX_CV_RESPONSE_BYTES',len(json.dumps({'cvs':[saved_cv],'next_cursor':'next'}).encode())+100)
    def handler(request):
        calls.append(request)
        page=[saved_cv] if len(calls)==1 or continuation!='empty' else []
        if continuation=='bytes' and len(calls)>1:page=[{**saved_cv,'id':'11111111-1111-4111-8111-111111111111'}]
        return httpx.Response(200,json={'cvs':page,'next_cursor':'next'})
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test',transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(GoalError) as outcome:await CvClient(http).list('Bearer synthetic')
            assert outcome.value.status==(413 if continuation=='bytes' else 503)
    asyncio.run(check())
    assert len(calls)==2


@pytest.fixture
def saved_cv(documents):
    source = {'item_id': 'project-original', 'evidence_type': 'user_clarified', 'explicit': False,
              'support_uncertain': False, 'attribution': 'personal', 'assistance': 'supervised',
              'proficiency': None, 'experience_months': 2.5,
              'evidence': [{'id': 'quote-one', 'excerpt': 'I wrote SQL with my tutor.', 'location': 'clarification'}]}
    return {'id': '22222222-2222-4222-8222-222222222222', 'file_name': 'synthetic.docx',
        'file_type': 'docx', 'status': 'ready', 'version': 4, 'extraction_version': 1,
        'effective_version': 3, 'profile_version': 1, 'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-02T00:00:00Z', 'skills': [{'skill_id': 'skill:sql', 'name': 'SQL',
        'category': 'Language', 'proficiency': None, 'experience_months': 2.5, 'context': None,
        'evidence': source['evidence'], 'evidence_type': 'user_clarified', 'explicit': False,
        'item_ids': ['project-original'], 'sources': [source], 'conflicting_fields': []}]}


def test_saved_cv_boundary_preserves_original_ids_unknowns_and_personal_source(saved_cv, documents):
    from app.clients.cvs import MAPPING_VERSION
    owner = documents['cv']['user_id']
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer synthetic'
        return httpx.Response(200, json={'cvs': [saved_cv], 'selection': {'cv_id': None, 'version': 0}}
            if request.url.path == '/api/v1/cv' else saved_cv)
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test', transport=httpx.MockTransport(handler)) as http:
            client = CvClient(http)
            summary = (await client.list('Bearer synthetic'))[0]
            assert summary.id == saved_cv['id'] and summary.user_id is None
            assert summary.extraction_status == 'succeeded'
            cv = await client.get(saved_cv['id'], 'Bearer synthetic', owner)
            assert cv.id == saved_cv['id'] and cv.user_id == owner
            assert cv.skill_mapping_version == MAPPING_VERSION
            assert cv.skills[0].skill_id == 'skill:sql'
            assert cv.skills[0].proficiency is None
            assert cv.skills[0].experience_months == 2.5
            assert cv.skills[0].model_dump()['sources'] == saved_cv['skills'][0]['sources']
            assert cv.skills[0].item_ids == ['project-original']
            assert cv.skills[0].model_dump()['source_evidence'] == saved_cv['skills'][0]['evidence']
    asyncio.run(check())


@pytest.mark.parametrize('change', ['foreign_owner', 'wrong_identity', 'not_ready', 'negative_months', 'malformed_evidence'])
def test_saved_cv_rejects_unavailable_foreign_or_malformed_snapshot(saved_cv, documents, change):
    if change == 'foreign_owner': saved_cv['user_id'] = '33333333-3333-4333-8333-333333333333'
    if change == 'wrong_identity': saved_cv['id'] = '33333333-3333-4333-8333-333333333333'
    if change == 'not_ready': saved_cv['status'] = 'processing'
    if change == 'negative_months': saved_cv['skills'][0]['experience_months'] = -1
    if change == 'malformed_evidence': saved_cv['skills'][0]['evidence'] = 'unsupported'
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test', transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=saved_cv))) as http:
            with pytest.raises(GoalError):
                await CvClient(http).get('22222222-2222-4222-8222-222222222222', 'Bearer synthetic', documents['cv']['user_id'])
    asyncio.run(check())


def test_saved_cv_does_not_truncate_long_evidence_or_invent_supported_proficiency(saved_cv, documents):
    from app.clients.cvs import saved_snapshot
    saved_cv['skills'][0]['evidence'][0]['excerpt'] = 'Exact source statement. ' * 40
    saved_cv['skills'][0]['proficiency'] = 'working familiarity'
    cv = saved_snapshot(saved_cv, documents['cv']['user_id'])
    assert cv.skills[0].evidence is None
    assert cv.skills[0].model_dump()['source_evidence'] == saved_cv['skills'][0]['evidence']
    assert cv.skills[0].proficiency is None
    assert cv.skills[0].reported_proficiency == 'working familiarity'


def test_saved_cv_accepts_more_than_two_hundred_skills_and_aggregate_excerpts_within_byte_limit(saved_cv, documents):
    from copy import deepcopy
    from app.clients.cvs import saved_snapshot
    skill = saved_cv['skills'][0]
    excerpts = [{'id': f'quote-{i}', 'excerpt': f'Exact statement {i}', 'location': 'Synthetic source'} for i in range(201)]
    skill['evidence'] = excerpts
    skill['sources'] = [{**deepcopy(skill['sources'][0]), 'item_id': f'project-{i}', 'evidence': excerpts[i * 6:(i + 1) * 6]} for i in range(34)]
    skill['item_ids'] = [source['item_id'] for source in skill['sources']]
    saved_cv['skills'] += [{**deepcopy(skill), 'skill_id': f'skill:skill-{i}', 'name': f'Skill {i}',
        'evidence': [], 'sources': [], 'item_ids': []} for i in range(200)]
    cv = saved_snapshot(saved_cv, documents['cv']['user_id'])
    assert len(cv.skills) == 201
    assert len(cv.skills[0].source_evidence) == 201
    assert cv.skills[0].source_evidence[-1].excerpt == 'Exact statement 200'
    assert cv.skills[0].sources[-1].item_id == 'project-33'


@pytest.mark.parametrize('declared_length', [True, False])
def test_oversize_cv_response_reports_actionable_intake_limit_before_decoding(saved_cv, documents, declared_length):
    from app.clients.cvs import MAX_CV_RESPONSE_BYTES
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b' ' * (MAX_CV_RESPONSE_BYTES // 2)
            yield b' ' * (MAX_CV_RESPONSE_BYTES // 2 + 1)
    def handler(request):
        return httpx.Response(200, stream=Stream(), headers={
            'content-length': str(MAX_CV_RESPONSE_BYTES + 1)} if declared_length else {})
    async def check():
        async with httpx.AsyncClient(base_url='http://cv.test', transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(GoalError, match='512 KiB.*smaller saved CV') as caught:
                await CvClient(http).get(saved_cv['id'], 'Bearer synthetic', documents['cv']['user_id'])
            assert caught.value.status == 413
    asyncio.run(check())

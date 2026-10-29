from copy import deepcopy
from io import BytesIO
import os
from uuid import uuid4
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZipInfo
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.core.config import Settings
from app.main import create_app
from app.repositories.cv import MemoryCvRepository, CvRepository


TEXT = ['Education: Example University, Computing',
        'Project A: Team built a Python and SQL application.',
        'Independent SQL queries for a personal dataset.']


def docx(paragraphs=TEXT):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr(ZipInfo('[Content_Types].xml', (2020, 1, 1, 0, 0, 0)), '<Types/>')
        archive.writestr(ZipInfo('word/document.xml', (2020, 1, 1, 0, 0, 0)), '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
            ''.join('<w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p>' for text in paragraphs) + '</w:body></w:document>')
    return output.getvalue()


class FakeExtractor:
    configured = True
    failure = None
    payload = None

    def extract(self, blocks):
        if self.failure: raise ValueError(self.failure)
        items = [{'kind': 'education', 'title': 'Example University', 'description': blocks[0]['text'],
                  'explicit': True, 'evidence': [{'block_id': blocks[0]['id'], 'excerpt': blocks[0]['text']}]}]
        if len(blocks) > 1:
            items.append({'kind': 'project', 'title': 'Project A', 'description': blocks[1]['text'], 'explicit': True,
                'evidence': [{'block_id': blocks[1]['id'], 'excerpt': blocks[1]['text']}],
                'skill_names': ['Python', 'SQL'], 'uncertainties': ['personal_contribution']})
        if len(blocks) > 2:
            items.append({'kind': 'skill', 'title': 'SQL', 'description': blocks[2]['text'], 'explicit': True,
                'evidence': [{'block_id': blocks[2]['id'], 'excerpt': blocks[2]['text']}],
                'skill_names': ['SQL'], 'uncertainties': ['proficiency']})
        return deepcopy(self.payload or {'items': items}), {'provider': 'synthetic-test', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}


class FakeTargets:
    context_value = None
    async def context(self, authorization, identifier, version): return self.context_value
    async def selected_context(self, authorization): return self.context_value


class FakeInterpreter:
    """Explicit synthetic provider responses; not a production language parser."""
    configured = True
    payload = None
    failure = None
    calls = 0
    before_return = None

    def interpret(self, item, question, answer, answer_revision):
        self.calls += 1
        if self.before_return: self.before_return()
        if self.failure: raise ValueError(self.failure)
        if self.payload is not None:
            output = self.payload(item, question, answer, answer_revision) if callable(self.payload) else deepcopy(self.payload)
            output.setdefault('item_id', item['id'])
            output.setdefault('answer_revision', answer_revision)
        else:
            uncertainty = question['uncertainty']
            output = {'item_id': item['id'], 'answer_revision': answer_revision, 'resolution': 'resolved',
                'claims': [], 'resolved_uncertainties': [uncertainty], 'remaining_uncertainties': []}
            if uncertainty in {'personal_contribution', 'responsibility'}:
                for identifier, name in zip(item['skill_ids'], item['skill_names']):
                    attribution = 'team' if name == 'SQL' and 'teammate wrote SQL' in answer else 'personal' if name == 'Python' and 'I built the Python' in answer else 'unknown'
                    claim = {'skill_id': identifier, 'name': name, 'attribution': attribution,
                        'changed_fields': ['attribution'], 'evidence_excerpt': answer if attribution != 'unknown' else None}
                    if attribution == 'personal' and 'guidance' in answer:
                        claim.update(assistance='assisted', changed_fields=['attribution', 'assistance'])
                    if attribution == 'personal' and 'supervision' in answer:
                        claim.update(assistance='supervised', changed_fields=['attribution', 'assistance'])
                    output['claims'].append(claim)
                if 'I cleaned data with pandas' in answer:
                    output['claims'].append({'skill_id': 'skill:pandas', 'name': 'pandas', 'attribution': 'personal',
                        'changed_fields': ['attribution'], 'evidence_excerpt': 'I cleaned data with pandas.'})
                if any(c['attribution'] == 'unknown' for c in output['claims']):
                    output.update(resolution='partial', resolved_uncertainties=[], remaining_uncertainties=[uncertainty])
            elif uncertainty == 'proficiency' and 'basic joins' in answer:
                output['claims'] = [{'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'unknown',
                    'proficiency': 'basic joins', 'assistance': 'independent' if 'independently' in answer else 'assisted',
                    'changed_fields': ['proficiency', 'assistance'], 'evidence_excerpt': answer}]
            else:
                output.update(resolution='unanswerable', resolved_uncertainties=[], remaining_uncertainties=[uncertainty])
        return output, {'provider': 'synthetic-test', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}


class ProfileTransport:
    declaration_version = 1
    race = False
    calls = 0
    onboarding = True
    revoked = False
    async def __call__(self, request):
        owner = request.headers.get('authorization', '').removeprefix('Bearer ')
        if self.revoked or owner not in {'owner-a', 'owner-b'}: return httpx.Response(401, json={})
        if request.url.path.endswith('/auth/session'):
            return httpx.Response(200, json={'id': owner, 'email_verified': True})
        if request.url.path.endswith('/capabilities'):
            self.calls += 1
            return httpx.Response(200, json={'version': self.declaration_version + (self.calls if self.race else 0),
                'declarations': [{'id': 'manual-1', 'name': 'Pandas', 'description': 'I cleaned data with pandas', 'provenance': 'user_declared'}]})
        return httpx.Response(200, json={'onboarding_complete': self.onboarding, 'version': 4})


@pytest.fixture(params=['memory', 'mongo'])
def repository(request):
    if request.param == 'memory': yield MemoryCvRepository(); return
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri: pytest.skip('Set MONGODB_TEST_URI to exercise real MongoDB CAS and recovery.')
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = 'coachify_cv_test_' + uuid4().hex
    try: yield CvRepository(client[name])
    finally:
        client.drop_database(name)
        client.close()


@pytest.fixture
def harness(tmp_path, repository):
    extractor, targets, transport = FakeExtractor(), FakeTargets(), ProfileTransport()
    profile = httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url='http://profile')
    app = create_app(repository=repository, profile_client=profile, extractor=extractor, interpreter=FakeInterpreter(),
                     target_provider=targets, settings=Settings(storage_path=str(tmp_path)), start_worker=False)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer owner-a'
        yield client, app, extractor, targets, transport


def upload(client, data=None, name='same-name.docx', mutation_id=None, **fields):
    return client.post('/api/v1/cv/uploads', files={'file': (name, data if data is not None else docx(),
        'application/pdf' if name.endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
        data={'mutation_id': mutation_id or str(uuid4()), **fields})


def ready(harness):
    client, app, *_ = harness
    response = upload(client)
    assert response.status_code == 202, response.text
    app.state.worker.run_once()
    result = client.get('/api/v1/cv/' + response.json()['id']).json()
    assert result['status'] == 'ready', result
    return result


def mutation(version, **fields): return {'expected_version': version, 'mutation_id': str(uuid4()), **fields}

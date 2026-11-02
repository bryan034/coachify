"""Profile intake publication and declaration concurrency on both account adapters."""
from copy import deepcopy
from uuid import uuid4
import pytest
from pydantic import ValidationError
from elo_shared.skills_profile import SkillsProfileWrite
from app.domain.capabilities import CapabilityConflict
from app.repositories.skills_profile import SkillsProfileRepository
from tests.test_capabilities import database, repo, client, payload


def entry():
    evidence = [{'message_id': 'synthetic-turn', 'quote': 'I combined reports with pandas each week.'}]
    return {'id': str(uuid4()), 'kind': 'project', 'title': 'Report automation',
        'fields': {'description': {'status': 'answered', 'value': 'Combined weekly reports', 'evidence': evidence}},
        'skills': [{'name': 'pandas', 'description': 'Combined weekly reports using pandas.', 'evidence': evidence,
            'dimensions': {'frequency': {'status': 'answered', 'value': 'Weekly', 'evidence': evidence}}}]}


def write(version=0, **changes):
    return SkillsProfileWrite(expected_version=version, mutation_id=uuid4(), **changes)


def test_draft_save_and_confirmed_declaration_publication_preserve_account(repo):
    skills = SkillsProfileRepository(repo)
    original = deepcopy(repo.account('alice'))
    experience = entry()
    draft = skills.save('alice', write(entries=[experience]))
    assert draft['status'] == 'draft' and draft['version'] == 1
    assert repo.current('alice')['declarations'] == []
    request = write(1, status='saved', entries=[experience])
    saved = skills.save('alice', request)
    assert saved['status'] == 'saved' and saved['saved_at']
    declarations = repo.current('alice')
    assert declarations['version'] == 1
    declaration = declarations['declarations'][0]
    assert declaration['source_entry_id'] == experience['id']
    assert any(c['description'] == 'Frequency: Weekly' for c in declaration['contributions'])
    assert declaration['proficiency'] is declaration['independence'] is None
    assert skills.save('alice', request) == saved
    assert skills.current('bob')['entries'] == []
    assert all(repo.account('alice')[key] == value for key, value in original.items())
    skills.save('alice', write(saved['version'], status='saved', entries=[experience]))
    assert repo.current('alice')['version'] == 1  # A review alone does not change effective declarations.


def test_stale_profile_and_key_reuse_rejected_without_losing_declarations(repo):
    skills = SkillsProfileRepository(repo)
    request = write(entries=[entry()])
    skills.save('alice', request)
    with pytest.raises(CapabilityConflict):
        skills.save('alice', request.model_copy(update={'status': 'saved'}))
    with pytest.raises(CapabilityConflict):
        skills.save('alice', write(status='saved', entries=[]))
    repo.create('alice', payload(name='SQL'))
    skills.save('alice', write(1, status='saved', entries=request.entries))
    assert {d['name'] for d in repo.current('alice')['declarations']} == {'SQL', 'pandas'}


def test_acknowledgement_loss_recovers_and_concurrent_capability_is_not_overwritten(repo, monkeypatch):
    skills = SkillsProfileRepository(repo)
    request = write(status='saved', entries=[entry()])
    update = repo.accounts.update_one
    failed = False
    def lost_response(query, body):
        nonlocal failed
        result = update(query, body)
        if 'skills_profile' in body['$set'] and not failed:
            failed = True
            raise RuntimeError('synthetic acknowledgement loss')
        return result
    monkeypatch.setattr(repo.accounts, 'update_one', lost_response)
    with pytest.raises(RuntimeError): skills.save('alice', request)
    assert skills.save('alice', request)['status'] == 'saved'
    assert len(repo.current('alice')['declarations']) == 1


def test_intake_endpoints_auth_owner_strict_shape_and_nullable_unknowns(client):
    assert client.get('/api/v1/profile/skills-profile').status_code == 401
    headers = {'Authorization': 'Bearer alice'}
    data = write(areas={'work': 'not_applicable', 'education': 'unknown'}).model_dump(mode='json')
    response = client.put('/api/v1/profile/skills-profile', headers=headers, json=data)
    assert response.status_code == 200, response.text
    assert response.json()['areas']['work'] == 'not_applicable'
    assert client.get('/api/v1/profile/skills-profile', headers={'Authorization': 'Bearer bob'}).json()['status'] == 'empty'
    assert client.put('/api/v1/profile/skills-profile', headers=headers, json={**data, 'user_id': 'bob-id'}).status_code == 422
    bad = entry(); bad['fields']['description']['evidence'] = []
    with pytest.raises(ValidationError): write(entries=[bad])


def test_uncommitted_profile_candidate_cannot_overwrite_a_concurrent_declaration(repo, monkeypatch):
    skills = SkillsProfileRepository(repo)
    insert = skills.receipts.insert_one
    raced = False
    def concurrent(candidate):
        nonlocal raced
        result = insert(candidate)
        if candidate['mutation_id'].startswith('skills-profile:') and not raced:
            raced = True
            repo.create('alice', payload(name='SQL'))
        return result
    monkeypatch.setattr(skills.receipts, 'insert_one', concurrent)
    request = write(status='saved', entries=[entry()])
    with pytest.raises(CapabilityConflict): skills.save('alice', request)
    with pytest.raises(CapabilityConflict): skills.save('alice', request)
    assert skills.current('alice')['status'] == 'empty'
    assert [d['name'] for d in repo.current('alice')['declarations']] == ['SQL']
    skills.save('alice', write(status='saved', entries=request.entries))
    assert {d['name'] for d in repo.current('alice')['declarations']} == {'SQL', 'pandas'}


def test_removing_an_intake_skill_preserves_separately_attached_user_descriptions(repo):
    skills = SkillsProfileRepository(repo)
    saved = skills.save('alice', write(status='saved', entries=[entry()]))
    declaration = repo.current('alice')['declarations'][0]
    repo.create('alice', payload(expected_version=1, name='pandas', mutation_id='extra-statement',
        mode='attach', attach_to_id=declaration['id'], description='I also used pandas for an independent volunteering task.'))
    skills.save('alice', write(saved['version'], status='saved', entries=[]))
    remaining = repo.current('alice')['declarations']
    assert len(remaining) == 1 and remaining[0]['source_entry_id'] is None
    assert remaining[0]['description'] == 'I also used pandas for an independent volunteering task.'
    assert len(remaining[0]['contributions']) == 1


def test_profile_contract_matches_runtime(client):
    from pathlib import Path
    import yaml
    contract = yaml.safe_load((Path(__file__).resolve().parents[3] / 'contracts/api/profile.yaml').read_text())
    runtime = client.app.openapi()
    assert contract['paths']['/api/v1/profile/skills-profile'] == runtime['paths']['/api/v1/profile/skills-profile']
    for name in ('SkillsProfile', 'SkillsProfileWrite', 'ProfileEntry', 'ProfileSkill', 'IntakeField'):
        assert contract['components']['schemas'][name] == runtime['components']['schemas'][name]

from app.domain.skill_list import merge, skill_list
from tests.conftest import ready, select


def entry(name, canonical=None, kind='cv', level=None, application=None, basis='none', category=None):
    return {'canonical_skill_id': canonical, 'name': name, 'category': category, 'level': level, 'application': application,
            'proficiency': None, 'basis': basis, 'added_in_review': False, 'note': None, 'sources': [{'kind': kind, 'id': kind + ':' + name}]}


def rated(level, status='rated'):
    return {'level': level, 'status': status, 'rationale': '', 'source': 'review', 'evidence': []}


def test_one_entry_per_identity_even_when_only_one_source_resolves_the_registry():
    skills = merge([entry('Excel', 'tool.excel', category='Tools'), entry('excel ', kind='declaration', basis='declared'),
                    entry('Kanban', kind='chat', basis='described'), entry('KANBAN', kind='declaration', basis='declared')])
    assert [(s['key'], len(s['sources'])) for s in skills] == [('tool.excel', 2), ('name:kanban', 2)]


def test_a_null_identity_source_listed_first_still_joins_the_canonical_skill():
    skills = merge([entry('Python', kind='declaration', basis='declared'), entry('Python', 'language.python')])
    assert len(skills) == 1 and skills[0]['key'] == 'language.python' and skills[0]['canonical_skill_id'] == 'language.python'


def test_ambiguous_name_keeps_unresolved_evidence_separate_from_known_skills():
    skills = merge([entry('Modeling', 'data.modeling'), entry('Modeling', 'design.modeling'),
                    entry('Modeling', kind='declaration', basis='declared')])
    assert [(skill['key'], len(skill['sources'])) for skill in skills] == [
        ('data.modeling', 1), ('design.modeling', 1), ('name:modeling', 1),
    ]


def test_strength_prefers_rated_then_assumed_levels_then_application_estimates():
    skills = merge([entry('SQL', 'database.sql', level=rated(7, 'assumed'), basis='level'),
                    entry('SQL', 'database.sql', level=rated(4), basis='level'),
                    entry('SQL', 'database.sql', application='complex_application', basis='application')])
    assert skills[0]['level']['level'] == 4 and skills[0]['level']['status'] == 'rated'
    estimate = merge([entry('Go', application='guided_application', basis='application'), entry('Go', basis='declared', kind='declaration')])
    assert estimate[0]['basis'] == 'application' and estimate[0]['application'] == 'guided_application'


def test_display_groups_are_keyed_by_the_listed_name():
    result = skill_list(None, {'version': 2, 'status': 'saved', 'entries': [{'id': 'e1', 'kind': 'project', 'title': 'Synthetic', 'skills': [
        {'name': 'Python', 'canonical_skill_id': None, 'description': 'Built scripts.', 'evidence': [{'message_id': 'm', 'quote': 'scripts'}], 'dimensions': {}}]}]},
        {'version': 3, 'declarations': []}, [])
    assert result['skills'][0]['name'] in result['skill_groups']
    assert result['skills'][0]['basis'] == 'described' and result['profile_version'] == 2 and result['declarations_version'] == 3


def test_route_merges_the_active_cv_with_manual_capabilities_and_reports_missing_sources(harness):
    client, app, _, _, transport = harness
    cv = ready(harness)
    select(client, cv['id'])
    response = client.get('/api/v1/cv/skills')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['cv_id'] == cv['id'] and body['cv_version'] == cv['version']
    assert 'chat' in body['unavailable']
    names = {skill['name'] for skill in body['skills']}
    assert 'Pandas' in names and {s['name'] for s in cv['skills']} <= names
    assert all(skill['name'] in body['skill_groups'] for skill in body['skills'])
    assert client.get('/api/v1/cv/skills', params={'cv_id': 'unknown'}).status_code == 404
    client.headers['Authorization'] = 'Bearer owner-b'
    assert client.get('/api/v1/cv/skills', params={'cv_id': cv['id']}).status_code == 404
    transport.revoked = True
    assert client.get('/api/v1/cv/skills').status_code == 401

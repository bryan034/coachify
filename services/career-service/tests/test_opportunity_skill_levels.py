"""The research run rates the level the role needs in each goal skill; failure never blocks research."""
import json
from types import SimpleNamespace
from uuid import uuid4
from app.ai.opportunity_contracts import SkillLevels
from tests.test_opportunity import opportunity_flow, research  # noqa: F401 (fixture)
from tests.test_workspace import headers, ingest


def rate(flow, level=None, error=None):
    primary = flow[2]; original = primary.generate; calls = []
    async def generate(request, operation, **kwargs):
        if request.stage != 'opportunity_skill_levels': return await original(request, operation, **kwargs)
        data = json.loads(request.context); calls.append(data)
        if error: raise error
        finding = data['findings'][0]['id']
        output = SkillLevels(levels=[{'skill': s['name'], 'level': level, 'employer_demand': 'Use it in daily analysis work.',
                                      'reported_examples': [{'text': 'Candidates were asked about it in interviews.', 'finding_id': finding}],
                                      'rationale': 'Interviews test this in practice.', 'finding_ids': [finding]} for s in data['skills']])
        if kwargs.get('validate_output'): kwargs['validate_output'](output)
        return SimpleNamespace(data=output)
    primary.generate = generate
    return calls


def test_research_rates_every_goal_skill_and_sets_its_target(opportunity_flow):
    flow = opportunity_flow; calls = rate(flow, level=4)
    assert ingest(flow).status_code == 202
    workspace, result, _ = research(flow)
    assert result['status'] == 'completed' and len(calls) == 1
    assert set(calls[0]) == {'opportunity', 'skills', 'findings'}
    assert all(set(s) == {'name', 'priority', 'stated_proficiency', 'required_experience_months', 'employer_context', 'reference_level', 'reference_factors'}
               for s in calls[0]['skills'])
    assert all(s['reference_factors'][0].endswith(f"baseline {s['reference_level']}") or len(s['reference_factors']) > 1 for s in calls[0]['skills'])
    skills = [s for s in workspace['current']['goal']['skills'] if s['origin'] != 'user_declaration']
    assert skills and all(s['competence_target']['level'] >= 4 for s in skills)
    rated = [s['competence_target'] for s in skills if s['competence_target']['level'] == 4 and s['competence_target']['basis'] == 'research']
    assert rated and all(t['source_urls'] for t in rated)
    assert all(t['employer_demand'] == 'Use it in daily analysis work.' and t['rating_reason'] == 'Interviews test this in practice.'
               and [e['text'] for e in t['reported_examples']] == ['Candidates were asked about it in interviews.']
               and t['reported_examples'][0]['source_url'] for t in rated)
    saved = flow[1].interview_research.find_one({'intelligence': {'$ne': None}})['intelligence']['skill_levels']
    assert {r['skill'] for r in saved} == {s['name'] for s in calls[0]['skills']}


def test_a_failed_rating_keeps_the_research_and_the_weighted_reference_targets(opportunity_flow):
    flow = opportunity_flow; calls = rate(flow, error=RuntimeError('provider down'))
    assert ingest(flow).status_code == 202
    workspace, result, _ = research(flow)
    assert result['status'] == 'completed' and len(calls) == 1
    assert flow[1].interview_research.find_one({'intelligence': {'$ne': None}})['intelligence']['skill_levels'] == []
    assert all(s['competence_target']['basis'] in ('job_description', 'inferred') for s in workspace['current']['goal']['skills'])


def test_a_failed_refresh_rating_does_not_reuse_the_cached_levels(opportunity_flow):
    flow = opportunity_flow
    rate(flow, level=9)
    assert ingest(flow).status_code == 202
    workspace, _, path = research(flow)
    original = flow[1].interview_research.find_one({'intelligence': {'$ne': None}})
    assert original['intelligence']['skill_levels']

    calls = rate(flow, error=RuntimeError('provider down'))
    body = {
        'expected_version': workspace['current']['goal']['version'],
        'expected_selection_version': workspace['current']['selection_version'],
        'refresh': True,
        'category': 'company_intelligence',
    }
    assert flow[0].post(path, headers=headers(str(uuid4())), json=body).status_code == 202
    _, result, _ = research(flow)
    assert result['status'] == 'completed' and len(calls) == 1
    refreshed = flow[1].interview_research.find_one({'_id': {'$ne': original['_id']}, 'intelligence': {'$ne': None}})
    assert refreshed['intelligence']['skill_levels'] == []

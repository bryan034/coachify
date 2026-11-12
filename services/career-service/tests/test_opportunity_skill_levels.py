"""The research run rates the level the role needs in each goal skill; failure never blocks research."""
import json
from types import SimpleNamespace
from app.ai.opportunity_contracts import SkillLevels
from tests.test_opportunity import opportunity_flow, research  # noqa: F401 (fixture)
from tests.test_workspace import ingest


def rate(flow, level=None, error=None):
    primary = flow[2]; original = primary.generate; calls = []
    async def generate(request, operation, **kwargs):
        if request.stage != 'opportunity_skill_levels': return await original(request, operation, **kwargs)
        data = json.loads(request.context); calls.append(data)
        if error: raise error
        finding = data['findings'][0]['id']
        output = SkillLevels(levels=[{'skill': s['name'], 'level': level, 'rationale': 'Interviews test this in practice.',
                                      'finding_ids': [finding]} for s in data['skills']])
        if kwargs.get('validate_output'): kwargs['validate_output'](output)
        return SimpleNamespace(data=output)
    primary.generate = generate
    return calls


def test_research_rates_every_goal_skill_and_sets_its_target(opportunity_flow):
    flow = opportunity_flow; calls = rate(flow, level=4)
    assert ingest(flow).status_code == 202
    workspace, result, _ = research(flow)
    assert result['status'] == 'completed' and len(calls) == 1
    # Only public role facts, skill names and validated findings are sent: no job text or CV.
    assert set(calls[0]) == {'opportunity', 'skills', 'findings'}
    assert all(set(s) == {'name', 'priority', 'stated_proficiency'} for s in calls[0]['skills'])
    skills = [s for s in workspace['current']['goal']['skills'] if s['origin'] != 'user_declaration']
    assert skills and all(s['competence_target']['level'] >= 4 for s in skills)
    assert any(s['competence_target']['level'] == 4 and s['competence_target']['basis'] == 'research'
               and s['competence_target']['source_urls'] for s in skills)
    saved = flow[1].interview_research.find_one({'intelligence': {'$ne': None}})['intelligence']['skill_levels']
    assert {r['skill'] for r in saved} == {s['name'] for s in calls[0]['skills']}


def test_a_failed_rating_keeps_the_research_and_the_description_based_targets(opportunity_flow):
    flow = opportunity_flow; calls = rate(flow, error=RuntimeError('provider down'))
    assert ingest(flow).status_code == 202
    workspace, result, _ = research(flow)
    assert result['status'] == 'completed' and len(calls) == 1  # Not retried by durable recovery.
    assert flow[1].interview_research.find_one({'intelligence': {'$ne': None}})['intelligence']['skill_levels'] == []
    assert all(s['competence_target']['basis'] in ('job_description', 'inferred') for s in workspace['current']['goal']['skills'])

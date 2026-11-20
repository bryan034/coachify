"""Role targets on the shared 1-10 scale: the research model decides, guided by a weighted reference score."""
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from app.ai.errors import AIError
from app.ai.opportunity_contracts import PROMPTS, SkillLevels
from app.domain.competence import target_for, calibrated_goal
from app.repositories.goals import now
from app.schemas.jd import JDExtraction, ReviewSkill
from app.workflows.opportunity.domain import validated_skill_levels


def skill(name='Python', **values):
    return ReviewSkill(**{'name': name, 'category': 'Technical', 'priority': 'required', 'origin': 'employer', **values})


def goal(role='Analyst', seniority=None, employment='unknown', skills=(), company=None, field=None):
    return JDExtraction(role=role, field=field, company=company, seniority_level=seniority, employment_type=employment, skills=list(skills))


@pytest.mark.parametrize('role,seniority,employment,base', [
    ('Analyst', None, 'unknown', 5), ('Analyst', None, 'internship', 5), ('Analyst', 'Senior', 'full_time', 7),
    ('Senior Data Engineer', None, 'full_time', 7), ('Graduate Analyst', None, 'full_time', 5), ('Analyst', 'Mid-level', 'full_time', 6),
    ('Lead Engineer', None, 'unknown', 8), ('Principal Engineer', None, 'unknown', 9), ('Software Engineering Intern', None, 'unknown', 5)])
def test_the_role_band_sets_the_baseline(role, seniority, employment, base):
    target = target_for(skill('Excel', priority='conflicting', evidence='Excel'), None, goal(role, seniority, employment))
    assert (target.level, target.basis) == (base, 'inferred') and 'estimated it from the role' in target.explanation


def test_importance_and_experience_move_the_score():
    role = goal('Machine Learning Engineer', 'Graduate')
    assert target_for(skill('Machine learning'), None, role).level == 7
    assert target_for(skill('SQL'), None, role).level == 7
    assert target_for(skill('SQL', priority='preferred'), None, role).level == 7
    assert target_for(skill('SQL', priority='unspecified'), None, role).level == 6
    assert target_for(skill('SQL', required_experience_months=12), None, role).level == 8
    assert target_for(skill('SQL', required_experience_months=13), None, role).level == 9
    assert target_for(skill('SQL', required_experience_months=37), None, role).level == 10


def test_targets_spread_instead_of_clustering():
    role = goal('Senior Machine Learning Engineer', employment='full_time')
    levels = [target_for(s, None, role).level for s in (skill('Machine learning', required_experience_months=24),
                                                        skill('Docker', priority='preferred'), skill('Kubernetes', priority='unspecified'))]
    assert levels == [10, 9, 8]


@pytest.mark.parametrize('role,company,field', [
    ('Statistics Intern', None, None), ('Quantitative Trading Intern', 'Optiver', None),
    ('Summer Analyst', 'Goldman Sachs', None), ('Summer Intern', None, 'Investment Banking')])
def test_the_reference_leaves_role_defining_skills_and_selectivity_to_the_model(role, company, field):
    role_goal = goal(role, employment='internship', company=company, field=field)
    for name in ('Statistical modelling', 'Probability'):
        target = target_for(skill(name), None, role_goal)
        assert target.level == 7 and 'core to the role title' not in target.explanation and 'selective' not in target.explanation
    assert target_for(skill('Probability'), report(9, name='Probability'), role_goal).level == 9


def test_ordinary_internships_are_not_treated_as_selective():
    for ordinary in (goal('Marketing Intern', employment='internship', company='Shopee'),
                     goal('Data Analyst Intern', employment='internship', field='Banking')):
        assert target_for(skill('Probability'), None, ordinary).level == 7


def test_a_rated_internship_skill_reaches_a_high_target_without_an_internship_cap():
    optiver = goal('Quantitative Trading Intern', employment='internship', company='Optiver')
    target = target_for(skill('Quantitative problem solving'), None, optiver)
    assert target.level == 7 and 'Research hasn’t rated' in target.explanation
    rated = report(10, name='Quantitative problem solving')
    assert target_for(skill('Quantitative problem solving'), rated, optiver).level == 10


@pytest.mark.parametrize('text,proficiency,level,basis', [
    ('Expert Python knowledge', None, 9, 'job_description'), ('Advanced Python', None, 7, 'inferred'),
    ('Python', 'intermediate', 7, 'inferred'), ('Basic Python', None, 3, 'job_description'), ('Python', 'beginner', 3, 'job_description')])
def test_stated_employer_wording_is_a_floor_or_basic_ceiling(text, proficiency, level, basis):
    target = target_for(skill(evidence=text, required_proficiency=proficiency), None, goal('Analyst', employment='internship'))
    assert (target.level, target.basis) == (level, basis)
    assert target_for(skill(evidence='Basic Python'), None, goal('Analyst', 'Senior')).level == 3


def test_only_employer_skills_state_a_bound():
    target = target_for(skill(evidence='Expert Python', origin='user_declaration'), None, goal())
    assert (target.level, target.basis) == (7, 'inferred')


def report(level=None, *, name='Python', cited=('f1',), expired=False, status='completed', findings=None):
    findings = findings or [NS(finding_id='f1', source_ids=['source1'], value='Teams use Python daily.')]
    categories = {}
    for category, finding in findings if isinstance(findings[0], tuple) else [('internship_insights', f) for f in findings]:
        categories.setdefault(category, NS(findings=[])).findings.append(finding)
    ratings = [NS(skill=name, level=level, rationale='Interviews test scripting.', finding_ids=list(cited))] if level else []
    sources = {s for result in categories.values() for f in result.findings for s in f.source_ids}
    return NS(intelligence=NS(status=status, expires_at=now() + timedelta(days=-1 if expired else 1),
                              categories=categories, skill_levels=ratings),
              sources=[NS(source_id=s, url=f'https://example.test/{s}') for s in sorted(sources)])


def finding(index, value, sources):
    return NS(finding_id=f'f{index}', source_ids=list(sources), value=value)


def test_wide_and_interview_research_each_add_a_level_and_cite_sources():
    wide = report(findings=[finding(1, 'Python is used across teams.', ['a', 'b']), finding(2, 'Most staff write python.', ['c'])])
    target = target_for(skill(), wide, goal())
    assert (target.level, target.basis) == (8, 'research') and len(target.source_urls) == 3
    probed = report(findings=[('interview_intelligence', finding(1, 'Interviewers ask Python questions.', ['a']))])
    assert target_for(skill(), probed, goal()).level == 8
    assert target_for(skill('Java'), probed, goal()).level == 7


def test_research_signals_match_the_skill_name_as_a_phrase_but_not_lookalike_words():
    named = report(findings=[('interview_intelligence', finding(1, 'Interviews test quantitative problem solving live.', ['a']))])
    assert target_for(skill('Quantitative problem solving'), named, goal()).level == 8
    symbol = report(findings=[('interview_intelligence', finding(1, 'Expect C++ questions.', ['a']))])
    assert target_for(skill('C++'), symbol, goal()).level == 8
    assert target_for(skill('C'), symbol, goal()).level == 7
    lookalike = report(findings=[('interview_intelligence', finding(1, 'Excellent communication is assessed.', ['a']))])
    assert target_for(skill('Excel'), lookalike, goal()).level == 7
    reworded = report(findings=[('interview_intelligence', finding(1, 'Candidates solve quantitative problems live.', ['a']))])
    assert target_for(skill('Quantitative problem solving'), reworded, goal()).level == 7


def test_the_research_model_decides_the_level_and_the_weights_are_its_reference():
    target = target_for(skill(), report(9), goal())
    assert (target.level, target.basis) == (9, 'research') and target.source_urls == ['https://example.test/source1']
    assert target.explanation == target.rating_reason == 'Interviews test scripting.'
    assert target_for(skill(), report(2), goal('Analyst', employment='internship')).level == 2
    uncited = target_for(skill(), report(3, cited=()), goal())
    assert (uncited.level, uncited.basis) == (3, 'inferred') and uncited.rating_reason == 'Interviews test scripting.'


def test_a_level_the_employer_states_still_bounds_the_model_rating():
    assert target_for(skill(evidence='Advanced Python'), report(4), goal()).level == 7
    assert target_for(skill(evidence='Advanced Python'), report(9), goal()).level == 9
    capped = target_for(skill(evidence='Basic Python'), report(6), goal())
    assert (capped.level, capped.basis) == (3, 'job_description')


def test_the_estimate_names_the_employment_type_inferred_by_research():
    research = report(3, name='Java')
    research.intelligence.employment_type = 'internship'
    target = target_for(skill(), research, goal())
    assert target.level == 7 and 'internship' in target.explanation and not any(ch.isdigit() for ch in target.explanation)


def test_long_stored_rationale_keeps_the_employer_bound_first():
    research = report(9)
    research.intelligence.skill_levels[0].rationale = 'Candidate interview feedback. ' * 25
    target = target_for(skill(evidence='Basic Python'), research, goal(employment='internship'))
    assert (target.level, target.basis) == (3, 'job_description')
    assert target.explanation.startswith('The job description asks only for basic understanding (3).')
    assert target.rating_reason.startswith('The job description asks only for basic understanding (3).')
    assert len(target.explanation) <= 600 and target.explanation.endswith('…')


def test_a_research_rating_explains_the_employer_demand_examples_and_reason():
    research = report(8, findings=[('interview_intelligence', finding(1, 'Interviewers asked candidates to debug a Python script.', ['a', 'b']))])
    rating = research.intelligence.skill_levels[0]
    rating.employer_demand = 'Write and maintain Python services independently.'
    rating.reported_examples = [NS(text='Candidates were asked to debug a Python script live.', finding_id='f1'),
                                NS(text='Not in this report.', finding_id='missing')]
    target = target_for(skill(), research, goal())
    assert target.employer_demand == 'Write and maintain Python services independently.'
    assert [(e.text, e.source_url) for e in target.reported_examples] == [('Candidates were asked to debug a Python script live.', 'https://example.test/a')]
    assert target.rating_reason == target.explanation == 'Interviews test scripting.'
    old = report(8); target = target_for(skill(), old, goal())
    assert (target.employer_demand, target.reported_examples, target.rating_reason) == (None, [], 'Interviews test scripting.')


@pytest.mark.parametrize('research', [report(9, expired=True), report(9, status='failed'), report(9, name='JavaScript'), None])
def test_without_a_fresh_rating_the_weighted_reference_is_the_target(research):
    assert target_for(skill(), research, goal()).level == 7


def test_rating_input_carries_the_weighted_reference_for_each_skill():
    from app.workflows.opportunity.domain import weighted_skills
    probed = report(findings=[('interview_intelligence', finding(1, 'Interviewers ask Python questions.', ['a']))]).intelligence.categories
    rows = weighted_skills([{'name': 'Python', 'priority': 'required', 'stated_proficiency': None, 'required_experience_months': None},
                            {'name': 'Excel', 'priority': 'unspecified', 'stated_proficiency': None, 'required_experience_months': None}],
                           {'role': 'Data Intern', 'seniority_level': None, 'employment_type': 'internship'}, probed)
    assert [(r['name'], r['reference_level']) for r in rows] == [('Python', 8), ('Excel', 6)]
    assert rows[0]['reference_factors'] == ['internship baseline 5', 'essential to the role +2', 'probed in reported interviews +1']
    selective = weighted_skills([{'name': 'Python', 'priority': 'required'}],
                                {'role': 'Trading Intern', 'seniority_level': None, 'employment_type': 'internship', 'company': 'Optiver'}, None)
    assert selective[0]['reference_level'] == 7
    assert selective[0]['reference_factors'] == ['internship baseline 5', 'essential to the role +2']


def test_current_goal_enrichment_keeps_saved_goal_and_source_provenance_intact():
    saved = goal(skills=[skill(evidence='Python')])
    current = calibrated_goal(saved, report(9))
    assert current.skills[0].competence_target.level == 9
    assert saved.skills[0].competence_target is None
    assert current.skills[0].evidence == saved.skills[0].evidence


def test_saving_recomputes_targets_only_for_changed_inputs():
    from app.domain.review import prepare
    before = prepare(goal(skills=[skill(item_id='a'), skill('SQL', item_id='b')]), extracted=False, map_skills=False)
    edited = before.model_copy(update={'skills': [before.skills[0].model_copy(update={'priority': 'unspecified'}), before.skills[1]]})
    after = prepare(edited, before, map_skills=False)
    assert [s.competence_target.level for s in before.skills] == [7, 7]
    assert after.skills[0].competence_target.level == 6 and after.skills[1].competence_target == before.skills[1].competence_target
    retitled = prepare(before.model_copy(update={'seniority_level': 'Senior'}), before, map_skills=False)
    assert [s.competence_target.level for s in retitled.skills] == [9, 9]
    employer = prepare(before.model_copy(update={'company': 'Jane Street'}), before, map_skills=False)
    assert [s.competence_target.level for s in employer.skills] == [7, 7]



def test_an_unchanged_skill_saved_without_a_target_is_rated_on_save():
    from app.domain.review import prepare
    before = prepare(goal(skills=[skill(item_id='a')]), extracted=False, map_skills=False)
    unrated = before.model_copy(update={'skills': [before.skills[0].model_copy(update={'competence_target': None})]})
    after = prepare(unrated, unrated, map_skills=False)
    assert after.skills[0].competence_target is not None and after.skills[0].competence_target.level == 7

SKILLS = [{'name': 'Python', 'priority': 'required', 'stated_proficiency': None},
          {'name': 'SQL', 'priority': 'preferred', 'stated_proficiency': None}]


def rated(*levels):
    return SkillLevels(levels=[{'skill': name, 'level': level, 'rationale': 'Needed for the role.', 'finding_ids': ids}
                               for name, level, ids in levels])


def test_model_must_rate_every_goal_skill_once_and_cite_real_findings():
    result = validated_skill_levels(rated(('python', 6, ['f1']), ('SQL', 4, [])), SKILLS, {'f1'})
    assert [(r['skill'], r['level'], r['finding_ids']) for r in result] == [('Python', 6, ['f1']), ('SQL', 4, [])]
    for bad in (rated(('Python', 6, [])), rated(('Python', 6, []), ('Python', 5, []), ('SQL', 4, [])),
                rated(('Python', 6, ['invented']), ('SQL', 4, [])), rated(('Python', 6, []), ('Rust', 4, []))):
        with pytest.raises(AIError): validated_skill_levels(bad, SKILLS, {'f1'})


def test_rating_prompt_uses_the_shared_scale_and_research():
    prompt = PROMPTS['opportunity_skill_levels']
    assert '1 = No understanding' in prompt and '4-6 = moderate understanding' in prompt and '10 = Expert understanding' in prompt
    assert 'crowd-sourced' in prompt and 'not what tasks they can execute alone' in prompt
    assert 'findings' in prompt and 'exactly one entry per skill' in prompt
    assert 'Treat required and preferred skills as essential' in prompt
    assert 'reference_level' in prompt and 'reference_factors' in prompt and 'you decide the level' in prompt
    assert 'guidelines, not rules' in prompt and 'not a floor or a ceiling' in prompt and 'real hiring bar' in prompt and 'quantitative trading' in prompt
    assert 'rarely need more than 3-5' not in prompt


def test_reported_examples_must_restate_findings_of_this_report():
    def with_example(finding_id):
        return SkillLevels(levels=[{'skill': 'Python', 'level': 6, 'employer_demand': '**Build** data pipelines.',
                                    'reported_examples': [{'text': 'Asked to write a **generator**.', 'finding_id': finding_id}],
                                    'rationale': 'Interviews probe it.', 'finding_ids': ['f1']},
                                   {'skill': 'SQL', 'level': 4, 'rationale': 'Light use.', 'finding_ids': []}])
    result = validated_skill_levels(with_example('f1'), SKILLS, {'f1'})
    assert result[0]['employer_demand'] == 'Build data pipelines.'
    assert result[0]['reported_examples'] == [{'text': 'Asked to write a generator.', 'finding_id': 'f1'}]
    assert (result[1]['employer_demand'], result[1]['reported_examples']) == (None, [])
    with pytest.raises(AIError): validated_skill_levels(with_example('invented'), SKILLS, {'f1'})

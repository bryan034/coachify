"""Role targets on the shared 1-10 scale: scored deterministically from the role, the skill and its research."""
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.opportunity_contracts import PROMPTS, SkillLevels
from app.domain.competence import target_for, calibrated_goal
from app.repositories.goals import now
from app.schemas.jd import JDExtraction, ReviewSkill
from app.workflows.opportunity.domain import validated_skill_levels


def skill(name='Python', **values):
    return ReviewSkill(**{'name': name, 'category': 'Technical', 'priority': 'required', 'origin': 'employer', **values})


def goal(role='Analyst', seniority=None, employment='unknown', skills=()):
    return JDExtraction(role=role, field=None, company=None, seniority_level=seniority, employment_type=employment, skills=list(skills))


@pytest.mark.parametrize('role,seniority,employment,base', [
    ('Analyst', None, 'unknown', 5), ('Analyst', None, 'internship', 3), ('Analyst', 'Senior', 'full_time', 7),
    ('Senior Data Engineer', None, 'full_time', 7), ('Graduate Analyst', None, 'full_time', 4), ('Lead Engineer', None, 'unknown', 8),
    ('Principal Engineer', None, 'unknown', 9), ('Software Engineering Intern', None, 'unknown', 3)])
def test_the_role_band_sets_the_baseline(role, seniority, employment, base):
    # A conflicting-priority skill not named in the title adds nothing to the baseline.
    target = target_for(skill('Excel', priority='conflicting', evidence='Excel'), None, goal(role, seniority, employment))
    assert (target.level, target.basis) == (base, 'inferred') and 'planning estimate' in target.explanation


def test_importance_title_and_experience_move_the_score():
    role = goal('Machine Learning Engineer', 'Mid-level')
    assert target_for(skill('Machine learning'), None, role).level == 7           # 5 + essential + named in title
    assert target_for(skill('SQL'), None, role).level == 6                        # 5 + essential
    assert target_for(skill('SQL', priority='preferred'), None, role).level == 6  # Preferred is essential too.
    assert target_for(skill('SQL', priority='unspecified'), None, role).level == 4
    assert target_for(skill('SQL', required_experience_months=60), None, role).level == 8
    assert target_for(skill('SQL', required_experience_months=6), None, role).level == 5


def test_targets_spread_instead_of_clustering():
    role = goal('Senior Machine Learning Engineer', employment='full_time')
    levels = [target_for(s, None, role).level for s in (skill('Machine learning'), skill('Docker', priority='preferred'),
                                                        skill('Kubernetes', priority='unspecified'))]
    assert levels == [9, 8, 6]


@pytest.mark.parametrize('text,proficiency,level', [
    ('Expert Python knowledge', None, 9), ('Advanced Python', None, 7), ('Proficient in Python', None, 7),
    ('Python', 'intermediate', 5), ('Basic Python', None, 3), ('Python', 'beginner', 3)])
def test_stated_employer_wording_is_a_floor_or_basic_ceiling(text, proficiency, level):
    # Internship baseline 3 + essential = 4: floors lift it, the basic ceiling caps it.
    target = target_for(skill(evidence=text, required_proficiency=proficiency), None, goal('Analyst', employment='internship'))
    assert target.level == level and target.basis == ('inferred' if level == 4 else 'job_description')
    assert target_for(skill(evidence='Basic Python'), None, goal('Analyst', 'Senior')).level == 3


def test_only_employer_skills_state_a_bound():
    target = target_for(skill(evidence='Expert Python', origin='user_declaration'), None, goal())
    assert (target.level, target.basis) == (6, 'inferred')


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
    assert (target.level, target.basis) == (7, 'research') and len(target.source_urls) == 3
    probed = report(findings=[('interview_intelligence', finding(1, 'Interviewers ask Python questions.', ['a']))])
    assert target_for(skill(), probed, goal()).level == 7
    # A finding about another skill is not evidence for this one.
    assert target_for(skill('Java'), probed, goal()).level == 6


def test_a_cited_research_rating_nudges_by_at_most_one_level():
    assert target_for(skill(), report(9), goal()).level == 7
    assert target_for(skill(), report(2), goal()).level == 5
    assert target_for(skill(), report(6), goal()).level == 6
    assert 'research rated it 9' in target_for(skill(), report(9), goal()).explanation


@pytest.mark.parametrize('research', [report(9, cited=()), report(9, expired=True), report(9, status='failed'),
                                      report(9, name='JavaScript'), None])
def test_uncited_stale_failed_or_other_skill_ratings_are_ignored(research):
    assert target_for(skill(), research, goal()).level == 6


def test_current_goal_enrichment_keeps_saved_goal_and_source_provenance_intact():
    saved = goal(skills=[skill(evidence='Python')])
    current = calibrated_goal(saved, report(9))
    assert current.skills[0].competence_target.level == 7
    assert saved.skills[0].competence_target is None
    assert current.skills[0].evidence == saved.skills[0].evidence


def test_saving_recomputes_targets_only_for_changed_inputs():
    from app.domain.review import prepare
    before = prepare(goal(skills=[skill(item_id='a'), skill('SQL', item_id='b')]), extracted=False, map_skills=False)
    edited = before.model_copy(update={'skills': [before.skills[0].model_copy(update={'priority': 'unspecified'}), before.skills[1]]})
    after = prepare(edited, before, map_skills=False)
    assert [s.competence_target.level for s in before.skills] == [6, 6]
    assert after.skills[0].competence_target.level == 4 and after.skills[1].competence_target == before.skills[1].competence_target
    retitled = prepare(before.model_copy(update={'seniority_level': 'Senior'}), before, map_skills=False)
    assert [s.competence_target.level for s in retitled.skills] == [8, 8]


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

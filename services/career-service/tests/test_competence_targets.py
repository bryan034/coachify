"""Role targets on the shared 1-10 scale: rated from research, with the stated JD level as a floor."""
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.opportunity_contracts import PROMPTS, SkillLevels
from app.domain.competence import target_for, calibrated_goal
from app.repositories.goals import now
from app.schemas.jd import ReviewSkill
from app.workflows.opportunity.domain import validated_skill_levels


def skill(**values):
    return ReviewSkill(name='Python', category='Technical', priority='required', origin='employer', **values)


@pytest.mark.parametrize('text,level,basis', [
    ('Python is required', 5, 'inferred'), ('Familiar with Python', 5, 'job_description'),
    ('Basic Python', 3, 'job_description'), ('Advanced Python', 7, 'job_description'),
    ('Proficient in Python', 7, 'job_description'), ('Expert Python knowledge', 9, 'job_description')])
def test_without_research_the_stated_wording_sets_the_target(text, level, basis):
    target = target_for(skill(evidence=text))
    assert (target.level, target.basis) == (level, basis)
    assert 'planning' in target.explanation


def report(level, *, name='Python', finding_ids=('f1',), expired=False, status='completed'):
    finding = NS(finding_id='f1', source_ids=['source1'])
    rating = NS(skill=name, level=level, rationale='Interviews test independent scripting.', finding_ids=list(finding_ids))
    return NS(intelligence=NS(status=status, expires_at=now() + timedelta(days=-1 if expired else 1),
                              categories={'interview_intelligence': NS(findings=[finding])}, skill_levels=[rating]),
              sources=[NS(source_id='source1', url='https://employer.example/skills')])


def test_research_rating_sets_the_target_and_cites_its_sources():
    target = target_for(skill(evidence='Python is required'), report(6))
    assert (target.level, target.basis) == (6, 'research')
    assert target.source_urls == ['https://employer.example/skills']
    assert 'Interviews test independent scripting.' in target.explanation
    # Research may rate an unstated skill below the default: not every role needs independence in it.
    assert target_for(skill(evidence='Python is required'), report(3)).level == 3


def test_a_level_the_employer_states_is_a_floor_for_research():
    assert target_for(skill(evidence='Advanced Python'), report(4)).level == 7
    assert target_for(skill(evidence='Advanced Python'), report(9)).level == 9


def test_a_rating_without_cited_findings_is_labelled_inferred():
    target = target_for(skill(evidence='Python is required'), report(6, finding_ids=()))
    assert (target.level, target.basis) == (6, 'inferred') and 'did not address' in target.explanation


@pytest.mark.parametrize('research', [report(8, expired=True), report(8, status='failed'), report(8, name='JavaScript'), None])
def test_stale_failed_or_other_skill_ratings_are_ignored(research):
    assert target_for(skill(evidence='Python is required'), research).level == 5


def test_current_goal_enrichment_keeps_saved_goal_and_source_provenance_intact():
    from app.schemas.jd import JDExtraction
    goal = JDExtraction(role='Engineer', field=None, company=None, skills=[skill(evidence='Python')])
    current = calibrated_goal(goal, report(6))
    assert current.skills[0].competence_target.level == 6
    assert goal.skills[0].competence_target is None
    assert current.skills[0].evidence == goal.skills[0].evidence


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
    assert '1 = Not competent' in prompt and '5 = Independent and understands' in prompt and '10 = Expert' in prompt
    assert 'findings' in prompt and 'exactly one entry per skill' in prompt

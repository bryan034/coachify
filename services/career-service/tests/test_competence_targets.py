from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from app.domain.competence import target_for,calibrated_goal
from app.repositories.goals import now
from app.schemas.jd import ReviewSkill


def skill(**values):
    return ReviewSkill(name='Python',category='Technical',priority='required',origin='employer',**values)


@pytest.mark.parametrize('text,level',[
    ('Familiar with Python',8),('Advanced Python',9),('Proficient in Python',9),
    ('Expert Python knowledge',10),('Python is required',8)])
def test_role_target_uses_strict_stated_expectations(text,level):
    target=target_for(skill(evidence=text))
    assert target.level==level
    assert 'planning' in target.explanation


def report(quote,*,confidence='high',expired=False,scope='exact'):
    finding=NS(field='preparation_topics',value='Prepare Python application',quotes=[quote],
        confidence=confidence,conflict_group=None,scope=scope,source_ids=['source1'])
    category=NS(status='completed',expires_at=now()+timedelta(days=-1 if expired else 1),findings=[finding])
    return NS(intelligence=NS(categories={'interview_intelligence':category},expires_at=now()+timedelta(days=1)),
        sources=[NS(source_id='source1',url='https://employer.example/skills')])


def test_cited_research_can_raise_but_never_lower_the_career_target():
    target=target_for(skill(evidence='Familiar with Python'),report('Advanced Python is assessed.'))
    assert target.level==9 and target.basis=='research'
    assert target.source_urls==['https://employer.example/skills']
    assert target_for(skill(evidence='Expert Python'),report('Familiar with Python')).level==10


@pytest.mark.parametrize('research',[
    report('Advanced Python',expired=True),report('Advanced Python',confidence='low'),
    report('Advanced JavaScript'),report('Advanced React programming')])
def test_expired_weak_or_unrelated_research_does_not_raise_the_target(research):
    target=target_for(skill(evidence='Familiar with Python'),research)
    assert target.level==8 and target.basis=='job_description'


def test_current_goal_enrichment_keeps_saved_goal_and_source_provenance_intact():
    from app.schemas.jd import JDExtraction
    goal=JDExtraction(role='Engineer',field=None,company=None,skills=[skill(evidence='Python')])
    current=calibrated_goal(goal,report('Advanced Python'))
    assert current.skills[0].competence_target.level==9
    assert goal.skills[0].competence_target is None
    assert current.skills[0].evidence==goal.skills[0].evidence

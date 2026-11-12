from types import SimpleNamespace as NS
import pytest
from app.domain import planning_estimate
from app.competence import evidence_level,goal_score


def facts(*fields):
    return [{'field':field,'status':'supported','value':'Successful delivery.'} for field in fields]


@pytest.mark.parametrize('record,level',[
    ({'source_kind':'project','attribution':'unknown'},3),
    ({'source_kind':'project','attribution':'personal','support_uncertain':True},3),
    ({'attribution':'personal','assistance':'assisted'},3),
    ({'attribution':'personal','assistance':'independent'},4),
    ({'attribution':'personal','assistance':'independent','review_facts':facts('outcome')},5),
    ({'attribution':'personal','assistance':'independent','review_facts':facts('outcome','complexity','problem_solving')},7),
    ({'attribution':'personal','assistance':'independent','experience_months':30,'review_facts':facts('outcome','complexity','problem_solving','frequency','recency')},9),
    ({'source_kind':'project','attribution':'team'},None),
    ({'source_kind':'project','attribution':'denied'},None),
    ({'attribution':'personal','support_uncertain':True},None),
])
def test_both_scoring_paths_obey_the_evidence_ceiling(record,level):
    assert evidence_level([record],10)==level
    outcome=NS(mapping_method='canonical',components=[NS(evidence_refs=['e1'])],demonstrated_level=10)
    result=planning_estimate({'kind':'job_skill','priority':'required','competence_target':{'level':8}},outcome,{'e1':record})
    assert result['demonstrated_score']==level and result['required_score']==8
    assert result['competence_score']==(goal_score(level,8) if level is not None else None)
    assert result['scoring_rubric_version']=='evidence-role-v2'
    assert (result['score_status']=='estimated')==(level is not None)


def test_self_ratings_do_not_inflate_or_override_evidence():
    record={'attribution':'personal','assistance':'independent','review_facts':facts('outcome')}
    for rating in ('1','10'):
        record['review_facts']=facts('outcome')+[{'field':'self_rating','status':'supported','value':rating}]
        assert evidence_level([record],10)==5


def test_failed_outcomes_and_conflicts_do_not_prove_success():
    record={'attribution':'personal','assistance':'independent','review_facts':[{'field':'outcome','status':'supported','value':'The deployment failed.'}]}
    assert evidence_level([record],10)==3
    record['review_facts']=[{'field':'assistance','status':'conflicting','value':'Unclear help.'}]
    assert evidence_level([record],10)==None


def test_only_reaching_the_role_target_scores_ten():
    assert goal_score(5,8)==6.2
    assert goal_score(3,8)==3.7
    assert goal_score(9,10)==9
    assert goal_score(8,8)==10
    assert goal_score(9,8)==10


def test_explicit_low_replication_confidence_limits_the_current_estimate():
    record={'attribution':'personal','assistance':'independent','review_facts':facts('outcome')+
        [{'field':'replication_confidence','status':'supported','value':'I am unsure and need help to repeat it.'}]}
    assert evidence_level([record],10)==3

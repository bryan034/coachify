from types import SimpleNamespace as NS
import pytest
from app.domain import planning_estimate

@pytest.mark.parametrize('evidence,required,expected',[('guided_application','intermediate',5),('independent_application','advanced',7),('complex_application','beginner',10),('independent_application','intermediate',10),('guided_application','expert',None),(None,'advanced',None)])
def test_estimate_requires_explicit_supported_levels(evidence,required,expected):
    outcome=NS(mapping_method='canonical',components=[NS(evidence_refs=['e1'])])
    result=planning_estimate({'priority':'required','required_proficiency':required},outcome,{'e1':{'attribution':'personal','application_level':evidence,'reviewed':True}})
    assert result['competence_score']==expected
    assert result['relevance']=='high'
    assert result['required_score']=={'beginner':3,'intermediate':7,'advanced':10}.get(required)
    assert result['scoring_rubric_version']=='application-ratio-v1'
    assert (result['score_status']=='estimated')==(expected is not None)

@pytest.mark.parametrize('attribution,uncertain',[('team',False),('denied',False),('personal',True)])
def test_team_or_uncertain_evidence_never_produces_a_score(attribution,uncertain):
    output=NS(mapping_method='semantic',components=[NS(evidence_refs=['e1'])])
    result=planning_estimate({'priority':'preferred','required_proficiency':'intermediate'},output,{'e1':{'attribution':attribution,'support_uncertain':uncertain,'application_level':'complex_application'}})
    assert result['competence_score'] is None

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.api.v1.assessment_input import assessment_input
from app.schemas.analysis import CareerGoal,InterviewResearch
from app.repositories.goals import GoalError
class Goals:
    def __init__(self,goal,change=None):self.goal=goal;self.calls=0;self.change=change
    def current(self,owner):
        self.calls+=1
        if self.calls>1 and self.change=='selection':return {'selection_version':2,'goal':None}
        if self.calls>1 and self.change=='version':return {'selection_version':1,'goal':self.goal.model_copy(update={'version':2})}
        return {'selection_version':1,'goal':self.goal}
class Research:
    def __init__(self,record):self.record=record;self.calls=[]
    def read(self,owner,goal_id,**options):self.calls.append((owner,goal_id,options));return self.record

def request(goals,research):return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(goal_store=goals,research_store=research)))
def test_full_goal_and_owner_linked_research_do_not_require_every_mapping(documents):
    data=deepcopy(documents['goal']);data['readiness']='pending';data['skills'][0].update(name='Synthetic unmapped skill',skill_id=None)
    goal=CareerGoal.model_validate(data);research=Research(InterviewResearch.model_validate(documents['research']))
    value=asyncio.run(assessment_input(request(Goals(goal),research),goal.user_id))
    assert value['ready'] and value['goal']['_id']==goal.id
    assert value['goal']['skills'][0]['canonical_skill_id'] is None and value['goal']['skills'][0]['skill_id'] is None
    assert value['registry_version']=='skills-v2' and value['research']['_id']==research.record.id
    assert research.calls==[(goal.user_id,goal.id,{'current':True,'goal_version':goal.version})]
@pytest.mark.parametrize('change',['selection','version'])
def test_changes_during_assembly_are_rejected(documents,change):
    goal=CareerGoal.model_validate(documents['goal'])
    with pytest.raises(GoalError):asyncio.run(assessment_input(request(Goals(goal,change),Research(None)),goal.user_id))
def test_missing_goal_does_not_read_research():
    research=Research(None);value=asyncio.run(assessment_input(request(Goals(None),research),'synthetic-owner'))
    assert value['ready'] is False and value['goal'] is None and not research.calls

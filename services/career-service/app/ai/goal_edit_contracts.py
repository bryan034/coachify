"""Small typed change commands; Python keeps untouched fields and provenance."""
from typing import Literal,Annotated
from pydantic import Field,StrictInt,StringConstraints,model_validator
from app.schemas.analysis import Contract,Evidence

EditField=Literal['role','field','employment_type','company','location','seniority_level','job_url','summary',
    'name','category','priority','required_proficiency','required_experience_months','context',
    'description','minimum_months','maximum_months','completion_status','group_id','group_operator','text']

class GoalChange(Contract):
    collection:Literal['goal','skills','conditions','responsibilities']
    action:Literal['set','add','remove','clear']
    reference:str|None=Field(default=None,max_length=32)
    field:EditField|None=None
    value:Annotated[str,StringConstraints(max_length=600)]|StrictInt|None=None

class GoalEditDecision(Contract):
    status:Literal['clarify','ready','cancel','off_topic']
    reply:Evidence
    intent:Evidence
    changes:list[GoalChange]=Field(default_factory=list,max_length=80)
    acknowledge_context:bool=False

    @model_validator(mode='after')
    def action(self):
        if self.status=='ready' and not self.changes and not self.acknowledge_context:
            raise ValueError('A ready edit must contain an explicit change.')
        if self.status in ('cancel','off_topic') and (self.changes or self.acknowledge_context):
            raise ValueError('Cancelled or unrelated messages cannot change the goal.')
        return self

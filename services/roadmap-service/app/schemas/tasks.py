"""Editable roadmap tasks; generated sessions remain available as a compatibility view."""
from datetime import date
from typing import Annotated, Literal
from pydantic import ConfigDict, Field, StringConstraints, model_serializer, model_validator
from .base import Contract, Mutation, Text
Clock=Annotated[str,StringConstraints(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
Key=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=80)]
Title=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]

class TaskSlot(Contract):
    date:date
    start_time:Clock
    duration_minutes:int=Field(strict=True,ge=1,le=480)
    @model_validator(mode='after')
    def end_on_same_day(self):
        hour,minute=map(int,self.start_time.split(':'))
        if hour*60+minute+self.duration_minutes>1440:raise ValueError('A scheduled segment must end by midnight.')
        return self

class TaskDefinition(Contract):
    title:Title
    instructions:Text
    completion_outcome:Text
    estimated_minutes:int=Field(strict=True,ge=1,le=60000)
    requirement_refs:list[Key]=Field(default_factory=list,max_length=30)
    prerequisites:list[Key]=Field(default_factory=list,max_length=30)
    milestone_key:Key|None=None
    schedule:list[TaskSlot]=Field(default_factory=list,max_length=100)

class TaskChanges(Contract):
    title:Title|None=None
    instructions:Text|None=None
    completion_outcome:Text|None=None
    estimated_minutes:int|None=Field(default=None,strict=True,ge=1,le=60000)
    requirement_refs:list[Key]|None=Field(default=None,max_length=30)
    prerequisites:list[Key]|None=Field(default=None,max_length=30)
    milestone_key:Key|None=None
    schedule:list[TaskSlot]|None=Field(default=None,max_length=100)

class AddTask(Mutation):
    task:TaskDefinition
class EditTask(Mutation):
    task_id:Key
    changes:TaskChanges
class RemoveTask(Mutation):
    task_id:Key
    reason:str|None=Field(default=None,max_length=2000)
class ChangeTaskStatus(Mutation):
    task_id:Key
    status:Literal['not_started','in_progress','completed']
    evidence_note:str|None=Field(default=None,max_length=2000)
class ReconcileDecision(Contract):
    task_id:Key
    decision:Literal['keep','discard']
class ReconcileTasks(Mutation):
    candidate_id:Key
    decisions:list[ReconcileDecision]=Field(min_length=1,max_length=100)

class SavedTaskObject(Contract):
    """A typed view over saved data, retaining older and future extra fields."""
    model_config=ConfigDict(extra='allow',populate_by_name=True)

    @model_serializer(mode='wrap')
    def present_fields_only(self, handler):
        # Existing histories are sparse dictionaries. Do not add nulls/defaults
        # when reading them through a typed public response.
        serialized=handler(self)
        present=set(self.model_fields_set)
        for name in self.model_fields_set:
            field=type(self).model_fields.get(name)
            if field and field.alias:present.add(field.alias)
        return {key:value for key,value in serialized.items() if key in present}

class TaskPrevious(SavedTaskObject):
    title:str|None=None
    instructions:str|None=None
    completion_outcome:str|None=None
    estimated_minutes:int|None=None
    requirement_refs:list[str]|None=None
    prerequisites:list[str]|None=None
    milestone_key:str|None=None
    schedule:list[TaskSlot]|None=None

class TaskHistory(SavedTaskObject):
    at:str|None=None
    from_status:str|None=Field(default=None,alias='from')
    to:str|None=None
    event:str|None=None
    fields:list[str]|None=None
    previous:TaskPrevious|None=None
    reason:str|None=None
    evidence_note:str|None=None
    new_evidence_note:str|None=None
    completion_definition:str|None=None
    estimated_minutes_at_completion:int|None=None

class TaskRemoval(SavedTaskObject):
    at:str|None=None
    reason:str|None=None

class SourceAssignment(SavedTaskObject):
    id:str|None=None
    key:str|None=None
    milestone_key:str|None=None
    gap_id:str|None=None
    kind:str|None=None
    date:str|None=None
    start_time:str|None=None
    duration_minutes:int|None=None
    task:str|None=None
    completion_criterion:str|None=None
    status:str|None=None
    completed_at:str|None=None
    evidence_note:str|None=None
    history:list[TaskHistory]|None=None

class EditableTask(Contract):
    id:Key
    title:str
    instructions:Text
    completion_outcome:Text
    estimated_minutes:int=Field(strict=True,ge=1,le=60000)
    requirement_refs:list[str]=Field(default_factory=list)
    requirement_source_hash:str|None=None
    requirement_source_id:str|None=None
    prerequisites:list[str]=Field(default_factory=list)
    milestone_key:str|None=None
    schedule:list[TaskSlot]=Field(default_factory=list)
    status:Literal['not_started','in_progress','completed']
    completed_at:str|None=None
    evidence_note:str|None=None
    history:list[TaskHistory]=Field(default_factory=list)
    removed:bool=False
    definition_review_required:bool=False
    removal:TaskRemoval|None=None
    generated_key:str|None=None
    origin:Literal['generated','user']
    overrides:list[str]=Field(default_factory=list)
    source_assignment:SourceAssignment|None=None

class ReadinessReason(Contract):
    code:str
    message:str
class TaskReadiness(Contract):
    actionable:bool
    reasons:list[ReadinessReason]
class TaskView(EditableTask):
    readiness:TaskReadiness
    unscheduled_minutes:int
    stale_requirement_refs:list[str]
class TaskWarning(Contract):
    code:str
    message:str
    task_ids:list[str]
class TaskList(Contract):
    version:int
    plan_id:str
    stale:bool
    source_unavailable:bool
    freshness:Literal['current','stale','not_ready','unavailable']
    tasks:list[TaskView]
    warnings:list[TaskWarning]
class RevisionReview(Contract):
    task_id:str
    removed_task_ids:list[str]=Field(default_factory=list)
    related_task_ids:list[str]=Field(default_factory=list)

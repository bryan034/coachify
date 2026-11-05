"""Editable roadmap tasks; generated sessions remain available as a compatibility view."""
from datetime import date
from typing import Annotated, Literal
from pydantic import Field, StringConstraints, model_validator
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
    status:Literal['in_progress']
    evidence_note:str|None=Field(default=None,max_length=2000)
class ReconcileDecision(Contract):
    task_id:Key
    decision:Literal['keep','discard']
class ReconcileTasks(Mutation):
    candidate_id:Key
    decisions:list[ReconcileDecision]=Field(min_length=1,max_length=100)

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
    history:list[dict]=Field(default_factory=list)
    removed:bool=False
    definition_review_required:bool=False
    removal:dict|None=None
    generated_key:str|None=None
    origin:Literal['generated','user']
    overrides:list[str]=Field(default_factory=list)
    source_assignment:dict|None=None

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

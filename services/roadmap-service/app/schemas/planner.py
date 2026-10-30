from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=4000)]
class Contract(BaseModel): model_config=ConfigDict(extra='forbid')
class Mutation(Contract):
    expected_version:int=Field(strict=True,ge=0)
    mutation_id:UUID
class Message(Mutation):
    message:Text
    allow_partial_assessment:bool=False
class DayBudget(Contract):
    day:int=Field(strict=True,ge=0,le=6)
    minutes:int=Field(strict=True,ge=0,le=1440)
class ReducedPeriod(Contract):
    id:str|None=Field(default=None,max_length=100)
    start_date:date
    end_date:date
    weekly_hours:float=Field(strict=True,ge=0,le=168,allow_inf_nan=False)
    @model_validator(mode='after')
    def ordered(self):
        if self.end_date<self.start_date:raise ValueError('Availability period ends before it starts.')
        return self
class Preferences(Contract):
    start_date:date|None=None
    target_date:date|None=None
    horizon_weeks:int|None=Field(default=None,strict=True,ge=1,le=52)
    weekly_minutes:int|None=Field(default=None,strict=True,ge=0,le=10080)
    days:list[DayBudget]=Field(default_factory=list,max_length=7)
    max_session_minutes:int=Field(default=60,strict=True,ge=1,le=1440)
    time_zone:str='Asia/Singapore'
    learning_preferences:str=Field(default='',max_length=2000)
    reduced_periods:list[ReducedPeriod]=Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def coherent(self):
        try:ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Choose a valid planning time zone.') from None
        if len({d.day for d in self.days})!=len(self.days):raise ValueError('Choose each weekday once.')
        if self.target_date and self.start_date and self.target_date<=self.start_date:raise ValueError('Choose a preparation target after the start date.')
        if self.weekly_minutes is not None and sum(d.minutes for d in self.days)>self.weekly_minutes:raise ValueError('Daily budgets exceed the weekly budget.')
        if self.target_date and self.start_date and (self.target_date-self.start_date).days>366:raise ValueError('Plan at most one year at a time.')
        periods=sorted(self.reduced_periods,key=lambda p:p.start_date)
        if any(a.end_date>=b.start_date for a,b in zip(periods,periods[1:])):raise ValueError('Reduced-availability periods overlap.')
        return self
class PreferencesPatch(Contract):
    start_date:date|None=None
    target_date:date|None=None
    clear_target:bool=False
    horizon_weeks:int|None=Field(default=None,strict=True,ge=1,le=52)
    weekly_minutes:int|None=Field(default=None,strict=True,ge=0,le=10080)
    days:list[DayBudget]|None=Field(default=None,max_length=7)
    max_session_minutes:int|None=Field(default=None,strict=True,ge=1,le=1440)
    learning_preferences:str|None=Field(default=None,max_length=2000)
class TaskDefinition(Contract):
    id:str=Field(min_length=1,max_length=80)
    title:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
    instructions:Text
    completion_outcome:Text
    estimated_minutes:int=Field(strict=True,ge=1,le=60000)
    rationale:Text
    requirement_refs:list[str]=Field(default_factory=list,max_length=30)
    prerequisites:list[str]=Field(default_factory=list,max_length=30)
    milestone:str=Field(default='',max_length=160)
    splittable:bool=True
class Removal(Contract):
    task_id:str=Field(min_length=1,max_length=80)
    reason:Text
    quote:Text
class Exclusion(Contract):
    requirement_ref:str=Field(min_length=1,max_length=160)
    reason:Text
    quote:Text
class AdviserReply(Contract):
    reply:Text
    preferences:PreferencesPatch=Field(default_factory=PreferencesPatch)
    task_changes:list[TaskDefinition]=Field(default_factory=list,max_length=40)
    remove_tasks:list[Removal]=Field(default_factory=list,max_length=40)
    scope_exclusions:list[Exclusion]=Field(default_factory=list,max_length=40)
    scope_inclusions:list[Exclusion]=Field(default_factory=list,max_length=40)
class EditTask(Mutation):
    task:TaskDefinition
    base_definition:TaskDefinition|None=None
class TaskStatus(Mutation):
    task_id:str=Field(min_length=1,max_length=80)
    status:Literal['not_started','in_progress','completed']
class SavePreferences(Mutation):
    preferences:Preferences
class RemoveTask(Mutation):
    task_id:str=Field(min_length=1,max_length=80)

class Task(TaskDefinition):
    model_config=ConfigDict(extra='allow')
    status:Literal['not_started','in_progress','completed']
    removed:bool=False
    definition_review_required:bool=False
    history:list[dict]=Field(default_factory=list)
class Schedule(Contract):
    status:Literal['needs_preferences','feasible','partial','no_work','review_needed']
    issues:list[str]
    allocations:list[dict]
    remainders:dict[str,int]
    milestones:list[dict]
    daily_capacity:dict[str,int]=Field(default_factory=dict)
    remaining_minutes:int|None=None
    total_estimated_minutes:int|None=None
    available_minutes:int|None=None
    allocated_minutes:int|None=None
    start_date:str|None=None
    cutoff_date:str|None=None
class Plan(Contract):
    model_config=ConfigDict(extra='allow')
    id:str
    assessment_id:str
    assessment_hash:str
    assessment:dict
    tasks:list[Task]
    preferences:Preferences
    schedule:Schedule
    exclusions:list[dict]
class Workspace(Contract):
    version:int
    messages:list[dict]
    draft:Plan|None
    active:Plan|None
    assessment:dict|None
    operation:dict|None
    context:dict
    stale:bool
    retry_request:dict|None=None

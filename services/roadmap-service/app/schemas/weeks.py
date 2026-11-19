"""Request and model-output contracts for a separately reviewed week."""
from datetime import date
from typing import Annotated, Literal
from pydantic import Field, StringConstraints
from .base import Contract, Mutation, Text
from .roadmap import Key, WeekFeedback
from .tasks import TaskTitle

class GenerateWeek(Mutation):
    week_start:date
    revision:bool=False
    feedback:WeekFeedback|None=None

class CarryChoice(Contract):
    task_id:Key
    action:Literal['carry','split','defer','drop']

class ReviewCarryover(Mutation):
    decisions:list[CarryChoice]=Field(min_length=1,max_length=60)

class WeekTask(Contract):
    """What to do and for how long. The service chooses the dates and times."""
    key:Key
    milestone_key:Key
    title:TaskTitle
    description:Text=Field(description='Explain the task with numbered steps, practical guidance for completing each step, and a final check of the result.')
    instructions:Text
    completion_outcome:Text
    duration_minutes:int=Field(strict=True,ge=5,le=1200)
    kind:Literal['study','diagnostic']='study'
    gap_id:Key|None=None


class CarryDecision(Contract):
    task_id:Key
    action:Literal['carry','split','defer','drop']
    minutes:int|None=Field(default=None,strict=True,ge=5,le=1200,description='For split: the minutes to do this week.')
    reason:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=400)]

class ObjectiveChange(Contract):
    week_start:date
    objective:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=400)]
    expected_outcome:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=400)]
    estimated_minutes:int=Field(strict=True,ge=0,le=10080)
    milestone_key:Key
    gap_ids:list[Key]=Field(default_factory=list,max_length=8)
    reason:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=400)]

class WeekDraft(Contract):
    summary:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=1000)]
    tasks:list[WeekTask]=Field(default_factory=list,max_length=40)
    carryover:list[CarryDecision]=Field(default_factory=list,max_length=60)
    objective_changes:list[ObjectiveChange]=Field(default_factory=list,max_length=52)

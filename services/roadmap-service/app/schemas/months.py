"""Input and model-output contracts for a separately reviewed month."""
from datetime import date
from typing import Annotated, Literal
from pydantic import Field, StringConstraints, field_validator
from .base import Contract, Mutation, Text
from .roadmap import Clock, Key

class GenerateMonth(Mutation):
    month:Annotated[str,StringConstraints(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')]
    revision:bool=False

class AcceptMonth(Mutation):
    month_id:Key

class MonthTask(Contract):
    key:Key
    milestone_key:Key
    title:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
    instructions:Text
    completion_outcome:Text
    date:date
    start_time:Clock
    duration_minutes:int=Field(strict=True,ge=1,le=480)
    kind:Literal['study','diagnostic']='study'
    gap_id:Key|None=None

    @field_validator('title')
    @classmethod
    def title_words(cls,value):
        if len(value.split())>19:raise ValueError('Use at most 19 words in a task title.')
        return value

class MonthDraft(Contract):
    tasks:list[MonthTask]=Field(default_factory=list,max_length=100)

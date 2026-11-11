"""AI-generated fills for interview-preparation slots that public research left empty.

Every item here is a model prediction, never a sourced fact; the frontend labels it as such."""
from datetime import datetime
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,StringConstraints


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')


SuggestionText=Annotated[str,StringConstraints(strip_whitespace=True,min_length=3,max_length=200)]
# Round slots plus the process-wide headline facts; every one is filled when sources leave it empty.
GapField=Literal['interview_questions','preparation_topics','recruitment_stages','application_timeline','difficulty']


class Gap(Model):
    # None means the whole process: sources describe no rounds, or nothing at all.
    round_number:int|None=Field(default=None,ge=1,le=10,strict=True)
    round_name:str|None=Field(default=None,max_length=80)
    field:GapField


class Suggestion(Model):
    round_number:int|None=Field(default=None,ge=1,le=10,strict=True)
    field:GapField
    value:SuggestionText


class InterviewSuggestions(Model):
    goal_id:str
    goal_version:int
    # The research revision the gaps were computed from; None when no research exists yet.
    research_id:str|None=None
    generated_at:datetime
    gaps:list[Gap]=Field(default_factory=list,max_length=24)
    items:list[Suggestion]=Field(default_factory=list,max_length=120)


class SuggestCommand(Model):
    expected_version:int=Field(strict=True,ge=1)
    refresh:bool=False

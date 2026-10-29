"""Explicit acknowledgement of the current canonical goal for CV clarification."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.analysis import DomainId


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ConfirmCvGoal(Strict):
    expected_goal_id: DomainId
    expected_goal_version: int = Field(ge=1, strict=True)
    expected_selection_version: int = Field(ge=0, strict=True)
    mutation_id: str

    @field_validator('mutation_id')
    @classmethod
    def valid_key(cls,value): return str(UUID(value))


class CvTargetCondition(Strict):
    id: str
    kind: Literal['qualification', 'date', 'requirement']
    label: str
    description: str
    item_kinds: list[Literal['education', 'experience', 'project', 'skill']]
    match_terms: list[str]
    evidence: str | None = None
    origin: Literal['user_reviewed_jd', 'user_guidance']
    source_requirement_id: str
    source_category: str
    source_priority: str
    source_origin: str
    group_id: str | None = None
    group_operator: Literal['all', 'any'] = 'all'


class CvConfirmedContext(Strict):
    id: str
    version: int = Field(ge=1)
    type: Literal['specific_job', 'career_exploration']
    confirmed: Literal[True] = True
    skill_ids: list[str] = Field(max_length=200)
    selection_version: int = Field(ge=1)
    role: str
    field: str
    conditions: list[CvTargetCondition] = Field(default_factory=list, max_length=100)


class CvConfirmationView(Strict):
    goal_id: str | None = None
    goal_version: int | None = None
    selection_version: int = Field(ge=0)
    confirmed: bool = False
    context: CvConfirmedContext | None = None
    reason: str | None = None

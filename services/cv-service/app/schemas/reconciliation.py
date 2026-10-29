from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.cv import CvItem, Clarification, ExtractionMetadata


class ResolutionChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(min_length=1, max_length=100)
    target_item_id: str | None = Field(default=None, min_length=1, max_length=100)


class ReconcileMutation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=0, strict=True)
    mutation_id: UUID
    candidate_id: str = Field(min_length=1, max_length=100)
    action: Literal['keep_previous', 'accept_candidate']
    choices: list[ResolutionChoice] = Field(default_factory=list, max_length=160)

    @model_validator(mode='after')
    def unique_choices(self):
        ids = [choice.item_id for choice in self.choices]
        targets = [choice.target_item_id for choice in self.choices if choice.target_item_id]
        if len(set(ids)) != len(ids) or len(set(targets)) != len(targets):
            raise ValueError('Choose each old and new source at most once.')
        if self.action == 'keep_previous' and self.choices:
            raise ValueError('Keeping the previous result needs no transfer choices.')
        return self


class ReconciliationView(BaseModel):
    cv_id: str
    cv_version: int
    candidate_id: str
    source_cv_id: str
    previous_items: list[CvItem]
    candidate_items: list[CvItem]
    affected_item_ids: list[str]
    previous_answers: list[Clarification]
    extraction: ExtractionMetadata
    notices: list[str]


class CompareSourceMutation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=0, strict=True)
    mutation_id: UUID
    source_cv_id: str = Field(min_length=1, max_length=100)
    source_version: int = Field(ge=0, strict=True)

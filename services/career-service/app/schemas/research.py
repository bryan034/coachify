"""J12/J13 public synthesis input and private request contracts."""
from typing import Literal
from pydantic import Field
from app.schemas.analysis import Contract, Text, Evidence, Version, ResearchSource, BraveAnswer, InterviewProcess

class ResearchRequest(Contract):
    expected_version: Version
    expected_selection_version: int = Field(strict=True,ge=0)
    refresh: bool = False

class ResearchBatch(Contract):
    sources: list[ResearchSource] = Field(default_factory=list,max_length=6)
    summaries: list[BraveAnswer] = Field(default_factory=list,max_length=2)

class Topic(Contract):
    evidence_origin: Literal['source_excerpt','brave_summary'] = 'source_excerpt'
    summary_id: Text | None = None
    name: Text
    category: Text
    interview_stage: Text | None = None
    assessment_type: Text | None = None
    difficulty: Literal['introductory','intermediate','advanced','unknown'] = 'unknown'
    question_patterns: list[Evidence] = Field(default_factory=list,max_length=8)
    source_ids: list[Text] = Field(min_length=1,max_length=3)
    quotes: list[Evidence] = Field(min_length=1,max_length=3)

class SourcedTopics(Contract):
    process: InterviewProcess=Field(default_factory=InterviewProcess)
    topics: list[Topic] = Field(max_length=20)

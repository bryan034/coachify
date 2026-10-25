"""Transient JD review contracts; candidates are not canonical analysis skills."""
from typing import Literal
from pydantic import Field, field_validator
from app.schemas.analysis import Contract, Text, Evidence, SourceUrl, Proficiency, Count, Generation

class ReviewSkill(Contract):
    name: Text
    category: Text
    priority: Literal['required','preferred','suggested']
    required_proficiency: Proficiency | None = None
    required_experience_months: Count | None = None
    context: Evidence | None = None
    evidence: Evidence | None = None
    origin: Literal['employer','generated_guidance','user_declaration']

class JDExtraction(Contract):
    role: Text | None
    field: Text | None
    company: Text | None
    skills: list[ReviewSkill] = Field(max_length=60)

class JDExtractionResult(Contract):
    extraction: JDExtraction
    generation: Generation

class JDReply(Contract):
    reply: Evidence
    proposed_skills: list[ReviewSkill] | None

class JDSource(Contract):
    text: str = Field(min_length=1,max_length=20000,repr=False)
    source_url: SourceUrl | None = None

    @field_validator('text')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():raise ValueError('Provide a job description.')
        return value

class ReviewMessage(Contract):
    role: Literal['user','assistant']
    content: Evidence

class JDMessage(JDSource):
    message: Evidence
    skills: list[ReviewSkill] = Field(max_length=60)
    # Prior transcript is context, never evidence of an employer requirement.
    conversation: list[ReviewMessage] = Field(default_factory=list,max_length=12,repr=False)

"""Transient JD review contracts; candidates are not canonical analysis skills."""
from typing import Annotated, Literal
from pydantic import Field, StringConstraints, field_validator, model_validator
from app.schemas.analysis import Contract, Text, Evidence, SourceUrl, Proficiency, Count, Generation, NonSkillRequirement, Document, AccountId, DomainId, SkillId, Version, Priority

ChatText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

class ReviewSkill(Contract):
    item_id: Text | None = None
    skill_id: SkillId | None = None
    group_id: Text | None = None
    group_operator: Literal['all', 'any'] = 'all'
    correction: Literal['extracted', 'user'] = 'extracted'
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)
    name: Text
    category: Text
    priority: Priority
    priority_evidence: Evidence | None = None
    priority_origin: Literal['employer','generated_guidance','user_declaration'] | None = None
    required_proficiency: Proficiency | None = None
    required_experience_months: Count | None = None
    context: Evidence | None = None
    evidence: Evidence | None = None
    origin: Literal['employer','generated_guidance','user_declaration']

class JDExtraction(Contract):
    role: Text | None
    field: Text | None
    company: Text | None
    location: Text | None = None
    seniority_level: Text | None = None
    # Set from the supplied source URL by the API, never invented by the model.
    job_url: SourceUrl | None = None
    summary: Evidence | None = None
    responsibilities: list[Evidence] = Field(default_factory=list, max_length=20)
    non_skill_requirements: list[NonSkillRequirement] = Field(default_factory=list, max_length=30)
    skills: list[ReviewSkill] = Field(max_length=60)

class JDExtractionResult(Contract):
    review_id: DomainId
    version: Version
    target_type: Literal['specific_job', 'career_exploration']
    extraction: JDExtraction
    baseline: JDExtraction
    metadata_origins: dict[str, Literal['extracted', 'user']]
    requirements_need_review: bool
    is_confirmed: bool
    generation: Generation | None

class JDReply(Contract):
    reply: ChatText
    proposed_skills: list[ReviewSkill] | None = Field(max_length=60)

class JDSource(Contract):
    text: str = Field(min_length=1,max_length=8000,repr=False)
    source_url: SourceUrl | None = None
    source_kind: Literal['text', 'url', 'document'] = 'text'

    @field_validator('text')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():raise ValueError('Provide a job description.')
        return value

class ReviewMessage(Contract):
    role: Literal['user','assistant']
    content: ChatText

class JDMessage(Contract):
    review_id: DomainId
    expected_version: Version
    message: Evidence
    conversation: list[ReviewMessage] = Field(default_factory=list, max_length=12, repr=False)


class RequirementReview(Document):
    record_type: Literal['requirement_review'] = 'requirement_review'
    user_id: AccountId
    target_type: Literal['specific_job', 'career_exploration'] = 'specific_job'
    source_kind: Literal['text', 'url', 'document', 'career_exploration'] = 'text'
    content: JDExtraction
    baseline: JDExtraction
    generation: Generation | None
    metadata_origins: dict[str, Literal['extracted', 'user']] = Field(default_factory=dict, max_length=6)
    baseline_origins: dict[str, Literal['extracted', 'user']] = Field(default_factory=dict, max_length=6)
    requirements_need_review: bool = False
    base_goal_id: DomainId | None = None


class SaveReview(Contract):
    expected_version: Version
    content: JDExtraction | None = None
    reset: Literal['metadata', 'all'] | None = None
    acknowledge_context: bool = False

    @model_validator(mode='after')
    def one_action(self):
        if (self.content is None) == (self.reset is None):
            raise ValueError('Supply edited content or a reset action.')
        return self

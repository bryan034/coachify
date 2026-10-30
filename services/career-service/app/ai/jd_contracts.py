from elo_shared.dates import JobDate
"""Small provider contracts, independent of persistence/API document metadata."""
from app.schemas.analysis import EmploymentType

from typing import Literal
from pydantic import Field
from app.schemas.analysis import Contract, Text, Evidence, Proficiency, Count, Priority
from app.schemas.jd import ChatText, JDExtraction, ReviewSkill


class ExtractedSkill(Contract):
    name: Text
    category: Text
    priority: Priority
    priority_evidence: Evidence | None = None
    origin: Literal['employer', 'generated_guidance', 'user_declaration']
    group_id: Text | None = None
    group_operator: Literal['all', 'any'] = 'all'
    required_proficiency: Proficiency | None = None
    required_experience_months: Count | None = None
    context: Evidence | None = None
    evidence: Evidence | None = None


class ExtractedCondition(Contract):
    category: Literal['qualification', 'experience', 'eligibility', 'location', 'work_condition', 'other']
    description: Evidence
    priority: Priority
    priority_evidence: Evidence | None = None
    evidence: Evidence
    group_id: Text | None = None
    group_operator: Literal['all', 'any'] = 'all'
    origin: Literal['employer', 'generated_guidance', 'user_declaration'] = 'employer'
    minimum_months: Count | None = None
    maximum_months: Count | None = None
    completion_status: Literal['completed', 'in_progress', 'unspecified'] = 'unspecified'


class ExtractedJD(Contract):
    job_dates: list[JobDate] = Field(default_factory=list, max_length=8)
    role: Text | None
    field: Text | None
    employment_type: EmploymentType = 'unknown'
    company: Text | None
    location: Text | None = None
    seniority_level: Text | None = None
    summary: Evidence | None = None
    responsibilities: list[Evidence] = Field(default_factory=list, max_length=20)
    non_skill_requirements: list[ExtractedCondition] = Field(default_factory=list, max_length=30)
    skills: list[ExtractedSkill] = Field(max_length=60)

    def to_domain(self):
        data = self.model_dump()
        # Transient condition keys are allocated here; review preparation assigns
        # persistent identities. Group labels continue to span both item types.
        for index, condition in enumerate(data['non_skill_requirements']):
            condition['requirement_id'] = f'condition-{index + 1}'
        return JDExtraction.model_validate(data)


class JDAnswer(Contract):
    reply: ChatText
    edit_requested: bool = Field(default=False, strict=True)


class SkillEdits(Contract):
    keep: list[Text] = Field(max_length=60)
    add: list[ExtractedSkill] = Field(max_length=60)


def apply_edits(edits: SkillEdits, existing: list[ReviewSkill]):
    if len(edits.keep) + len(edits.add) > 60:
        raise ValueError('Too many proposed skills.')
    lookup = {str(index): skill for index, skill in enumerate(existing)}
    if len(set(edits.keep)) != len(edits.keep) or any(key not in lookup for key in edits.keep):
        raise ValueError('Invalid retained skill reference.')
    if any(skill.origin == 'employer' for skill in edits.add):
        raise ValueError('New chat skills cannot become employer facts.')
    return [*(lookup[key].model_copy(deep=True) for key in edits.keep),
            *(ReviewSkill.model_validate(skill.model_dump()) for skill in edits.add)]


class WorkspaceAnswer(Contract):
    reply: ChatText
    edits: SkillEdits | None = None

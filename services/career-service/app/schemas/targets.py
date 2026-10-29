"""Strict structured target contracts. The reviewed source is transient input only."""
import unicodedata
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TargetType = Literal['specific_job', 'career_exploration']
Origin = Literal['user_reviewed_jd', 'user_guidance']
Name = Annotated[str, Field(min_length=1, max_length=200)]
Short = Annotated[str, Field(min_length=1, max_length=120)]
Excerpt = Annotated[str, Field(min_length=1, max_length=500)]
Url = Annotated[str, Field(min_length=1, max_length=2048)]


def canonical_skill_id(name):
    return 'skill:' + ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()


def normalized_text(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('*')
    @classmethod
    def usable_strings(cls, value):
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and (not item.strip() or any(unicodedata.category(c) in {'Cc', 'Cs'} and c not in '\n\r\t' for c in item)):
                raise ValueError('Use readable, non-empty text.')
        return value


class Mutation(StrictModel):
    mutation_id: str

    @field_validator('mutation_id')
    @classmethod
    def valid_key(cls, value):
        return str(UUID(value))


class SkillInput(StrictModel):
    name: Name
    category: Short = 'unspecified'
    priority: Short = 'unspecified'
    required_proficiency: Short | None = None
    required_experience_months: Annotated[int, Field(ge=0, le=1200)] | None = None
    context: Excerpt | None = None
    evidence: Excerpt | None = None
    source_urls: list[Url] = Field(default_factory=list, max_length=5)

    @field_validator('source_urls')
    @classmethod
    def valid_urls(cls, values):
        for value in values: validate_url(value)
        return values


class ConditionInput(StrictModel):
    kind: Literal['qualification', 'date']
    label: Name
    description: Excerpt
    item_kinds: list[Literal['education', 'experience', 'project', 'skill']] = Field(min_length=1, max_length=4)
    match_terms: list[Annotated[str, Field(min_length=2, max_length=120)]] = Field(min_length=1, max_length=5)
    evidence: Excerpt | None = None

    @model_validator(mode='after')
    def precise_subjects(self):
        terms = [normalized_text(term) for term in self.match_terms]
        if len(set(self.item_kinds)) != len(self.item_kinds) or len(set(terms)) != len(terms):
            raise ValueError('Use distinct item types and relevant subject phrases.')
        if any(len(term) < 2 for term in terms):
            raise ValueError('Use a specific subject phrase of at least two characters.')
        content = normalized_text(' '.join([self.label, self.description, self.evidence or '']))
        if any(term not in content for term in terms):
            raise ValueError('Each relevant subject phrase must appear in this condition.')
        return self


class TargetCondition(ConditionInput):
    id: str
    origin: Origin


class TargetCreate(Mutation):
    target_type: TargetType
    role: Name
    field: Name
    company: Name | None = None
    location: Name | None = None
    seniority_level: Name | None = None
    job_url: Url | None = None
    interests: list[Name] = Field(default_factory=list, max_length=20)
    preferences: list[Name] = Field(default_factory=list, max_length=20)
    skills: list[SkillInput] = Field(max_length=40)
    conditions: list[ConditionInput] = Field(default_factory=list, max_length=20)
    reviewed_source_text: Annotated[str, Field(min_length=1, max_length=20000)] | None = None

    @field_validator('job_url')
    @classmethod
    def valid_url(cls, value):
        if value is not None: validate_url(value)
        return value

    @model_validator(mode='after')
    def reviewed_requirements(self):
        ids = [canonical_skill_id(skill.name) for skill in self.skills]
        if len(set(ids)) != len(ids): raise ValueError('Each canonical skill may appear only once.')
        if self.target_type == 'specific_job' and any(not skill.evidence or not self.reviewed_source_text or skill.evidence not in self.reviewed_source_text for skill in self.skills):
            raise ValueError('Each job skill needs an exact excerpt from the reviewed job description.')
        identities = [(condition.kind, normalized_text(condition.label)) for condition in self.conditions]
        if len(set(identities)) != len(identities):
            raise ValueError('Each labelled condition may appear only once.')
        if self.target_type == 'specific_job':
            for condition in self.conditions:
                if not condition.evidence or not self.reviewed_source_text or condition.evidence not in self.reviewed_source_text:
                    raise ValueError('Each job condition needs an exact excerpt from the reviewed job description.')
                if any(normalized_text(term) not in normalized_text(condition.evidence) for term in condition.match_terms):
                    raise ValueError('Relevant job subject phrases must be supported by the cited excerpt.')
        if self.target_type == 'career_exploration' and self.reviewed_source_text is not None:
            raise ValueError('Personal exploration guidance does not use a job description.')
        return self


def validate_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value) or '\\' in value:
            raise ValueError
        _ = parsed.port
    except ValueError as exc:
        raise ValueError('Use an HTTP or HTTPS source URL without credentials.') from exc


class TargetSkill(SkillInput):
    skill_id: Annotated[str, Field(min_length=7, max_length=4000)]
    origin: Origin


class Target(StrictModel):
    id: str
    user_id: str
    target_type: TargetType
    role: Name
    field: Name
    company: Name | None
    location: Name | None
    seniority_level: Name | None
    job_url: Url | None
    interests: list[Name]
    preferences: list[Name]
    skills: list[TargetSkill]
    conditions: list[TargetCondition] = Field(default_factory=list, max_length=20)
    requirements_source: Origin
    generation_version: Literal['manual-v1']
    status: Literal['draft', 'confirmed']
    version: Annotated[int, Field(ge=1)]
    created_at: str
    updated_at: str
    confirmed_at: str | None


class ConfirmTarget(Mutation):
    expected_version: Annotated[int, Field(ge=1)]


class SelectTarget(Mutation):
    expected_version: Annotated[int, Field(ge=0)]
    career_target_id: str
    career_target_version: Annotated[int, Field(ge=1)]

    @field_validator('career_target_id')
    @classmethod
    def valid_identifier(cls, value): return str(UUID(value))


class Selection(StrictModel):
    career_target_id: str | None
    career_target_version: int | None
    version: Annotated[int, Field(ge=0)]


class Targets(StrictModel):
    targets: list[Target] = Field(max_length=20)
    selection: Selection
    next_cursor: Annotated[str, Field(max_length=512)] | None
    selected_target: Target | None


class ConfirmedContext(StrictModel):
    id: str
    version: Annotated[int, Field(ge=1)]
    type: TargetType
    confirmed: Literal[True]
    skill_ids: list[Annotated[str, Field(min_length=7, max_length=4000)]] = Field(max_length=40)
    conditions: list[TargetCondition] = Field(default_factory=list, max_length=20)
    selection_version: Annotated[int, Field(ge=1)]
    role: Name
    field: Name

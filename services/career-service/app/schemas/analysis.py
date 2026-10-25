"""SCRUM-310: bounded, application-owned MongoDB and AI contracts.

No raw JD field is accepted. Account IDs remain Profile UUIDs; domain IDs are
ObjectIds represented as hex strings at the API boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from bson import BSON, ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, field_validator, model_validator

SCHEMA_VERSION = 'analysis-v1'
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Evidence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
SkillId = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+$', max_length=120)]
Count = Annotated[int, Field(strict=True, ge=0, le=1200)]
Version = Annotated[int, Field(strict=True, ge=1)]
Proficiency = Literal['beginner', 'intermediate', 'advanced', 'expert']
Priority = Literal['required', 'preferred', 'suggested']


def object_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{24}', value):
        raise ValueError('Expected a lowercase ObjectId string.')
    return value


def account_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Expected the canonical Profile account UUID.')
    return value


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Expected a public source URL.')
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Expected an HTTP(S) source URL without credentials.')
    return value


DomainId = Annotated[str, BeforeValidator(object_id), StringConstraints(pattern=r'^[0-9a-f]{24}$')]
AccountId = Annotated[str, BeforeValidator(account_id), StringConstraints(pattern=r'^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$')]
SourceUrl = Annotated[str, BeforeValidator(public_url)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True, populate_by_name=True, revalidate_instances='always')

    @model_validator(mode='after')
    def document_bound(self):
        if len(self.model_dump_json(by_alias=True).encode()) > 512 * 1024:
            raise ValueError('Contract exceeds the 512 KiB document limit.')
        return self


class Generation(Contract):
    provider: Text
    model: Text
    prompt_version: Text
    schema_version: Literal['analysis-v1'] = SCHEMA_VERSION
    generated_at: datetime

    @field_validator('generated_at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Use a timezone-aware timestamp.')
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class CvSkill(Contract):
    skill_id: SkillId
    name: Text
    category: Text
    proficiency: Proficiency | None = None
    experience_months: Count | None = None
    context: Evidence | None = None
    evidence: Evidence
    evidence_type: Literal['cv', 'user_declaration']
    explicit: bool = Field(strict=True)
    # Original extraction and current contribution remain distinct. No proof required.
    original_evidence: Evidence | None = None


class TargetSkill(Contract):
    skill_id: SkillId
    name: Text
    category: Text
    priority: Priority
    required_proficiency: Proficiency | None = None
    required_experience_months: Count | None = None
    context: Evidence | None = None
    evidence: Evidence | None = None
    origin: Literal['employer', 'generated_guidance', 'user_declaration']
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def grounded_employer(self):
        if self.origin == 'employer' and (not self.evidence or self.priority == 'suggested'):
            raise ValueError('Employer requirements need evidence and stated priority.')
        return self


class NonSkillRequirement(Contract):
    requirement_id: Text
    category: Literal['qualification', 'eligibility', 'location', 'other']
    description: Evidence
    priority: Priority
    evidence: Evidence
    group_id: Text | None = None
    group_operator: Literal['all', 'any'] = 'all'


class ResearchSource(Contract):
    source_id: Text
    platform: Literal['employer', 'reddit', 'glassdoor', 'other']
    url: SourceUrl
    title: Text | None = None
    evidence: Evidence | None = None
    reported_date: date | None = None
    published_date: date | None = None
    role_match: Literal['exact', 'related', 'unknown'] = 'unknown'
    reliability: Literal['official', 'anecdotal', 'unverified'] = 'unverified'
    # Assigned by retrieval/deduplication, never by the model.
    report_group: Text

    @field_validator('reported_date', 'published_date')
    @classmethod
    def not_future(cls, value):
        if value and value > datetime.now(timezone.utc).date():
            raise ValueError('Source dates cannot be in the future.')
        return value


class InterviewSkill(Contract):
    skill_id: SkillId
    name: Text
    category: Text
    interview_stage: Text | None = None
    assessment_type: Text | None = None
    difficulty: Literal['introductory', 'intermediate', 'advanced', 'unknown'] = 'unknown'
    question_patterns: list[Evidence] = Field(default_factory=list, max_length=20)
    independent_report_count: Count
    source_ids: list[Text] = Field(min_length=1, max_length=50)


class GapResult(Contract):
    skill_id: SkillId
    name: Text
    gap_type: Literal['job_skill', 'interview_preparation']
    match_status: Literal['supported', 'partial', 'uncertain', 'confirmed_shortfall']
    importance: Priority | None = None
    cv_proficiency: Proficiency | None = None
    required_proficiency: Proficiency | None = None
    explanation: Note
    recommendation: Note | None = None

    @model_validator(mode='after')
    def unknown_is_not_shortfall(self):
        if self.match_status == 'confirmed_shortfall' and self.cv_proficiency is None:
            raise ValueError('Unknown CV proficiency cannot confirm a shortfall.')
        return self


class Document(Contract):
    id: DomainId = Field(alias='_id')
    version: Version
    schema_version: Literal['analysis-v1'] = SCHEMA_VERSION
    skill_mapping_version: Text
    created_at: datetime
    updated_at: datetime

    @field_validator('created_at', 'updated_at')
    @classmethod
    def mongo_precision(cls, value):
        if value.tzinfo is None:
            raise ValueError('Use timezone-aware timestamps.')
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)

    @model_validator(mode='after')
    def timestamps(self):
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None or self.updated_at < self.created_at:
            raise ValueError('Use ordered timezone-aware timestamps.')
        return self


class CvSnapshot(Document):
    """CV API boundary snapshot, not permission to query the CV database."""
    user_id: AccountId
    file_name: Text
    file_type: Literal['pdf', 'docx', 'txt']
    file_url: Text | None = None
    skills: list[CvSkill] = Field(default_factory=list, max_length=200)
    extraction_status: Literal['pending', 'processing', 'succeeded', 'failed']
    extraction_version: Text
    profile_version: Version

    @field_validator('file_url')
    @classmethod
    def private_reference(cls, value):
        if value and not value.startswith(('private://', 's3://', 'gs://')):
            raise ValueError('Use a private storage reference, not a public URL.')
        return value

    @model_validator(mode='after')
    def skills_ready(self):
        unique_skills(self.skills)
        if self.extraction_status != 'succeeded' and self.skills:
            raise ValueError('Only successful extraction may publish skills.')
        return self


class CareerGoal(Document):
    user_id: AccountId
    target_type: Literal['specific_job', 'career_exploration']
    field: Text
    role: Text
    company: Text | None = None
    location: Text | None = None
    seniority_level: Text | None = None
    job_url: SourceUrl | None = None
    interests: list[Text] = Field(default_factory=list, max_length=30)
    preferences: list[Text] = Field(default_factory=list, max_length=30)
    skills: list[TargetSkill] = Field(default_factory=list, max_length=200)
    non_skill_requirements: list[NonSkillRequirement] = Field(default_factory=list, max_length=100)
    requirements_source: Literal['pasted_jd', 'url_jd', 'document_jd', 'career_exploration']
    generation_version: Text
    generation: Generation | None = None
    readiness: Literal['ready', 'pending'] = 'ready'
    exploration_draft_id: DomainId | None = None
    exploration_draft_version: Version | None = None
    source_cv_id: DomainId | None = None
    source_cv_version: Version | None = None
    source_extraction_version: Text | None = None
    source_profile_version: Version | None = None

    @model_validator(mode='after')
    def scenario(self):
        unique_skills(self.skills)
        if self.readiness == 'ready' and (not self.skills or self.generation is None):
            raise ValueError('Ready goals need validated skills and generation provenance.')
        if (self.target_type == 'career_exploration') != (self.requirements_source == 'career_exploration'):
            raise ValueError('Target type and requirements source disagree.')
        if self.target_type == 'career_exploration' and any(s.origin == 'employer' for s in self.skills):
            raise ValueError('Exploration guidance is not employer-stated evidence.')
        return self


def canonical_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))


def unique_skills(skills):
    if len({s.skill_id for s in skills}) != len(skills):
        raise ValueError('Duplicate canonical skill IDs.')


class ResearchContext(Contract):
    company: Text | None = None
    field: Text
    role: Text
    location: Text | None = None
    seniority_level: Text | None = None

    def reuse_key(self):
        normalized = {k: ' '.join(v.casefold().split()) if v else None for k, v in self.model_dump().items()}
        return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


class InterviewResearch(Document, ResearchContext):
    skills: list[InterviewSkill] = Field(default_factory=list, max_length=200)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=100)
    research_status: Literal['pending', 'processing', 'succeeded', 'no_findings', 'failed']
    last_researched_at: datetime | None = None
    generation: Generation | None = None

    @property
    def context_key(self):
        return ResearchContext(**{k: getattr(self, k) for k in ResearchContext.model_fields}).reuse_key()

    @model_validator(mode='after')
    def references(self):
        unique_skills(self.skills)
        sources = {s.source_id: s for s in self.sources}
        if len(sources) != len(self.sources) or len({canonical_url(s.url) for s in self.sources}) != len(self.sources):
            raise ValueError('Duplicate source ID or URL.')
        for skill in self.skills:
            if len(set(skill.source_ids)) != len(skill.source_ids) or not set(skill.source_ids) <= sources.keys():
                raise ValueError('Interview evidence must resolve to distinct retrieved source IDs.')
            reports = {sources[key].report_group for key in skill.source_ids}
            if skill.independent_report_count != len(reports):
                raise ValueError('Independent reports must count deduplicated report groups.')
        if self.research_status != 'succeeded' and self.skills:
            raise ValueError('Only successful research may publish skills.')
        if self.research_status in ('succeeded', 'no_findings') and (not self.last_researched_at or not self.generation):
            raise ValueError('Finished research needs retrieval and generation provenance.')
        if self.last_researched_at and self.last_researched_at.tzinfo is None:
            raise ValueError('Use a timezone-aware research timestamp.')
        return self


class ResearchVersion(Contract):
    id: DomainId
    version: Version


class InputVersions(Contract):
    cv_id: DomainId
    cv_version: Version
    extraction_version: Text
    profile_version: Version
    career_goal_id: DomainId
    career_goal_version: Version
    generation_version: Text
    research: list[ResearchVersion] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def unique_research(self):
        if len({r.id for r in self.research}) != len(self.research):
            raise ValueError('Duplicate research versions.')
        return self


class SkillGapAnalysis(Document):
    user_id: AccountId
    cv_id: DomainId
    career_goal_id: DomainId
    research_ids: list[DomainId] = Field(default_factory=list, max_length=20)
    inputs: InputVersions
    job_skill_gaps: list[GapResult] = Field(default_factory=list, max_length=200)
    interview_prep_gaps: list[GapResult] = Field(default_factory=list, max_length=200)
    analysis_status: Literal['succeeded', 'partial']
    analysis_version: Text
    summary: Note
    generation: Generation

    @model_validator(mode='after')
    def referenced_inputs(self):
        if self.cv_id != self.inputs.cv_id or self.career_goal_id != self.inputs.career_goal_id:
            raise ValueError('Analysis IDs disagree with versioned inputs.')
        if self.research_ids != [r.id for r in self.inputs.research]:
            raise ValueError('Research IDs disagree with versioned inputs.')
        for values, kind in ((self.job_skill_gaps, 'job_skill'), (self.interview_prep_gaps, 'interview_preparation')):
            unique_skills(values)
            if any(s.gap_type != kind for s in values):
                raise ValueError('Gap is in the wrong result array.')
        if not self.research_ids and (self.analysis_status != 'partial' or self.interview_prep_gaps):
            raise ValueError('Unavailable research requires an explicitly partial analysis.')
        return self


def mongo_document(model: Document):
    def bson_dates(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min, timezone.utc)
        if isinstance(value, dict):
            return {key: bson_dates(item) for key, item in value.items()}
        if isinstance(value, list):
            return [bson_dates(item) for item in value]
        return value
    data = bson_dates(model.model_dump(by_alias=True, mode='python'))
    data['_id'] = ObjectId(model.id)
    for name in ('cv_id', 'career_goal_id', 'selected_career_goal_id', 'result_id', 'exploration_draft_id', 'source_cv_id'):
        if data.get(name):
            data[name] = ObjectId(data[name])
    if 'research_ids' in data:
        data['research_ids'] = [ObjectId(value) for value in data['research_ids']]
    if data.get('inputs'):
        for name in ('cv_id', 'career_goal_id'):
            data['inputs'][name] = ObjectId(data['inputs'][name])
        for ref in data['inputs']['research']:
            ref['id'] = ObjectId(ref['id'])
    # Mongo stores datetimes in UTC; ISO strings are reserved for API JSON.
    for name in ('created_at', 'updated_at', 'last_researched_at'):
        if data.get(name):
            data[name] = getattr(model, name)
    if len(BSON.encode(data)) > 512 * 1024:
        raise ValueError('Document exceeds the storage bound.')
    return data

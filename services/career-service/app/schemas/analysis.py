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
EmploymentType=Literal['internship','full_time','part_time','contract','unknown']
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Evidence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
SkillId = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+$', max_length=120)]
Count = Annotated[int, Field(strict=True, ge=0, le=1200)]
Version = Annotated[int, Field(strict=True, ge=1)]
Proficiency = Literal['beginner', 'intermediate', 'advanced', 'expert']
Priority = Annotated[Literal['required', 'preferred', 'unspecified', 'conflicting', 'suggested'], BeforeValidator(lambda value: 'required' if value == 'essential' else value)]


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
    skill_id: SkillId | None = None
    item_id: Text | None = None
    group_id: Text | None = None
    group_operator: Literal['all', 'any'] = 'all'
    correction: Literal['extracted', 'user'] = 'extracted'
    name: Text
    category: Text
    priority: Priority
    priority_evidence: Evidence | None = None
    priority_origin: Literal['employer', 'generated_guidance', 'user_declaration'] | None = None
    required_proficiency: Proficiency | None = None
    required_experience_months: Count | None = None
    context: Evidence | None = None
    evidence: Evidence | None = None
    origin: Literal['employer', 'generated_guidance', 'user_declaration']
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def grounded_employer(self):
        if self.origin == 'employer' and self.priority == 'suggested':
            raise ValueError('Employer requirements need evidence and stated priority.')
        return self


class NonSkillRequirement(Contract):
    requirement_id: Text
    category: Literal['qualification', 'experience', 'eligibility', 'location', 'work_condition', 'other']
    description: Evidence
    priority: Priority
    priority_evidence: Evidence | None = None
    priority_origin: Literal['employer', 'generated_guidance', 'user_declaration'] | None = None
    evidence: Evidence
    group_id: Text | None = None
    group_operator: Literal['all', 'any'] = 'all'
    origin: Literal['employer', 'generated_guidance', 'user_declaration'] = 'employer'
    correction: Literal['extracted', 'user'] = 'extracted'
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)
    minimum_months: Count | None = None
    maximum_months: Count | None = None
    completion_status: Literal['completed', 'in_progress', 'unspecified'] = 'unspecified'

    @model_validator(mode='after')
    def ordered_range(self):
        if self.minimum_months is not None and self.maximum_months is not None and self.minimum_months > self.maximum_months:
            raise ValueError('Minimum duration exceeds maximum duration.')
        return self


class ResearchSource(Contract):
    retrieved_at: datetime | None = None
    source_id: Text
    platform: Literal['employer', 'reddit', 'glassdoor', 'other']
    url: SourceUrl
    title: Text | None = None
    evidence: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2400)] | None = None
    reported_date: date | None = None
    published_date: date | None = None
    role_match: Literal['exact', 'related', 'unknown'] = 'unknown'
    reliability: Literal['official', 'anecdotal', 'unverified'] = 'unverified'
    # Assigned by retrieval/deduplication, never by the model.
    report_group: Text | None = None

    @field_validator('reported_date', 'published_date')
    @classmethod
    def not_future(cls, value):
        if value and value > datetime.now(timezone.utc).date():
            raise ValueError('Source dates cannot be in the future.')
        return value


class AnswerClaim(Contract):
    text: Evidence
    source_ids: list[Text] = Field(min_length=1,max_length=6)


class BraveAnswer(Contract):
    summary_id: Text
    provider: Literal['brave'] = 'brave'
    text: str = Field(min_length=1,max_length=2400)
    source_ids: list[Text] = Field(min_length=1,max_length=6)
    claims: list[AnswerClaim] = Field(default_factory=list,max_length=4)


class InterviewSkill(Contract):
    evidence_origin: Literal['source_excerpt','brave_summary'] = 'source_excerpt'
    summary_id: Text | None = None
    skill_id: SkillId | None = None
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
    employment_type: EmploymentType = 'unknown'
    company: Text | None = None
    location: Text | None = None
    seniority_level: Text | None = None
    job_url: SourceUrl | None = None
    interests: list[Text] = Field(default_factory=list, max_length=30)
    preferences: list[Text] = Field(default_factory=list, max_length=30)
    skills: list[TargetSkill] = Field(default_factory=list, max_length=200)
    non_skill_requirements: list[NonSkillRequirement] = Field(default_factory=list, max_length=100)
    summary: Evidence | None = None
    responsibilities: list[Evidence] = Field(default_factory=list, max_length=20)
    requirements_source: Literal['pasted_jd', 'url_jd', 'document_jd', 'career_exploration']
    generation_version: Text
    generation: Generation | None = None
    readiness: Literal['ready', 'pending'] = 'ready'
    exploration_draft_id: DomainId | None = None
    exploration_draft_version: Version | None = None
    source_review_id: DomainId | None = None
    source_review_version: Version | None = None
    requirements_need_review: bool = False
    source_cv_id: DomainId | None = None
    source_cv_version: Version | None = None
    source_extraction_version: Text | None = None
    source_profile_version: Version | None = None

    @model_validator(mode='after')
    def scenario(self):
        unique_skills(self.skills)
        if self.readiness == 'ready' and (not self.skills or self.generation is None or self.requirements_need_review or any(s.skill_id is None or s.priority == 'conflicting' for s in self.skills) or any(r.priority == 'conflicting' for r in self.non_skill_requirements)):
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
    known = [s.skill_id for s in skills if s.skill_id is not None]
    if len(set(known)) != len(known):
        raise ValueError('Duplicate canonical skill IDs.')


class ResearchContext(Contract):
    company: Text | None = None
    field: Text
    role: Text
    location: Text | None = None
    seniority_level: Text | None = None
    details_fingerprint: str | None = Field(default=None,pattern=r"^[0-9a-f]{64}$")

    def reuse_key(self):
        normalized = {k: ' '.join(v.casefold().split()) if v else None for k, v in self.model_dump().items()}
        return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


class ResearchCoverage(Contract):
    # Keep historical mixed-provider records readable; new acquisition uses Brave only.
    platform: Literal['brave','reddit']
    status: Literal['succeeded','no_findings','unavailable','not_connected']
    round: int = Field(default=0,ge=0,le=5)
    useful_sources:int|None=Field(default=None,ge=0,le=6)
    target_sources:int|None=Field(default=None,ge=1,le=6)
    limit_reached:bool=False


class InterviewEvidence(Contract):
    evidence_origin: Literal['source_excerpt','brave_summary']='source_excerpt'
    summary_id: Text | None=None
    source_ids: list[Text]=Field(min_length=1,max_length=3)
    text: Evidence

class InterviewStage(Contract):
    name: Text
    assessment_type: Text | None=None
    evidence: InterviewEvidence

class InterviewProcess(Contract):
    round_count: int | None=Field(default=None,ge=1,le=20,strict=True)
    round_count_evidence: InterviewEvidence | None=None
    stages: list[InterviewStage]=Field(default_factory=list,max_length=8)


from app.schemas.opportunity import OpportunityReport

class InterviewResearch(Document, ResearchContext):
    intelligence: OpportunityReport | None = None
    process: InterviewProcess=Field(default_factory=InterviewProcess)
    summaries: list[BraveAnswer] = Field(default_factory=list,max_length=2)
    coverage: list[ResearchCoverage] = Field(default_factory=list,max_length=6)
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
        if self.intelligence:
            for category in self.intelligence.categories.values():
                for finding in category.findings:
                    if len(finding.source_ids)!=len(finding.quotes) or any(s not in sources or quote not in (sources[s].evidence or '') or finding.value not in quote for s,quote in zip(finding.source_ids,finding.quotes)):
                        raise ValueError('Opportunity claim must resolve to original retrieved excerpts.')
        summaries={v.summary_id:v for v in self.summaries}
        if len(summaries)!=len(self.summaries):raise ValueError('Duplicate summary identity.')
        for summary in self.summaries:
            if len(set(summary.source_ids))!=len(summary.source_ids) or not set(summary.source_ids)<=sources.keys():raise ValueError('Summary citations must resolve to retrieved sources.')
            if any(not set(c.source_ids)<=set(summary.source_ids) or c.text not in summary.text for c in summary.claims):raise ValueError('Summary claims need matching text and citations.')
        process_links=[stage.evidence for stage in self.process.stages]
        if self.process.round_count is not None:
            if not self.process.round_count_evidence:raise ValueError('Interview round count needs evidence.')
            process_links.append(self.process.round_count_evidence)
        elif self.process.round_count_evidence is not None:raise ValueError('Unknown round count has no supporting count claim.')
        for link in process_links:
            if len(set(link.source_ids))!=len(link.source_ids) or not set(link.source_ids)<=sources.keys():raise ValueError('Interview process references must resolve.')
            if link.evidence_origin=='brave_summary':
                summary=summaries.get(link.summary_id)
                if not summary or not any(set(link.source_ids)<=set(c.source_ids) and link.text in c.text for c in summary.claims):raise ValueError('Interview process needs attributed summary evidence.')
            elif link.summary_id is not None or any(link.text not in (sources[s].evidence or '') for s in link.source_ids):raise ValueError('Interview process needs original evidence.')
        for stage in self.process.stages:
            if stage.name.casefold() not in stage.evidence.text.casefold() or (stage.assessment_type and stage.assessment_type.casefold() not in stage.evidence.text.casefold()):raise ValueError('Stage details must appear in supporting evidence.')
        if self.process.round_count is not None:
            from app.domain.interview import supported_round_count
            if not supported_round_count(self.process.round_count,self.process.round_count_evidence.text):raise ValueError('Round count must be explicit in evidence.')
        if self.research_status!='succeeded' and (self.process.stages or self.process.round_count is not None):raise ValueError('Only successful research may publish an interview process.')
        for skill in self.skills:
            if skill.evidence_origin=='brave_summary':
                summary=summaries.get(skill.summary_id)
                if not summary or not any(set(skill.source_ids)<=set(c.source_ids) for c in summary.claims):raise ValueError('Summary finding requires attributed claim references.')
            elif skill.summary_id is not None:raise ValueError('Direct evidence cannot be labelled as summary evidence.')
            if len(set(skill.source_ids)) != len(skill.source_ids) or not set(skill.source_ids) <= sources.keys():
                raise ValueError('Interview evidence must resolve to distinct retrieved source IDs.')
            reports = {sources[key].report_group for key in skill.source_ids if sources[key].report_group}
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
    for name in ('cv_id', 'career_goal_id', 'selected_career_goal_id', 'result_id', 'exploration_draft_id', 'source_review_id', 'source_cv_id'):
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

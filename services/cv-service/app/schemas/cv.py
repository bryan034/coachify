"""SCRUM-310: bounded, application-owned MongoDB and AI contracts.

No raw JD field is accepted. Account IDs remain Profile UUIDs; domain IDs are
ObjectIds represented as hex strings at the API boundary.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from bson import ObjectId
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

DomainId = Annotated[str, BeforeValidator(object_id), StringConstraints(pattern=r'^[0-9a-f]{24}$')]
AccountId = Annotated[str, BeforeValidator(account_id), StringConstraints(pattern=r'^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$')]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True, populate_by_name=True, revalidate_instances='always')

    @model_validator(mode='after')
    def document_bound(self):
        if len(self.model_dump_json(by_alias=True).encode()) > 512 * 1024:
            raise ValueError('Contract exceeds the 512 KiB document limit.')
        return self

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

def unique_skills(skills):
    if len({s.skill_id for s in skills}) != len(skills):
        raise ValueError('Duplicate canonical skill IDs.')


class CvSummary(Contract):
    id: DomainId = Field(alias='_id')
    user_id: AccountId
    file_name: Text
    extraction_status: Literal['pending', 'processing', 'succeeded', 'failed']
    extraction_version: Text
    version: int = Field(strict=True, ge=1)


class CvList(Contract):
    items: list[CvSummary] = Field(max_length=50)

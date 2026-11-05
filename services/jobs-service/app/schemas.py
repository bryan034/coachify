"""Public response and request models. Listing fields are derived from untrusted provider data."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobType = Literal['internship', 'graduate', 'full_time', 'part_time', 'contract', 'temporary', 'unknown']
Workplace = Literal['onsite', 'hybrid', 'remote', 'unknown']
Industry = Literal['artificial_intelligence', 'consumer_internet', 'crypto', 'financial_services', 'fintech', 'gaming', 'logistics', 'technology']
Provider = Literal['greenhouse', 'lever', 'ashby']
PostingStatus = Literal['open', 'closed']
ApplicationStatus = Literal['saved', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']

IDENTIFIER = r'^[0-9a-f]{32}$'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Posting(BaseModel):
    id: str
    title: str
    company: str
    industry: Industry
    location: str
    department: str | None = None
    job_type: JobType
    workplace: Workplace
    posted_at: datetime
    posted_at_estimated: bool
    application_deadline: datetime | None = None
    excerpt: str
    listing_url: str
    apply_url: str
    provider: Provider
    status: PostingStatus


class SearchResult(BaseModel):
    items: list[Posting]
    total: int
    next_cursor: str | None = None
    retrieved_at: datetime | None = None
    unavailable_sources: list[str] = Field(default_factory=list)


class FilterOption(BaseModel):
    value: str
    count: int


class FilterOptions(BaseModel):
    job_types: list[FilterOption]
    industries: list[FilterOption]
    workplaces: list[FilterOption]
    companies: list[FilterOption]
    last_synced_at: datetime | None = None
    retrieved_at: datetime | None = None
    unavailable_sources: list[str] = Field(default_factory=list)


class ApplicationSnapshot(BaseModel):
    title: str
    company: str
    location: str
    job_type: JobType
    listing_url: str
    apply_url: str


class StatusChange(BaseModel):
    status: ApplicationStatus
    at: datetime


class Application(BaseModel):
    id: str
    posting_id: str
    version: int
    status: ApplicationStatus
    posting_status: PostingStatus | Literal['removed', 'unknown']
    snapshot: ApplicationSnapshot
    history: list[StatusChange]
    created_at: datetime
    updated_at: datetime


class ApplicationList(BaseModel):
    items: list[Application]


class CreateApplication(Strict):
    posting_id: str = Field(pattern=IDENTIFIER)


class UpdateApplication(Strict):
    expected_version: int = Field(ge=1)
    status: ApplicationStatus

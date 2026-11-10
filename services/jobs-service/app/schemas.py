"""Public response and request models. Listing fields are derived from untrusted provider data."""
from datetime import datetime, date
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
    matched_skills: list[str] | None = None
    match_basis: str | None = None
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
    applied_at: date | None = None
    deadline: date | None = None
    follow_up_at: date | None = None
    notes: str = ''
    id: str
    posting_id: str
    # 'link' records were pasted by the user and match no listing elo read itself.
    source: Literal['listing', 'link'] = 'listing'
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


class SaveJobLink(Strict):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=120)
    location: str = Field(default='', max_length=120)
    job_type: JobType = 'unknown'


class ExternalSearch(BaseModel):
    name: str
    url: str


class ExternalSearchList(BaseModel):
    items: list[ExternalSearch]


class UpdateApplication(Strict):
    applied_at: date | None = None
    deadline: date | None = None
    follow_up_at: date | None = None
    notes: str = Field(default='', max_length=4000)
    expected_version: int = Field(ge=1)
    status: ApplicationStatus

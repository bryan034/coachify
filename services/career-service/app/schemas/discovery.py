"""Career direction and evidence contracts; targets reuse JDExtraction/RequirementReview."""
from typing import Literal
from app.schemas.providers import ResearchProvider
from pydantic import Field
from app.schemas.analysis import Contract, Text, Evidence, Version

class Scope(Contract):
    field: Text
    area: Text
    specificity: Literal['field','role_area','specialisation']='field'
    career_stage: Literal['internship','entry_level','experienced','unspecified']='unspecified'
    location: Text | None=None

class Suggestion(Contract):
    area: Text
    explanation: Evidence
    typical_work: Evidence
    difference: Evidence

class Decision(Contract):
    action: Literal['ASK_CLARIFICATION','SUGGEST_ROLES','CONFIRM_AREA','START_RESEARCH']
    scope: Scope | None
    question: Evidence | None
    recommendations: list[Suggestion]=Field(default_factory=list,max_length=3)
    reply: Evidence

class Plan(Contract):
    related_roles: list[Text]=Field(min_length=1,max_length=4)
    queries: list[Text]=Field(min_length=1,max_length=4)

class Requirement(Contract):
    kind: Literal['skill','responsibility','qualification']
    name: Text
    category: Literal['technical','domain','soft_skill']='technical'
    preferred: bool=False
    quote: Evidence

class Listing(Contract):
    ref: int=Field(ge=0,le=4)
    company: Text | None
    job_title: Text
    location: Text | None
    career_stage: Literal['internship','entry_level','experienced','unspecified']
    relevant: bool
    requirements: list[Requirement]=Field(max_length=15)

class Listings(Contract):
    listings: list[Listing]=Field(max_length=3)

class MarketSummary(Contract):
    responsibility_refs: list[int]=Field(max_length=20)

class StartDiscovery(Contract):
    consent: Literal[True]

class DiscoveryMessage(Contract):
    expected_version: Version
    message: Evidence

class ResearchDiscovery(Contract):
    expected_version: Version
    scope: Scope
    confirmed: Literal[True]
    refresh: bool=False

# Public responses contain reviewed structured data; no worker leases or raw messages.
from app.schemas.analysis import ResearchSource
from app.schemas.jd import JDExtractionResult

class SkillFrequency(Contract):
    name: Text
    skill_id: str | None
    requirement_type: Literal['core','specialisation','optional']
    mention_count: int = Field(ge=1,le=30)
    sample_size: int = Field(ge=1,le=30)
    source_ids: list[Text] = Field(max_length=30)
    original_terms: list[Text] = Field(max_length=30)

class DiscoverySession(Contract):
    id: str
    version: Version
    status: Literal['conversation','researching','waiting','failed','review','confirmed']
    stage: str | None
    decision: Decision | None
    scope: Scope | None
    related_roles: list[Text] = Field(max_length=4)
    sources: list[ResearchSource] = Field(max_length=30)
    stats: list[SkillFrequency] = Field(max_length=60)
    warnings: list[Evidence] = Field(max_length=10)
    listings_analysed: int = Field(ge=0,le=30)
    employers_analysed: int = Field(ge=0,le=30)
    coverage: Literal['good','limited','insufficient'] | None
    error_code: str | None
    limit_scope: Literal['user','provider'] | None
    provider: ResearchProvider
    retry_after: int | None = Field(ge=0)
    review: JDExtractionResult | None

class DiscoveryView(Contract):
    available: bool
    session: DiscoverySession | None

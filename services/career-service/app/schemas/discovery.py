"""Career direction and evidence contracts; targets reuse JDExtraction/RequirementReview."""
from typing import Annotated, Literal
from app.schemas.providers import ResearchProvider
from pydantic import Field, TypeAdapter, field_validator, model_validator
from app.schemas.analysis import Contract, Text, Evidence, Version

_text_list = TypeAdapter(list[Text])


def recent_texts(value, limit):
    """Validate every entry, then keep the newest distinct entries in input order.

    Context lists are ordered oldest first. A duplicate does not renew an older
    entry's position; spelling is preserved after the usual whitespace trimming.
    """
    values = _text_list.validate_python(value)
    distinct = {}
    for item in values:
        key = ' '.join(item.casefold().split())
        if key not in distinct:
            distinct[key] = item
    return list(distinct.values())[-limit:]

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

class ConversationMemory(Contract):
    interests: list[Text] = Field(default_factory=list, max_length=6)
    preferences: list[Text] = Field(default_factory=list, max_length=6)
    rejected_directions: list[Text] = Field(default_factory=list, max_length=6)
    open_questions: list[Text] = Field(default_factory=list, max_length=3)

    @field_validator('interests', 'preferences', 'rejected_directions', 'open_questions', mode='before')
    @classmethod
    def retain_recent(cls, value, info):
        return recent_texts(value, 3 if info.field_name == 'open_questions' else 6)

class ChatMessage(Contract):
    role: Literal['user','assistant']
    content: Annotated[str, Field(min_length=1, max_length=12000)]

class DiscoveryAnswer(Contract):
    status: Literal['unanswered','known','unsure','skipped'] = 'unanswered'
    value: Text | None = None
    evidence: Evidence | None = None

class DiscoveryUnderstanding(Contract):
    field: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    role_family_or_work: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    interest: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    other_interests: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    career_stage: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    location: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    avoided_activities: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    work_preferences: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)
    skill_ambiguity: DiscoveryAnswer = Field(default_factory=DiscoveryAnswer)

    @model_validator(mode='before')
    @classmethod
    def read_legacy_context(cls, value):
        if not isinstance(value,dict):return value
        value=dict(value)
        broad=value.pop('broad_exploration',None)
        value.pop('industry',None)
        role=value.get('role_family_or_work') or {}
        if isinstance(role,DiscoveryAnswer):role=role.model_dump()
        field=value.get('field') or {}
        if isinstance(field,DiscoveryAnswer):field=field.model_dump()
        if isinstance(broad,dict) and broad.get('status')=='known' and broad.get('value')=='yes' and (role.get('status') in (None,'unanswered','unsure','skipped') or role.get('value')==field.get('value')):
            value['role_family_or_work']={'status':'known','value':'keep it broad','evidence':broad.get('evidence')}
        return value

class Decision(Contract):
    action: Literal['ASK_CLARIFICATION','SUGGEST_ROLES','CONFIRM_AREA','START_RESEARCH','ANSWER','REFINE_SKILLS']
    scope: Scope | None
    question: Evidence | None
    recommendations: list[Suggestion]=Field(default_factory=list,max_length=5)
    reply: Evidence
    memory: ConversationMemory = Field(default_factory=ConversationMemory)
    understanding: DiscoveryUnderstanding = Field(default_factory=DiscoveryUnderstanding)
    source_ids: list[Text] = Field(default_factory=list, max_length=10)
    excluded_skills: list[Text] = Field(default_factory=list, max_length=60)
    requested_skills: list[Text] = Field(default_factory=list, max_length=30)

    @field_validator('excluded_skills', 'requested_skills', mode='before')
    @classmethod
    def retain_recent_skills(cls, value, info):
        return recent_texts(value, 60 if info.field_name == 'excluded_skills' else 30)

class Plan(Contract):
    related_roles: list[Text]=Field(min_length=1,max_length=4)
    queries: list[Text]=Field(min_length=1,max_length=4)

class SourceAssessment(Contract):
    ref: int = Field(ge=0, le=2)
    relevant: bool
    score: int = Field(ge=0, le=3)
    quote: Evidence | None

    @model_validator(mode='before')
    @classmethod
    def ignore_model_metadata(cls, value):
        # Older provider output may still include these. Neither determines
        # validity; companies are owned by retrieval and kind is not assessed.
        return {k:v for k,v in value.items() if k not in ('kind','company')} if isinstance(value,dict) else value

class SourceAssessments(Contract):
    sources: list[SourceAssessment] = Field(max_length=3)

class Requirement(Contract):
    kind: Literal['skill','responsibility','qualification']
    name: Text
    category: Literal['technical','domain','soft_skill']='technical'
    preferred: bool=False
    quote: Evidence

class Listing(Contract):
    ref: int=Field(ge=0,le=4)
    job_title: Text
    location: Text | None
    career_stage: Literal['internship','entry_level','experienced','unspecified']
    relevant: bool
    requirements: list[Requirement]=Field(max_length=15)

    @model_validator(mode='before')
    @classmethod
    def ignore_model_company(cls, value):
        return {k:v for k,v in value.items() if k!='company'} if isinstance(value,dict) else value

class Listings(Contract):
    listings: list[Listing]=Field(max_length=3)
    question: Evidence | None = None
    question_refs: list[int] = Field(default_factory=list, max_length=3)

class RecommendedSkill(Contract):
    skill_refs: list[int] = Field(default_factory=list, max_length=10)
    name: Text
    requirement_type: Literal['core','specialisation','optional']
    relevance: Evidence
    learning_priority: Literal['high','medium','low']

class MarketSummary(Contract):
    responsibility_refs: list[int]=Field(max_length=20)
    skills: list[RecommendedSkill] = Field(default_factory=list, max_length=30)
    specialisations: list[Text] = Field(default_factory=list, max_length=4)
    question: Evidence | None = None

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

# Owner-scoped responses include the private transcript; worker leases remain private.
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

class DiscoverySource(ResearchSource):
    # Employer metadata copied from Brave structured content, never generated.
    company: Text | None = None

class DiscoverySession(Contract):
    id: str
    version: Version
    status: Literal['conversation','researching','waiting','failed','review','confirmed']
    stage: str | None
    decision: Decision | None
    messages: list[ChatMessage] = Field(default_factory=list, max_length=1000)
    summary: MarketSummary | None = None
    scope: Scope | None
    related_roles: list[Text] = Field(max_length=4)
    sources: list[DiscoverySource] = Field(max_length=30)
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
    introduction: Evidence | None = None

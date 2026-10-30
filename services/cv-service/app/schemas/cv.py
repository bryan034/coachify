from elo_shared.skills import resolve, MAPPING_VERSION
from typing import Annotated, Literal
import calendar
from datetime import date
import re
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Months = Annotated[float, Field(ge=0, le=1200, allow_inf_nan=False, strict=True)]
Uncertainty = Literal['personal_contribution', 'responsibility', 'proficiency', 'duration', 'claim', 'qualification', 'date']
PartialDate = Annotated[str, StringConstraints(pattern=r'^\d{4}(?:-\d{2}(?:-\d{2})?)?$')]


def date_bounds(value):
    """A partial date is an interval, never a silently invented exact day."""
    if value is None: return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', value):
        raise ValueError('Use YYYY, YYYY-MM or YYYY-MM-DD, or leave the date unknown.')
    parts = [int(part) for part in value.split('-')]
    year = parts[0]
    if len(parts) == 1: return date(year, 1, 1), date(year, 12, 31)
    month = parts[1]
    if len(parts) == 2: return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    exact = date(*parts)
    return exact, exact


def validate_item_dates(value):
    """Validate merged item values as well as extraction and interpretation data."""
    start, end = date_bounds(value.get('start_date')), date_bounds(value.get('end_date'))
    if value.get('ongoing', False) and end:
        raise ValueError('An ongoing item cannot also have an end date.')
    if start and end and start[0] > end[1]:
        raise ValueError('The start date cannot be after the end date.')
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Mutation(StrictModel):
    expected_version: int = Field(ge=0, strict=True)
    mutation_id: UUID


class SelectionMutation(Mutation):
    cv_id: str = Field(min_length=1, max_length=100)


class ItemMutation(Mutation):
    action: Literal['update', 'remove']
    title: Title | None = None
    description: Text | None = None
    proficiency: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    experience_months: Months | None = None
    start_date: PartialDate | None = None
    end_date: PartialDate | None = None
    ongoing: bool = Field(default=False, strict=True)

    @model_validator(mode='after')
    def valid_action(self):
        fields = self.model_fields_set - {'expected_version', 'mutation_id', 'action'}
        if self.action == 'remove' and fields:
            raise ValueError('Removal cannot also update fields.')
        if self.action == 'update' and not fields:
            raise ValueError('Supply at least one corrected field.')
        if any(getattr(self, field) is None for field in fields & {'title', 'description'}):
            raise ValueError('Title and description must be non-empty.')
        validate_item_dates(self.model_dump(exclude_unset=True))
        return self


class AnswerMutation(Mutation):
    action: Literal['answer', 'skip']
    answer: Text | None = None

    @model_validator(mode='after')
    def valid_action(self):
        if self.action == 'answer' and not self.answer:
            raise ValueError('Enter an explanation or choose Skip.')
        if self.action == 'skip' and self.answer is not None:
            raise ValueError('Skip cannot overwrite an answer.')
        return self


class PrepareMutation(Mutation):
    career_target_id: str = Field(min_length=1, max_length=100)
    career_target_version: int = Field(ge=1, strict=True)
    career_target_selection_version: int | None = Field(default=None, ge=1, strict=True)


class SourceExcerpt(StrictModel):
    block_id: str = Field(min_length=1, max_length=20)
    excerpt: str = Field(min_length=1, max_length=500)


class ExtractedItem(StrictModel):
    kind: Literal['education', 'experience', 'project', 'skill']
    title: Title
    description: Text
    explicit: bool = Field(strict=True)
    evidence: list[SourceExcerpt] = Field(min_length=1, max_length=6)
    skill_names: list[Title] = Field(default_factory=list, max_length=15)
    category: str | None = Field(default=None, max_length=120)
    proficiency: str | None = Field(default=None, max_length=120)
    experience_months: Months | None = None
    start_date: PartialDate | None = None
    end_date: PartialDate | None = None
    ongoing: bool = Field(default=False, strict=True)
    context: str | None = Field(default=None, max_length=500)
    supporting_items: list[Annotated[int, Field(strict=True)]] = Field(default_factory=list, max_length=15)
    uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=7)

    @model_validator(mode='after')
    def valid_dates(self):
        validate_item_dates(self.model_dump())
        return self


class Extraction(StrictModel):
    items: list[ExtractedItem] = Field(min_length=1, max_length=160)


class TargetCondition(StrictModel):
    id: UUID
    kind: Literal['qualification', 'date', 'requirement']
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    item_kinds: list[Literal['education', 'experience', 'project', 'skill']] = Field(min_length=1, max_length=4)
    match_terms: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]] = Field(min_length=1, max_length=7)
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=600)] | None = None
    origin: Literal['user_reviewed_jd', 'user_guidance']
    source_requirement_id: str | None = None
    source_category: str | None = None
    source_priority: str | None = None
    source_origin: str | None = None
    group_id: str | None = None
    group_operator: Literal['all', 'any'] = 'all'


class ConfirmedContext(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1, strict=True)
    type: Literal['specific_job', 'career_exploration']
    confirmed: Literal[True]
    skill_ids: list[Annotated[str, Field(min_length=7, max_length=4000)]] = Field(max_length=200)
    selection_version: int = Field(default=1, ge=1, strict=True)
    role: str = Field(default='', max_length=200)
    field: str = Field(default='', max_length=200)
    conditions: list[TargetCondition] = Field(default_factory=list, max_length=100)

    @field_validator('confirmed', mode='before')
    @classmethod
    def confirmed_boolean(cls, value):
        if value is not True: raise ValueError('A confirmed Career context is required.')
        return value


class Evidence(BaseModel):
    id: str
    excerpt: str
    location: str


class SkillClaim(BaseModel):
    skill_id: str
    name: str
    attribution: Literal['personal', 'team', 'observed', 'denied', 'unknown']
    assistance: Literal['independent', 'assisted', 'supervised', 'unknown']
    proficiency: str | None
    experience_months: float | None
    evidence: list[Evidence]
    evidence_type: str
    support_uncertain: bool


class CvItem(BaseModel):
    id: str
    source_fingerprint: str | None = None
    kind: Literal['education', 'experience', 'project', 'skill']
    title: str
    description: str
    provenance: Literal['explicit', 'inferred', 'user_corrected', 'user_clarified']
    evidence: list[Evidence]
    skill_ids: list[str]
    skill_names: list[str] = []
    category: str = 'unspecified'
    proficiency: str | None
    experience_months: float | None
    start_date: str | None = None
    end_date: str | None = None
    ongoing: bool = False
    context: str | None = None
    removed: bool
    supporting_item_ids: list[str] = []
    support_uncertain: bool = False
    uncertainties: list[str] = []
    skill_claims: list[SkillClaim] = []


class SkillSource(BaseModel):
    item_id: str
    evidence_type: str
    explicit: bool
    support_uncertain: bool
    attribution: Literal['personal', 'team', 'observed', 'denied', 'unknown'] = 'unknown'
    assistance: Literal['independent', 'assisted', 'supervised', 'unknown'] = 'unknown'
    proficiency: str | None = None
    experience_months: float | None = None
    evidence: list[Evidence] = []


class CvSkill(BaseModel):
    canonical_skill_id: str | None = None
    skill_registry_version: str = MAPPING_VERSION
    @model_validator(mode='after')
    def canonical_identity(self):
        self.canonical_skill_id = resolve(self.name, self.category)
        self.skill_registry_version = MAPPING_VERSION
        return self
    skill_id: str
    name: str
    category: str
    proficiency: str | None
    experience_months: float | None
    context: str | None
    evidence: list[Evidence]
    evidence_type: str
    explicit: bool
    item_ids: list[str]
    sources: list[SkillSource]
    conflicting_fields: list[str] = []


class InterpretedClaim(StrictModel):
    skill_id: Annotated[str, StringConstraints(min_length=7, max_length=4000)]
    name: Title
    attribution: Literal['personal', 'team', 'observed', 'denied', 'unknown']
    assistance: Literal['independent', 'assisted', 'supervised', 'unknown'] = 'unknown'
    proficiency: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    experience_months: Months | None = None
    evidence_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    changed_fields: list[Literal['attribution', 'assistance', 'proficiency', 'experience_months']] = Field(min_length=1, max_length=4)


class InterpretedDates(StrictModel):
    start_date: PartialDate | None = None
    end_date: PartialDate | None = None
    ongoing: bool = Field(default=False, strict=True)
    changed_fields: list[Literal['start_date', 'end_date', 'ongoing']] = Field(min_length=1, max_length=3)
    evidence_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @model_validator(mode='after')
    def valid_dates(self):
        validate_item_dates(self.model_dump())
        return self


class InterpretationOutput(StrictModel):
    item_id: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    answer_revision: int = Field(ge=1, strict=True)
    resolution: Literal['resolved', 'partial', 'unanswerable']
    claims: list[InterpretedClaim] = Field(default_factory=list, max_length=20)
    dates: InterpretedDates | None = None
    statement_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    resolved_uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=7)
    remaining_uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=7)


class InterpretationMetadata(StrictModel):
    provider: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    schema_version: str = Field(min_length=1, max_length=30)


class SavedInterpretation(InterpretationOutput):
    summary: str = Field(max_length=2000)
    metadata: InterpretationMetadata
    applied_sequence: int = Field(ge=1, strict=True)
    extraction_version: int = Field(ge=1, strict=True)


class Clarification(BaseModel):
    id: str
    item_id: str
    kind: Literal['project', 'work', 'other']
    question: str
    uncertainty_key: str
    status: Literal['unanswered', 'answered', 'skipped']
    answer: str | None
    career_target_id: str | None
    career_target_version: int | None
    career_target_type: str | None = None
    extraction_version: int
    reconciliation_required: bool = False
    uncertainty: str
    answer_revision: int = 0
    answer_sequence: int = 0
    interpretation_status: Literal['not_requested', 'pending', 'ready', 'failed'] = 'not_requested'
    interpretation_error: str | None = None
    resolution: Literal['unresolved', 'resolved', 'partial', 'unanswerable'] = 'unresolved'
    interpretation: SavedInterpretation | None = None
    followup_of: str | None = None
    reconciled_from: dict[str, str] | None = None


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool


class ExtractionMetadata(BaseModel):
    provider: str
    model: str
    prompt_version: str
    schema_version: str


class CvSummary(BaseModel):
    id: str
    file_name: str
    file_type: Literal['pdf', 'docx']
    status: Literal['queued', 'processing', 'ready', 'failed']
    operation_id: str
    version: int
    extraction_version: int
    effective_version: int
    profile_version: int
    created_at: str
    updated_at: str
    error: ErrorInfo | None
    source_available: bool


class CvDetail(CvSummary):
    items: list[CvItem]
    skills: list[CvSkill]
    original_items: list[CvItem]
    clarifications: list[Clarification]
    extraction: ExtractionMetadata | None
    notices: list[str]
    reconciliation: list[dict[str, str]]
    reconciliation_candidate_id: str | None = None
    review_required: bool


class Selection(BaseModel):
    cv_id: str | None
    version: int


class CvList(BaseModel):
    cvs: list[CvSummary]
    selection: Selection
    next_cursor: str | None = None


class QuestionEnvelope(BaseModel):
    questions: list[Clarification]
    deferred: bool
    reason: str | None
    cv_version: int
    context: ConfirmedContext | None
    prepared: bool


class CapabilityInput(BaseModel):
    cv_id: str
    selection_version: int
    extraction_version: int
    effective_version: int
    declarations_version: int
    profile_version: int
    items: list[CvItem]
    skills: list[CvSkill]
    declarations: list[dict]
    schema_version: Literal['1']
    normalization_version: Literal['1']


class Policy(BaseModel):
    max_file_bytes: int
    formats: list[Literal['pdf', 'docx']]
    max_answer_chars: int
    max_item_chars: int
    extraction_configured: bool
    original_retention_hours: int
    ocr_supported: bool
    max_text_chars: int
    max_title_chars: int
    max_description_chars: int
    max_saved_cvs: int
    max_stored_original_bytes: int
    max_model_calls_per_day: int
    max_concurrent_model_calls: int


class ApiError(BaseModel):
    detail: str
    code: str | None = None

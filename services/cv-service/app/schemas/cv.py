from elo_shared.skills import resolve, MAPPING_VERSION
from elo_shared.skill_groups import skill_groups, skill_subgroups
from app.schemas.interview_evidence import ReviewFact, SkillEstimate, SkillLevel, ExtractedSkillLevel
from app.domain.extraction_errors import FailureStage, FailureCategory, ProviderReason, ProviderParameter
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


class RenameMutation(Mutation):
    display_name: Title

    @field_validator('display_name')
    @classmethod
    def readable_name(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Use a readable CV title without control characters.')
        return value


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
    excerpt: str = Field(min_length=1, description='Source-supported quotation or faithful summary; exact original formatting is not required.')


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
    start_date: str | None = Field(default=None, max_length=120)
    end_date: str | None = Field(default=None, max_length=120)
    ongoing: bool = Field(default=False, strict=True)
    context: str | None = Field(default=None, max_length=500)
    supporting_items: list[Annotated[int, Field(strict=True)]] = Field(default_factory=list, max_length=15)
    uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=7)
    review_evidence: list[ReviewFact] = Field(default_factory=list, max_length=12)
    skill_levels: list[ExtractedSkillLevel] = Field(default_factory=list, max_length=15)

    @model_validator(mode='after')
    def valid_dates(self):
        # Dates are optional extraction hints, never a reason to lose CV facts.
        for field in ('start_date', 'end_date'):
            try:
                date_bounds(getattr(self, field))
            except ValueError:
                setattr(self, field, None)
        if self.ongoing:
            self.end_date = None
        try:
            validate_item_dates(self.model_dump())
        except ValueError:
            self.start_date = self.end_date = None
        return self


class Extraction(StrictModel):
    items: list[ExtractedItem] = Field(min_length=1, max_length=160)
    other_information: list[SourceExcerpt] = Field(default_factory=list, max_length=160)


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
    excerpt: str = Field(description='Source-linked evidence; CV extraction may contain a faithful summary rather than an exact quotation.')
    location: str


class SkillLevelInfo(BaseModel):
    """The skill's own 1-10 level on the shared competence scale (not a goal comparison).

    `uncertain` means the CV and review were not conclusive; the level is then null.
    """
    level: SkillLevel | None
    status: Literal['rated', 'uncertain'] = 'rated'
    rationale: str
    source: Literal['cv', 'review'] = Field(description="cv: judged at extraction from the saved CV; review: judged during the CV review from the CV and the user's answers.")
    evidence: list[Evidence]

    @model_validator(mode='after')
    def consistent_status(self):
        self.status = 'uncertain' if self.level is None else 'rated'
        return self


class SkillClaim(BaseModel):
    skill_id: str
    name: str
    attribution: Literal['personal', 'team', 'observed', 'denied', 'unknown']
    assistance: Literal['independent', 'assisted', 'supervised', 'unknown']
    proficiency: str | None
    experience_months: float | None
    skill_level: SkillLevelInfo | None = None
    evidence: list[Evidence]
    evidence_type: str
    support_uncertain: bool


class ValidationIssue(BaseModel):
    status: Literal['unverified']
    code: str = Field(description='The check this section failed after retrying; no CV content.')
    message: str


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
    review_evidence: list[ReviewFact] = Field(default_factory=list, max_length=240)
    validation_issue: ValidationIssue | None = None


class SkillSource(BaseModel):
    item_id: str
    evidence_type: str
    explicit: bool
    support_uncertain: bool
    attribution: Literal['personal', 'team', 'observed', 'denied', 'unknown'] = 'unknown'
    assistance: Literal['independent', 'assisted', 'supervised', 'unknown'] = 'unknown'
    proficiency: str | None = None
    experience_months: float | None = None
    skill_level: SkillLevelInfo | None = None
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
    skill_level: SkillLevelInfo | None = Field(default=None, description="Highest rated level across this skill's sources; uncertain only when no source could be rated.")
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
    skill_level: SkillLevel | None = None
    skill_level_rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)] | None = None
    evidence_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    changed_fields: list[Literal['attribution', 'assistance', 'proficiency', 'experience_months', 'skill_level']] = Field(min_length=1, max_length=5)


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
    review_evidence: list[ReviewFact] = Field(default_factory=list, max_length=12)
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
    failure_stage: FailureStage | None = None
    failure_category: FailureCategory | None = None
    provider_status_code: int | None = Field(default=None, ge=100, le=599)
    repair_attempted: bool | None = None
    provider_reason: ProviderReason | None = None
    provider_parameter: ProviderParameter | None = None


class ExtractionMetadata(BaseModel):
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    response_mode: Literal['json_schema', 'json_object'] | None = None
    workflow_version: str | None = None
    repair_attempts: int | None = Field(default=None, ge=0, le=1)


class ProcessingProgress(BaseModel):
    stage: Literal['queued', 'source_read', 'document_parse', 'model_request', 'extraction_validation', 'model_repair', 'publication', 'ready']
    percent: int = Field(ge=0, le=100)
    message: str


class ReviewProgress(BaseModel):
    reviewed_topics: int = Field(ge=0)
    total_topics: int = Field(ge=0)


class CvSummary(BaseModel):
    # Topics covered so far in the guided review; null until a review has started.
    review_progress: ReviewProgress | None = None
    processing_progress: ProcessingProgress | None = None
    profile_reviewed_effective_version: int | None = None
    id: str
    file_name: str
    display_name: str | None = None
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


class ReviewSummary(BaseModel):
    answered_questions: int = Field(default=0, ge=0)
    experiences: int = Field(default=0, ge=0)
    skills_added: int = Field(default=0, ge=0)
    skills_corrected: int = Field(default=0, ge=0)
    skills_removed: int = Field(default=0, ge=0)
    added_skill_ids: list[str] = Field(default_factory=list)
    skill_notes: dict[str, str] = Field(default_factory=dict)


class CvDetail(CvSummary):
    # Display categories by skill name, derived on read; see elo_shared.skill_groups.
    skill_groups: dict[str, str] = Field(default_factory=dict)
    skill_subgroups: dict[str,str] = Field(default_factory=dict)
    @model_validator(mode='after')
    def display_groups(self):
        self.skill_groups = skill_groups((skill.name, skill.category) for skill in self.skills)
        self.skill_subgroups = skill_subgroups((skill.name,skill.category) for skill in self.skills)
        return self
    skill_estimates: list[SkillEstimate] = Field(default_factory=list)
    other_information: list[Evidence] = Field(default_factory=list, max_length=160)
    items: list[CvItem]
    skills: list[CvSkill]
    original_items: list[CvItem]
    clarifications: list[Clarification]
    extraction: ExtractionMetadata | None
    notices: list[str]
    reconciliation: list[dict[str, str]]
    reconciliation_candidate_id: str | None = None
    review_required: bool
    review_summary: ReviewSummary = Field(default_factory=ReviewSummary)


class Selection(BaseModel):
    cv_id: str | None
    version: int


class CvDeletionResult(BaseModel):
    cv_id: str
    deleted: Literal[True]
    selection: Selection


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

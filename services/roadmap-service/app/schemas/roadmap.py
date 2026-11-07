"""Contracts for the timed roadmap: confirmed settings, model output and saved plans."""
from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import ConfigDict, Field, StringConstraints, model_validator
from .base import Contract, Mutation, Text
from .tasks import EditableTask, RevisionReview, TaskReadiness

Clock=Annotated[str,StringConstraints(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
Key=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=80)]
Title=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
Focus=Literal['interview_practice','portfolio_work','hands_on_projects','courses_and_reading','certification','networking']

class StudyBlock(Contract):
    day:int=Field(strict=True,ge=0,le=6)
    start_time:Clock
    duration_minutes:int=Field(strict=True,ge=15,le=480)
    kind:Literal['preferred','backup']='preferred'
    @model_validator(mode='after')
    def ends_by_midnight(self):
        hours,minutes=self.start_time.split(':')
        if int(hours)*60+int(minutes)+self.duration_minutes>1440:raise ValueError('A study block must end by midnight.')
        return self
class BlackoutRule(Contract):
    """A whole day or a time slot, once or repeating. Weekly uses weekdays; monthly uses start_date's day.

    Ordering problems are reported as runway issues so the planner form can explain them.
    """
    frequency:Literal['once','daily','weekly','monthly']='once'
    start_date:date
    end_date:date|None=None
    interval:int=Field(default=1,strict=True,ge=1,le=52)
    weekdays:list[Annotated[int,Field(strict=True,ge=0,le=6)]]=Field(default_factory=list,max_length=7)
    start_time:Clock|None=None
    end_time:Clock|None=None
class Duration(Contract):
    value:int=Field(strict=True,ge=1,le=52)
    unit:Literal['weeks','months']
    @model_validator(mode='after')
    def within_a_year(self):
        if self.unit=='months' and self.value>12:raise ValueError('Plan at most twelve months at a time.')
        return self
class PlannerConfig(Contract):
    """Date problems are reported as runway issues so the settings panel can explain them."""
    start_date:date|None=None
    target_date:date|None=None
    duration:Duration|None=None
    time_zone:str='Asia/Singapore'
    weekly_minutes:int|None=Field(default=None,strict=True,ge=0,le=10080)
    blocks:list[StudyBlock]=Field(default_factory=list,max_length=28)
    use_backup:bool=False
    blackouts:list[BlackoutRule]=Field(default_factory=list,max_length=366)
    preferred_session_minutes:int=Field(default=60,strict=True,ge=15,le=480)
    learning_focus:list[Focus]=Field(default_factory=list,max_length=6)
    learning_notes:str=Field(default='',max_length=1000)
    @model_validator(mode='after')
    def coherent(self):
        try:ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Choose a valid planning time zone.') from None
        if len(set(self.learning_focus))!=len(self.learning_focus):raise ValueError('Choose each learning focus once.')
        return self

# The patch fields stay loose on purpose. A model mistake then reaches the merge step, where
# it leaves the settings unchanged and is explained in chat, rather than failing the turn.
class PatchBlock(Contract):
    day:int
    start_time:str
    duration_minutes:int
    kind:str
class PatchBlackout(Contract):
    frequency:str
    start_date:str
    end_date:str|None=None
    interval:int|None=None
    weekdays:list[int]|None=None
    start_time:str|None=None
    end_time:str|None=None
class PatchDuration(Contract):
    value:int
    unit:str
class SettingsPatch(Contract):
    start_date:str|None=None
    target_date:str|None=None
    duration:PatchDuration|None=None
    weekly_minutes:int|None=None
    blocks:list[PatchBlock]|None=None
    use_backup:bool|None=None
    blackouts:list[PatchBlackout]|None=None
    preferred_session_minutes:int|None=None
    learning_focus:list[str]|None=None
    learning_notes:str|None=None
class ChatTurn(Contract):
    reply:Text
    settings:SettingsPatch=Field(default_factory=SettingsPatch)
    revision_instruction:str|None=Field(default=None,max_length=2000)

class DraftGap(Contract):
    id:Key
    name:Title
    requirement_ref:str|None=None
    source:Literal['stated','inferred']
    inference_reason:str|None=Field(default=None,max_length=1000)
    status:Literal['confirmed_gap','unknown']
    priority:int=Field(strict=True,ge=1,le=100)
    plan_impact:Literal['material','minor']
    resolution:Literal['diagnostic','confirm_experience']|None=None
    confirmation_question:str|None=Field(default=None,max_length=500)
    rationale:Text
class DraftMilestone(Contract):
    key:Key
    title:Title
    gap_ids:list[Key]=Field(default_factory=list,max_length=20)
    prerequisite_keys:list[Key]=Field(default_factory=list,max_length=16)
    estimated_minutes:int=Field(strict=True,ge=0,le=60000)
    projected_start:date
    projected_end:date
    demonstrable_outcome:Text
class DraftAssignment(Contract):
    key:Key
    milestone_key:Key
    gap_id:str|None=Field(default=None,max_length=80)
    kind:Literal['study','diagnostic']='study'
    date:date
    start_time:Clock
    duration_minutes:int=Field(strict=True,ge=1,le=480)
    task:Text
    completion_criterion:Text
class DraftBeyond(Contract):
    title:Title
    gap_ids:list[Key]=Field(default_factory=list,max_length=20)
    reason:Text
    estimated_minutes:int=Field(strict=True,ge=0,le=60000)
class DeadlineOutcome(Contract):
    summary:Text
    achievable_by_target:list[Text]=Field(default_factory=list,max_length=20)
    fits_in_runway:bool
class DraftExclusion(Contract):
    requirement_ref:Key
    reason:Text
    quote:Text
class PlanDraft(Contract):
    summary:Text
    gaps:list[DraftGap]=Field(default_factory=list,max_length=40)
    milestones:list[DraftMilestone]=Field(default_factory=list,max_length=16)
    assignments:list[DraftAssignment]=Field(default_factory=list,max_length=40)
    deadline_outcome:DeadlineOutcome
    beyond_deadline:list[DraftBeyond]=Field(default_factory=list,max_length=20)
    exclusions:list[DraftExclusion]=Field(default_factory=list,max_length=20)

class RunwayRequest(Contract):
    config:PlannerConfig
class SaveConfig(Mutation):
    config:PlannerConfig
class GeneratePlan(Mutation):
    allow_partial_assessment:bool=False
class AssignmentStatus(Mutation):
    assignment_id:str=Field(min_length=1,max_length=80)
    status:Literal['scheduled','completed']
    evidence_note:str|None=Field(default=None,max_length=2000)
class MilestoneOutcome(Mutation):
    milestone_id:str=Field(min_length=1,max_length=80)
    demonstrated:bool
    note:str|None=Field(default=None,max_length=2000)
class ExperienceConfirmation(Mutation):
    gap_id:str=Field(min_length=1,max_length=80)
    answer:Literal['have_experience','some_experience','no_experience','not_sure']
    note:str|None=Field(default=None,max_length=1000)

class RunwayIssue(Contract):
    code:str
    message:str
class RunwayWeek(Contract):
    week_start:str
    weekly_cap:int
    completed_minutes:int
    preferred_minutes:int
    backup_extra_minutes:int
    usable_minutes:int
    partial:bool
class RunwayCalendar(Contract):
    days:int
    weeks:int
    extra_days:int
    label:str
    partial_first_week:bool
class RunwayStudy(Contract):
    preferred_minutes:int
    backup_extra_minutes:int
    usable_minutes:int
class RunwayResolved(Contract):
    today:str
    start_date:str
    target_date:str|None
    matched_duration:Duration|None
class Runway(Contract):
    can_generate:bool
    issues:list[RunwayIssue]
    resolved:RunwayResolved
    calendar:RunwayCalendar|None
    study:RunwayStudy
    weeks:list[RunwayWeek]
    first_planning_week:str|None
class OperationError(Contract):
    detail:str
    code:str
class OperationView(Contract):
    """Stages run preparing, assessing, writing, correcting, then complete or failed."""
    id:str
    status:Literal['pending','running','succeeded','failed']
    stage:str
    error:OperationError|None=None
    retry_after:int|None=None
class OperationAccepted(Contract):
    version:int
    operation:OperationView|None
# Stored records can predate these models. Unexpected extras stay readable instead of failing the page.
class SavedRecord(Contract):
    model_config=ConfigDict(extra='allow')
class MilestoneOutcomeRecord(SavedRecord):
    demonstrated:bool
    note:str|None=None
    recorded_at:str|None=None
    source:Literal['self_reported']|None=None
class AssignmentChange(SavedRecord):
    model_config=ConfigDict(extra='allow',populate_by_name=True)
    at:str|None=None
    from_status:Literal['scheduled','completed']|None=Field(default=None,alias='from')
    to:Literal['scheduled','completed']|None=None
    evidence_note:str|None=None
class PlanChanges(SavedRecord):
    completed_preserved:int=0
    assignments_added:list[str]=Field(default_factory=list)
    assignments_removed:list[str]=Field(default_factory=list)
    assignments_moved:list[str]=Field(default_factory=list)
    milestones_added:list[str]=Field(default_factory=list)
    milestones_removed:list[str]=Field(default_factory=list)
    milestones_moved:list[str]=Field(default_factory=list)
class PlanGeneration(SavedRecord):
    prompt_version:str|None=None
    attempts:int|None=None
class ConfirmationRecord(SavedRecord):
    name:str|None=None
    question:str|None=None
    answer:Literal['have_experience','some_experience','no_experience','not_sure']
    note:str|None=None
    source:Literal['self_reported']|None=None
    recorded_at:str|None=None
class MilestoneProgress(Contract):
    sessions_total:int
    sessions_completed:int
    completed_minutes:int
    tasks_total:int
    tasks_completed:int
    review_needed:bool
class LearningSession(Contract):
    id:str
    date:str
    start_time:str
    duration_minutes:int
    task:str
    completion_criterion:str
class LearningStep(Contract):
    gap_id:str
    name:str
    status:Literal['confirmed_gap','unknown']
    state:Literal['not_scheduled','not_started','in_progress','done']
    priority:int
    rationale:str
    milestones:list[str]
    sessions_total:int
    sessions_completed:int
    sessions_missed:int
    completed_minutes:int
    remaining_minutes:int
    next_session:LearningSession|None
class LearningPlan(Contract):
    has_roadmap:bool
    roadmap_id:str|None
    skills_total:int
    skills_started:int
    skills_done:int
    steps:list[LearningStep]
class PlanGap(DraftGap):
    pass
class PlanMilestone(DraftMilestone):
    model_config=ConfigDict(extra='forbid')
    id:str
    outcome:MilestoneOutcomeRecord
class PlanAssignment(DraftAssignment):
    model_config=ConfigDict(extra='forbid')
    id:str
    status:Literal['scheduled','completed']
    completed_at:str|None=None
    evidence_note:str|None=None
    history:list[AssignmentChange]=Field(default_factory=list)
class PlannedRoadmap(Contract):
    model_config=ConfigDict(extra='allow')
    schema_version:Literal['roadmap-v2']
    id:str
    assessment_id:str
    assessment_hash:str
    assessment:dict
    config:PlannerConfig
    config_hash:str
    confirmations_hash:str
    base_active_id:str|None
    pace_baseline_id:str|None=None
    created_at:str
    updated_at:str|None=None
    request_hash:str|None=None
    completed_at_generation:int=0
    first_planning_week:str
    summary:str
    gaps:list[PlanGap]
    milestones:list[PlanMilestone]
    assignments:list[PlanAssignment]
    editable_tasks:list[EditableTask]|None=None
    revision_review:list[RevisionReview]=Field(default_factory=list)
    deadline_outcome:DeadlineOutcome
    beyond_deadline:list[DraftBeyond]
    exclusions:list[DraftExclusion]
    changes:PlanChanges|None=None
    generation:PlanGeneration
class PlanReview(Contract):
    next_assignment_id:str|None
    missed_assignment_ids:list[str]
    remaining:Runway
    milestones:dict[str,MilestoneProgress]
class DashboardSource(Contract):
    version:int
    active:PlannedRoadmap|None
    active_review:PlanReview|None
    task_readiness:dict[str,TaskReadiness]
class Signal(Contract):
    kind:Literal['settings','evidence','progress','next_week']
    message:str
class InputRecord(Contract):
    ref:str
    name:str|None
    kind:str|None
    text:str
class InputSkill(InputRecord):
    attribution:str|None=None
    assistance:str|None=None
    proficiency:str|int|float|None=None
    experience_months:int|float|None=None
    support_uncertain:bool|None=None
class InputExperience(InputRecord):
    start_date:str|None=None
    end_date:str|None=None
    ongoing:bool|None=None
class PlanInputs(Contract):
    """goal and cv belong to the Assessment service's context, so they stay open objects here."""
    goal:dict|None
    cv:dict|None
    skills:list[InputSkill]
    experience:list[InputExperience]
    skill_groups:dict[str,str]
class PlannerView(Contract):
    config:PlannerConfig
    config_saved:bool
    runway:Runway
    inputs:PlanInputs
    candidate:PlannedRoadmap|None
    candidate_review:PlanReview|None
    candidate_blockers:list[RunwayIssue]
    active:PlannedRoadmap|None
    active_review:PlanReview|None
    task_warnings:list[dict]=Field(default_factory=list)
    confirmations:dict[str,ConfirmationRecord]
    signals:list[Signal]
    retry_generate:GeneratePlan|None=None

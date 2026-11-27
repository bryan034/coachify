"""Contracts for the timed roadmap: confirmed settings, model output and saved plans."""
from datetime import date
import json
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import ConfigDict, Field, StringConstraints, model_validator
from .base import Contract, Mutation, Text
from .notes import NotesDocument
from .tasks import EditableTask, RevisionReview, SavedTaskSlot, TaskReadiness, TaskSkill, TaskTitle, TaskWarning

Day=date
Clock=Annotated[str,StringConstraints(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
Key=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=80)]
Title=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
Focus=Literal['interview_practice','portfolio_work','hands_on_projects','courses_and_reading','certification','networking']

class StudyBlock(Contract):
    day:int=Field(strict=True,ge=0,le=6)
    start_time:Clock
    duration_minutes:int=Field(strict=True,ge=15,le=480)
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
class ReducedPeriod(Contract):
    """A Profile availability period, copied by the service so every capacity calculation sees the same dates."""
    start_date:date
    end_date:date
    weekly_minutes:int=Field(strict=True,ge=0,le=10080)
SHAPE_FIELDS=('start_date','target_date','duration','time_zone','week_start_day','weekly_minutes','learning_focus','learning_notes','learning_topics')
DISPLAY_FIELDS=('time_format','goal_unit')
class PlannerConfig(Contract):
    """Date problems are reported as runway issues so the settings panel can explain them.

    SHAPE_FIELDS decide what the outline covers. DISPLAY_FIELDS only change how the page reads.
    Every other field is a scheduling rule that applies from the next week that is planned.
    """
    start_date:date|None=None
    target_date:date|None=None
    duration:Duration|None=None
    time_zone:str='Asia/Singapore'
    weekly_minutes:int|None=Field(default=None,strict=True,ge=0,le=10080)
    blocks:list[StudyBlock]=Field(default_factory=list,max_length=28)
    allow_overflow:bool=False
    overflow_start:Clock='09:00'
    overflow_end:Clock='23:00'
    blackouts:list[BlackoutRule]=Field(default_factory=list,max_length=366)
    preferred_session_minutes:int=Field(default=60,strict=True,ge=15,le=480,description='The longest single session. Longer tasks are split.')
    break_minutes_per_hour:int=Field(default=10,strict=True,ge=0,le=30,description='Rest left after a session for each hour studied.')
    min_session_minutes:int=Field(default=25,strict=True,ge=15,le=120,description='The shortest session worth scheduling.')
    max_daily_minutes:int|None=Field(default=None,strict=True,ge=15,le=1440)
    lead_minutes:int=Field(default=0,strict=True,ge=0,le=1440,description='Notice needed before a newly planned session can start.')
    week_start_day:int=Field(default=0,strict=True,ge=0,le=6)
    plan_day:int|None=Field(default=None,strict=True,ge=0,le=6,description='Weekday on which next week can be planned. Null means the last day of the week.')
    rest_days_per_week:int=Field(default=0,strict=True,ge=0,le=6)
    apply_reduced_periods:bool=True
    reduced_periods:list[ReducedPeriod]=Field(default_factory=list,max_length=100,description='Set by the service from Profile; values sent by a client are replaced.')
    unfinished_default:Literal['ask','carry','defer']='ask'
    max_carry_minutes:int|None=Field(default=None,strict=True,ge=0,le=10080,description='Most carried-over work in one week. Null means half the weekly hours.')
    time_format:Literal['24h','12h']='24h'
    goal_unit:Literal['tasks','hours']='tasks'
    learning_focus:list[Focus]=Field(default_factory=list,max_length=6)
    learning_notes:str=Field(default='',max_length=1000)
    learning_topics:list[Title]=Field(default_factory=list,max_length=12)
    @model_validator(mode='before')
    @classmethod
    def without_backup_blocks(cls,data):
        """Backup blocks were retired. A saved backup block stays only if it was switched on, as an ordinary study block."""
        if isinstance(data,dict) and ('use_backup' in data or any(isinstance(b,dict) and 'kind' in b for b in data.get('blocks') or [])):
            data=dict(data);enabled=bool(data.pop('use_backup',False))
            data['blocks']=[{k:v for k,v in b.items() if k!='kind'} if isinstance(b,dict) else b for b in data.get('blocks') or []
                if not isinstance(b,dict) or b.get('kind','preferred')!='backup' or enabled]
        return data
    @model_validator(mode='after')
    def coherent(self):
        if self.overflow_start>=self.overflow_end:raise ValueError('Extra time must end after it starts on the same day.')
        try:ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Choose a valid planning time zone.') from None
        if len(set(self.learning_focus))!=len(self.learning_focus):raise ValueError('Choose each learning focus once.')
        if any(period.end_date<period.start_date for period in self.reduced_periods):raise ValueError('A reduced-availability period ends before it starts.')
        return self

class PatchBlock(Contract):
    day:int
    start_time:str
    duration_minutes:int
    kind:str|None=Field(default=None,description='Retired. Accepted so an older reply still applies; a backup block is ignored.')
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
    blackouts:list[PatchBlackout]|None=None
    preferred_session_minutes:int|None=None
    break_minutes_per_hour:int|None=None
    plan_day:int|None=None
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
class DraftCheckpoint(Contract):
    """A dated, observable check inside a milestone. The last one completes the milestone."""
    key:Key
    title:Title
    date:date
class DraftMilestone(Contract):
    key:Key
    title:Title
    gap_ids:list[Key]=Field(default_factory=list,max_length=20)
    prerequisite_keys:list[Key]=Field(default_factory=list,max_length=16)
    estimated_minutes:int=Field(strict=True,ge=0,le=60000)
    projected_start:date
    projected_end:date
    demonstrable_outcome:Text
    checkpoints:list[DraftCheckpoint]=Field(default_factory=list,max_length=8)
class DraftAssignment(Contract):
    key:Key
    milestone_key:Key
    title:Title=Field(description='A short, actionable name for the to-do list, at most 80 characters.')
    gap_id:str|None=Field(default=None,max_length=80)
    gap_ids:list[Key]=Field(default_factory=list,max_length=6,description='Every listed gap this session practises.')
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
    fits_in_runway:bool=Field(default=True,description='Set by elo: false exactly when beyond_deadline lists work. A value sent in a draft is replaced.')
class DraftExclusion(Contract):
    requirement_ref:Key
    reason:Text
    quote:Text
class RoutineRule(Contract):
    id:Key
    revision:int=Field(default=1,strict=True,ge=1)
    milestone_key:Key
    activity:Text
    weekdays:list[Annotated[int,Field(strict=True,ge=0,le=6)]]=Field(min_length=1,max_length=7)
    duration_minutes:int=Field(strict=True,ge=1,le=480)
    topic_progression:list[Text]=Field(default_factory=list,max_length=31)
    difficulty:str=Field(default='',max_length=160)
    start_date:date
    end_date:date
    user_wording:str=Field(default='',max_length=1000)
    @model_validator(mode='after')
    def coherent(self):
        if self.start_date>self.end_date:raise ValueError('Routine end date must not precede its start date.')
        if len(set(self.weekdays))!=len(self.weekdays):raise ValueError('Choose each weekday once.')
        return self

class WeekObjective(Contract):
    """What one week of the roadmap is for. A projection until that week's tasks are generated and accepted."""
    week_start:date
    objective:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=400)]
    expected_outcome:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=400)]
    estimated_minutes:int=Field(strict=True,ge=0,le=10080)
    milestone_key:Key
    gap_ids:list[Key]=Field(default_factory=list,max_length=8)

class OutlineDraft(Contract):
    summary:Text
    gaps:list[DraftGap]=Field(default_factory=list,max_length=40)
    milestones:list[DraftMilestone]=Field(default_factory=list,max_length=16)
    weeks:list[WeekObjective]=Field(default_factory=list,max_length=54)
    routine_rules:list[RoutineRule]=Field(default_factory=list,max_length=20)
    deadline_outcome:DeadlineOutcome
    beyond_deadline:list[DraftBeyond]=Field(default_factory=list,max_length=20)
    exclusions:list[DraftExclusion]=Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def derived_deadline_fit(self):
        self.deadline_outcome.fits_in_runway=not self.beyond_deadline
        return self
    @model_validator(mode='after')
    def bounded_payload(self):
        if len(json.dumps(self.model_dump(mode='json'),ensure_ascii=True,separators=(',',':')).encode())>48*1024:
            raise ValueError('The outline is too large; shorten its details before saving.')
        return self

class RunwayRequest(Contract):
    config:PlannerConfig
class SaveConfig(Mutation):
    config:PlannerConfig
class GeneratePlan(Mutation):
    allow_partial_assessment:bool=Field(default=False,deprecated=True,description='Ignored. Saved evaluations are reused only when current; kept so saved retry requests stay readable.')
    auto_accept:bool=Field(default=False,description='Activate the roadmap and first week in the generation operation, without a separate review.')
class ConfirmEvidence(Mutation):
    expected_declarations_version:int=Field(ge=0)
    proposal_hash:str=Field(min_length=64,max_length=64)
class EvidenceProposal(Contract):
    """A completed session's note offered to the user as Skills Profile evidence. Nothing is written until confirmed."""
    id:str
    session_id:str
    name:str
    description:str
    proposal_hash:str
class EvidenceProposals(Contract):
    version:int
    declarations_version:int
    items:list[EvidenceProposal]
class AssignmentStatus(Mutation):
    assignment_id:str=Field(min_length=1,max_length=80)
    status:Literal['scheduled','completed']
    evidence_note:str|None=Field(default=None,max_length=2000)
class CheckpointReached(Mutation):
    milestone_id:str=Field(min_length=1,max_length=80)
    checkpoint_key:Key
    reached:bool
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
    overflow_minutes:int
    usable_minutes:int
    partial:bool
    reduced:bool=False
class RunwayCalendar(Contract):
    days:int
    weeks:int
    extra_days:int
    label:str
    partial_first_week:bool
class RunwayStudy(Contract):
    preferred_minutes:int
    overflow_minutes:int
    usable_minutes:int
class RunwayResolved(Contract):
    today:str
    start_date:str
    target_date:str|None
    matched_duration:Duration|None
class RunwayWindow(Contract):
    """One free study window on a date: inside study blocks (preferred) or extra time (overflow)."""
    date:str
    start_time:str
    end_time:str
    kind:Literal['preferred','overflow']
    minutes:int
class Runway(Contract):
    windows:list[RunwayWindow]=Field(default_factory=list,max_length=10000)
    can_generate:bool
    issues:list[RunwayIssue]
    notices:list[RunwayIssue]=Field(default_factory=list,description='Explanations that do not block generation, such as study times that hold less than the weekly hours.')
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
    clamped_milestones:list[str]|None=Field(default=None,description='Milestones whose generated start was before the planning start and was moved up to it.')
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
class PlanCheckpoint(DraftCheckpoint):
    reached_at:str|None=None
class PlanMilestone(DraftMilestone):
    model_config=ConfigDict(extra='forbid')
    id:str
    outcome:MilestoneOutcomeRecord
    checkpoints:list[PlanCheckpoint]=Field(default_factory=list)
class PlanAssignment(DraftAssignment):
    model_config=ConfigDict(extra='forbid')
    id:str
    title:str|None=Field(default=None,description='The short to-do name; null on sessions saved before names existed.')
    skill_gap_ids:list[str]|None=Field(default=None,description='Exactly one known skill gap, or an empty list when no unambiguous link is available. Null indicates a legacy assignment without a projected link.')
    status:Literal['scheduled','completed']
    completed_at:str|None=None
    evidence_note:str|None=None
    history:list[AssignmentChange]=Field(default_factory=list)
    task_id:str|None=Field(default=None,description='The editable task this session is a slot of; null on sessions saved before tasks existed.')
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
class SessionOriginal(Contract):
    title:str
    completion_criterion:str
class SessionView(Contract):
    """One to-do row: a scheduled slot, or an anytime day, of a current task."""
    id:str
    task_id:str
    title:str
    instructions:str
    description:Text|None=Field(default=None,description='Detailed task steps and completion guidance; null for older tasks.')
    completion_criterion:str
    date:str
    start_time:str|None=Field(description='Null when the task can be done at any time that day.')
    duration_minutes:int
    status:Literal['scheduled','completed']
    completed_at:str|None=None
    missed:bool=Field(description='Not done and its day has passed, so it waits in the backlog.')
    origin:Literal['generated','user']
    kind:Literal['study','diagnostic']='study'
    milestone_key:str|None=None
    skills:list[TaskSkill]=Field(default_factory=list)
    edited:bool=Field(default=False,description='The name or completion criterion differs from the generated wording.')
    original:SessionOriginal|None=None
    notes:NotesDocument|None=None
    confidence:int|None=Field(default=None,description='Self-reported, 1 to 10. Never used for skill scores.')
    difficulty:int|None=Field(default=None,description='Self-reported, 1 to 10. Never used for skill scores.')
    rated_at:str|None=None
    moved_from_backlog:bool=False
    slots:int=1
class DashboardSource(Contract):
    version:int
    active:PlannedRoadmap|None
    active_review:PlanReview|None
    task_readiness:dict[str,TaskReadiness]
class Signal(Contract):
    kind:Literal['settings','evidence','progress']
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
class SavedWeekObjective(WeekObjective):
    model_config=ConfigDict(extra='allow')
    revised_reason:str|None=None
class OmittedOutlineItem(Contract):
    kind:Literal['gap','milestone','week','routine','exclusion','beyond_deadline']
    id:str
    title:str
    reason:str
    requirement_ref:str|None=None
class PartialOutlineReview(Contract):
    """Backend-recorded omissions after two outline attempts; shown before explicit acceptance."""
    omitted_items:list[OmittedOutlineItem]
    uncovered_requirements:list[str]=Field(default_factory=list)
class SavedOutline(SavedRecord):
    partial_review:PartialOutlineReview|None=None
    id:str
    revision:int
    status:Literal['preview','accepted']
    assessment_id:str
    assessment_hash:str
    assessment:dict
    config:PlannerConfig
    config_hash:str
    confirmations_hash:str
    base_active_id:str|None
    base_progress_hash:str
    created_at:str
    accepted_at:str|None=None
    first_planning_week:str
    summary:str
    gaps:list[DraftGap]
    milestones:list[PlanMilestone]
    weeks:list[SavedWeekObjective]=Field(default_factory=list)
    routine_rules:list[RoutineRule]
    deadline_outcome:DeadlineOutcome
    beyond_deadline:list[DraftBeyond]
    exclusions:list[DraftExclusion]
    generation:PlanGeneration
    first_week_error:str|None=Field(default=None,description='Why the first week could not be prepared with this outline. The outline can still be accepted.')
class SavedMonth(SavedRecord):
    """A calendar month accepted before weekly planning. Read-only: its weeks count as planned."""
    id:str
    month:str
    status:Literal['preview','accepted']
    start_date:str
    end_exclusive:str
    task_ids:list[str]|None=None
class WeekTarget(SavedRecord):
    """How much study the week should hold and why it differs from the agreed weekly hours."""
    week_start:str
    weekly_minutes:int
    target_minutes:int
    shortfall_minutes:int=0
    reasons:list[RunwayIssue]=Field(default_factory=list)
class CarryoverEntry(SavedRecord):
    """One unfinished task and what the preview does with it. Nothing changes until the week is accepted."""
    task_id:str
    title:str
    milestone_key:str|None=None
    status:Literal['not_started','in_progress']
    estimated_minutes:int
    action:Literal['carry','split','defer','drop']
    proposed_action:Literal['carry','split','defer','drop']
    minutes:int|None=None
    reason:str
    adjusted:bool=Field(default=False,description='The service changed the proposal because the work could not be placed or exceeded the carry-over limit.')
    schedule:list[SavedTaskSlot]=Field(default_factory=list)
    previous_schedule:list[SavedTaskSlot]=Field(default_factory=list)
class ObjectiveRevision(SavedWeekObjective):
    reason:str
    previous:SavedWeekObjective|None=None
class WeekFeedback(Contract):
    """Optional, self-reported. It shapes the next week and never changes assessed skills."""
    workload:Literal['too_much','about_right','too_light']|None=None
    difficulty:Literal['too_hard','about_right','too_easy']|None=None
    note:str=Field(default='',max_length=500)

class SavedWeek(SavedRecord):
    id:str
    week_start:str
    status:Literal['preview','accepted']
    outline_id:str
    outline_revision:int
    start_date:str
    end_exclusive:str
    time_zone:str
    created_at:str
    accepted_at:str|None=None
    summary:str=''
    feedback:WeekFeedback|None=None
    target:WeekTarget|None=None
    tasks:list[EditableTask]|None=None
    unplaced:list[EditableTask]=Field(default_factory=list,description='New tasks left out because a carry-over choice used their time.')
    task_ids:list[str]|None=None
    carryover:list[CarryoverEntry]=Field(default_factory=list)
    objective_changes:list[ObjectiveRevision]=Field(default_factory=list)
    revision:int=1
    replaces_block_id:str|None=None
    replaced_task_ids:list[str]|None=None
    generation:PlanGeneration
class RetryWeek(Mutation):
    week_start:date
    revision:bool=False
    feedback:WeekFeedback|None=None
class WeekPlanning(Contract):
    """Which week can be planned now. `available` is false while next week is still waiting for the planning day."""
    current_week_start:str
    plan_day:str
    week_done:bool
    action:Literal['plan_this','plan_next','review']|None
    week_start:str|None
    available:bool
    reason:Literal['week_unplanned','week_done','plan_day','waiting','preview_ready']|None
    unfinished_count:int=0
    notice:str|None=None
class WeekOverview(SavedWeekObjective):
    """One week of the journey: its objective, and whether its tasks exist yet."""
    start_date:str
    end_date:str
    status:Literal['past','planned','open','projected']
    tasks_total:int=0
    tasks_completed:int=0
    planned_minutes:int=0

class PlannerView(Contract):
    config:PlannerConfig
    config_saved:bool
    runway:Runway
    inputs:PlanInputs
    active:PlannedRoadmap|None
    active_review:PlanReview|None
    task_warnings:list[TaskWarning]=Field(default_factory=list)
    active_sessions:list[SessionView]=Field(default_factory=list)
    preview_sessions:list[SessionView]=Field(default_factory=list,description='The week preview as to-do rows: new tasks and carried work at their proposed times.')
    outline_candidate:SavedOutline|None=None
    outline_active:SavedOutline|None=None
    week_candidate:SavedWeek|None=None
    week_blocks:list[SavedWeek]=Field(default_factory=list)
    month_blocks:list[SavedMonth]=Field(default_factory=list)
    weeks:list[WeekOverview]=Field(default_factory=list)
    week_planning:WeekPlanning|None=None
    retry_outline:GeneratePlan|None=None
    retry_week:RetryWeek|None=None
    confirmations:dict[str,ConfirmationRecord]
    signals:list[Signal]
    outline_generated:bool=Field(default=False,description='Whether this workspace has ever generated a roadmap outline, including discarded or replaced ones.')

class SessionChanges(Contract):
    """Only the fields sent are changed. A null start_time makes the task anytime on its day."""
    title:TaskTitle|None=None
    completion_criterion:Text|None=None
    skills:list[Title]|None=Field(default=None,max_length=8)
    date:Day|None=None
    start_time:Clock|None=None
    duration_minutes:int|None=Field(default=None,strict=True,ge=5,le=480)
    notes:NotesDocument|None=None
    confidence:int|None=Field(default=None,strict=True,ge=1,le=10)
    difficulty:int|None=Field(default=None,strict=True,ge=1,le=10)
    restore_original:bool|None=None
class SaveSession(Mutation):
    session_id:str=Field(min_length=1,max_length=80)
    changes:SessionChanges
    allow_overlap:bool=False
class NewSession(Contract):
    title:TaskTitle
    completion_criterion:str=Field(default='',max_length=4000)
    skills:list[Title]=Field(default_factory=list,max_length=8)
    date:date
    start_time:Clock|None=None
    duration_minutes:int=Field(strict=True,ge=5,le=480)
    notes:NotesDocument|None=None
class AddSession(Mutation):
    session:NewSession
    allow_overlap:bool=False
class SessionMove(Contract):
    session_id:str=Field(min_length=1,max_length=80)
    date:date
    start_time:Clock
class MoveSessions(Mutation):
    moves:list[SessionMove]=Field(min_length=1,max_length=50)
class SkipSession(Mutation):
    session_id:str=Field(min_length=1,max_length=80)
class FreeTimesRequest(Contract):
    duration_minutes:int=Field(strict=True,ge=5,le=480)
    session_id:str|None=Field(default=None,max_length=80)
class FreeDay(Contract):
    date:str
    rest_day:bool
    kind:Literal['study','after_block','rest_day','none']
    starts:list[str]
class FreeTimes(Contract):
    version:int
    today:str
    days:list[FreeDay]
class BacklogPlanRequest(Contract):
    session_ids:list[Annotated[str,StringConstraints(min_length=1,max_length=80)]]|None=Field(default=None,max_length=50)
class BacklogProposal(Contract):
    session_id:str
    title:str
    duration_minutes:int
    date:str|None
    start_time:str|None
class BacklogPlan(Contract):
    version:int
    moves:list[BacklogProposal]

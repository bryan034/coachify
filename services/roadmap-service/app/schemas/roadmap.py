"""Contracts for the timed roadmap: confirmed settings, model output and saved plans."""
from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import ConfigDict, Field, StringConstraints, model_validator
from .base import Contract, Mutation, Text

Clock=Annotated[str,StringConstraints(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
Key=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=80)]
Title=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
Day=date
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
    buffer_percent:int=Field(default=20,strict=True,ge=0,le=50)
    checkin_day:int=Field(default=4,strict=True,ge=0,le=6)
    checkin_time:Clock='18:00'
    @model_validator(mode='before')
    @classmethod
    def upgrade_saved_blackout_dates(cls,values):
        """Saved settings and plans from before blackout rules keep their dates as one-off rules."""
        if not isinstance(values,dict) or 'blackout_dates' not in values:return values
        upgraded={k:v for k,v in values.items() if k!='blackout_dates'}
        upgraded.setdefault('blackouts',[{'frequency':'once','start_date':day} for day in values['blackout_dates']])
        return upgraded
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
    buffer_percent:int|None=None
    checkin_day:int|None=None
    checkin_time:str|None=None
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
    depends_on:list[Key]=Field(default_factory=list,max_length=8)
    refresher_reason:str|None=Field(default=None,max_length=500)
class DraftBeyond(Contract):
    title:Title
    gap_ids:list[Key]=Field(default_factory=list,max_length=20)
    reason:Text
    estimated_minutes:int=Field(strict=True,ge=0,le=60000)
    key:Key|None=None
    dependencies:list[Key]=Field(default_factory=list,max_length=16)
class DraftWeek(Contract):
    week_start:date
    theme:Title
    milestone_keys:list[Key]=Field(default_factory=list,max_length=16)
    target_minutes:int=Field(strict=True,ge=0,le=10080)
    expected_output:Text
class DeadlineOutcome(Contract):
    summary:Text
    achievable_by_target:list[Text]=Field(default_factory=list,max_length=20)
    fits_in_runway:bool
class DraftExclusion(Contract):
    requirement_ref:Key
    reason:Text
    quote:Text
class PlanOutline(Contract):
    """First generation stage: scope, order and one row per week through the target date."""
    summary:Text
    gaps:list[DraftGap]=Field(default_factory=list,max_length=40)
    milestones:list[DraftMilestone]=Field(default_factory=list,max_length=24)
    outline:list[DraftWeek]=Field(default_factory=list,max_length=54)
    deadline_outcome:DeadlineOutcome
    beyond_deadline:list[DraftBeyond]=Field(default_factory=list,max_length=20)
    exclusions:list[DraftExclusion]=Field(default_factory=list,max_length=20)
class WindowDetail(Contract):
    """Second generation stage, also used for rolling detail: dated tasks for the requested weeks."""
    assignments:list[DraftAssignment]=Field(default_factory=list,max_length=40)
class TaskRevision(WindowDetail):
    """A check-in or chat revision: replacement tasks for the requested weeks, with a short explanation."""
    message:Text
class PlanDraft(PlanOutline):
    """Both stages together, which is what the final validation pass checks."""
    assignments:list[DraftAssignment]=Field(default_factory=list,max_length=80)

class RunwayRequest(Contract):
    config:PlannerConfig
class SaveConfig(Mutation):
    config:PlannerConfig
class GeneratePlan(Mutation):
    allow_partial_assessment:bool=False
Feedback=Literal['too_easy','about_right','too_hard']
class AssignmentStatus(Mutation):
    assignment_id:str=Field(min_length=1,max_length=80)
    status:Literal['scheduled','completed']
    evidence_note:str|None=Field(default=None,max_length=2000)
    feedback:Feedback|None=None
class TaskReference(Mutation):
    task_id:str=Field(min_length=1,max_length=80)
class MoveTask(TaskReference):
    date:date
    start_time:Clock
    confirm_outside_blocks:bool=False
class UpdateTask(TaskReference):
    """Only the fields present are changed; send an empty note to clear it."""
    pinned:bool|None=None
    note:str|None=Field(default=None,max_length=2000)
    feedback:Feedback|None=None
    count_hours:bool|None=None
class CustomTask(Mutation):
    title:Title
    duration_minutes:int=Field(strict=True,ge=5,le=480)
    week_start:Day
    date:Day|None=None
    start_time:Clock|None=None
    note:str|None=Field(default=None,max_length=2000)
    milestone_key:Key|None=None
    count_hours:bool=True
    confirm_outside_blocks:bool=False
    @model_validator(mode='after')
    def placed_together(self):
        if (self.date is None)!=(self.start_time is None):raise ValueError('Choose both a date and a time, or neither.')
        return self
class UndoEvent(Mutation):
    event_id:str=Field(min_length=1,max_length=200)
class CompleteMilestone(Mutation):
    milestone_id:str=Field(min_length=1,max_length=80)
    completed:bool=True
    unfinished:Literal['keep','remove']|None=None
class CheckinAnswer(Mutation):
    week_start:date
    week_feel:Literal['busier','as_expected','freer']
    next_week:Literal['more','same','less']
    note:str|None=Field(default=None,max_length=1000)
class CheckinPropose(Mutation):
    week_start:date
class RollDetail(Mutation):
    weeks:list[date]=Field(default_factory=list,max_length=2)
class PauseWeek(Mutation):
    week_start:date
class PaceAction(Mutation):
    action:Literal['cut_scope','add_hours','move_date']
    extra_minutes:int|None=Field(default=None,strict=True,ge=5,le=10080)
    target_date:date|None=None
class EditPlan(Mutation):
    config:PlannerConfig
class BringDeferred(Mutation):
    deferred_id:str=Field(min_length=1,max_length=120)
    target_date:date|None=None
class AcceptProposal(Mutation):
    proposal_id:str=Field(min_length=1,max_length=80)
    keep_task_ids:list[str]=Field(default_factory=list,max_length=200)
class DiscardProposal(Mutation):
    proposal_id:str=Field(min_length=1,max_length=80)
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
    planned_minutes:int
    buffer_minutes:int
    paused:bool=False
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
class RunwayBudget(Contract):
    available_weeks:int
    eligible_minutes:int
    planned_minutes:int
    buffer_minutes:int
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
    budget:RunwayBudget
    weeks:list[RunwayWeek]
    first_planning_week:str|None
class PlanGap(DraftGap):
    pass
class LegacyMilestone(DraftMilestone):
    model_config=ConfigDict(extra='forbid')
    id:str
    outcome:dict
class LegacyAssignment(Contract):
    key:Key
    milestone_key:Key
    gap_id:str|None=Field(default=None,max_length=80)
    kind:Literal['study','diagnostic']='study'
    date:date
    start_time:Clock
    duration_minutes:int=Field(strict=True,ge=1,le=480)
    task:Text
    completion_criterion:Text
    id:str
    status:Literal['scheduled','completed']
    completed_at:str|None=None
    evidence_note:str|None=None
    history:list[dict]=Field(default_factory=list)
class LegacyBeyond(Contract):
    title:Title
    gap_ids:list[Key]=Field(default_factory=list,max_length=20)
    reason:Text
    estimated_minutes:int=Field(strict=True,ge=0,le=60000)
class LegacyRoadmap(Contract):
    """A roadmap-v2 plan. It stays readable and is never changed by roadmap-v3 mutations."""
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
    created_at:str
    first_planning_week:str
    summary:str
    gaps:list[PlanGap]
    milestones:list[LegacyMilestone]
    assignments:list[LegacyAssignment]
    deadline_outcome:DeadlineOutcome
    beyond_deadline:list[LegacyBeyond]
    exclusions:list[DraftExclusion]
    changes:dict|None=None
    generation:dict

class PlanMilestone(DraftMilestone):
    model_config=ConfigDict(extra='forbid')
    id:str
    outcome:dict
    completion:dict|None=None
class PlanAssignment(Contract):
    """A generated or custom task. status scheduled has a placement; backlog has only a week preference."""
    id:str
    key:Key
    origin:Literal['generated','custom']='generated'
    kind:Literal['study','diagnostic','custom']='study'
    milestone_key:str|None=None
    gap_id:str|None=None
    task:Text
    completion_criterion:str|None=None
    depends_on:list[str]=Field(default_factory=list)
    refresher_reason:str|None=None
    week_start:str
    date:Day|None=None
    start_time:Clock|None=None
    duration_minutes:int=Field(strict=True,ge=1,le=480)
    status:Literal['scheduled','backlog','completed','skipped','removed']='scheduled'
    pinned:bool=False
    count_hours:bool=True
    note:str|None=None
    evidence_note:str|None=None
    feedback:Feedback|None=None
    completed_at:str|None=None
    auto_moves:int=0
    manual_moves:int=0
    action_needed:dict|None=None
    backlog_reason:str|None=None
    removed_reason:str|None=None
    baseline:str|None=None
    revision:int=0
    history:list[dict]=Field(default_factory=list)
class OutlineWeek(Contract):
    week_start:str
    theme:str
    milestone_keys:list[str]=Field(default_factory=list)
    target_minutes:int
    expected_output:str
class DeferredItem(Contract):
    """Work beyond the target date. It stays outside the dated schedule until a scope or date change is accepted."""
    id:str
    key:str
    title:str
    gap_ids:list[str]=Field(default_factory=list)
    reason:str
    estimated_minutes:int
    dependencies:list[str]=Field(default_factory=list)
    source_milestone:dict|None=None
class WeekState(Contract):
    paused:bool=False
    exception_task_ids:list[str]=Field(default_factory=list)
    workload_minutes:int|None=None
    workload_source:str|None=None
class PlanEvent(Contract):
    id:str
    type:Literal['auto_move','auto_backlog','undo','manual_move','skip','restore','complete','reopen','custom_added','detail_added','milestone_completed','milestone_reopened','pause','unpause','plan_edit','scope_change','checkin_applied','revision_applied']
    at:str
    task_id:str|None=None
    message:str
    undo:dict|None=None
    undone:bool=False
class PlannedRoadmap(Contract):
    """A roadmap-v3 plan: an outline through the target date, a rolling two-week detail window and deferred scope."""
    model_config=ConfigDict(extra='allow')
    schema_version:Literal['roadmap-v3']
    id:str
    revision:int=0
    progress_revision:int=0
    assessment_id:str
    assessment_hash:str
    assessment:dict
    config:PlannerConfig
    config_hash:str
    confirmations_hash:str
    base_active_id:str|None
    base_progress_revision:int|None=None
    created_at:str
    accepted_at:str|None=None
    first_planning_week:str
    summary:str
    gaps:list[PlanGap]
    milestones:list[PlanMilestone]
    outline:list[OutlineWeek]
    assignments:list[PlanAssignment]
    deferred_scope:list[DeferredItem]
    deadline_outcome:DeadlineOutcome
    exclusions:list[DraftExclusion]
    week_states:dict[str,WeekState]=Field(default_factory=dict)
    checkins:dict[str,dict]=Field(default_factory=dict)
    events:list[PlanEvent]=Field(default_factory=list)
    changes:dict|None=None
    generation:dict
class PlanReview(Contract):
    next_assignment_id:str|None
    missed_assignment_ids:list[str]
    remaining:Runway
    milestones:dict[str,dict]
class Signal(Contract):
    kind:Literal['settings','evidence','progress','next_week']
    message:str
class PlanInputs(Contract):
    goal:dict|None
    cv:dict|None
    skills:list[dict]
    experience:list[dict]
    skill_groups:dict[str,str]

class ProgressCount(Contract):
    completed:int
    planned:int
class ProgressView(Contract):
    label:Literal['Roadmap progress']='Roadmap progress'
    roadmap_minutes:ProgressCount
    generated_tasks:ProgressCount
    milestones:ProgressCount
    custom_scheduled_minutes:int
    custom_excluded_minutes:int
    custom_linked_completed_minutes:int
    remaining_minutes:int
class RecentPace(Contract):
    status:Literal['available','insufficient_data','no_estimate']
    weeks_used:int
    weekly_minutes:int|None=None
    finish_date:str|None=None
    weeks_late:int|None=None
class PaceView(Contract):
    status:Literal['on_track','behind','insufficient_data']
    completed_minutes:int
    expected_minutes:int
    behind_minutes:int
    recent:RecentPace
class ProjectionView(Contract):
    target_date:str
    scheduled_finish:str|None
    projected_finish:str|None
    remaining_active_minutes:int
    deferred_minutes:int
    fits_target:bool
    assumption:str
class WeekView(Contract):
    week_start:str
    state:Literal['past','current','next','later']
    theme:str|None
    expected_output:str|None
    milestone_keys:list[str]
    target_minutes:int
    eligible_minutes:int
    planned_minutes:int
    buffer_minutes:int
    scheduled_minutes:int
    completed_minutes:int
    paused:bool
    exception_task_ids:list[str]
    workload_source:str|None
    task_ids:list[str]
    contains_target:bool
class SuggestedSlot(Contract):
    date:str
    start_time:str
class BacklogView(Contract):
    task_id:str
    reason:str
    week_start:str
    suggested_slot:SuggestedSlot|None
class CheckinRecap(Contract):
    planned_minutes:int
    completed_minutes:int
    remaining_minutes:int
    due_minutes:int
    completed_due_minutes:int
    moved:list[str]
    skipped:list[str]
    suggest_less:bool
class CheckinView(Contract):
    week_start:str
    status:Literal['open','answered','proposed']
    opens_at:str
    expires_at:str
    recap:CheckinRecap
    answers:dict|None=None
    next_week:str
    next_week_target_minutes:int
class CoachView(Contract):
    messages:list[str]
    action_needed_task_ids:list[str]
    recent_moves:list[PlanEvent]
    notices:list[str]
class RollingView(Contract):
    status:Literal['idle','needed','running','failed','unavailable']
    weeks:list[str]
    error:str|None=None
    retry_after:int|None=None
class ActiveView(Contract):
    today:str
    current_week:str
    next_week:str|None
    next_task_id:str|None
    today_task_ids:list[str]
    this_week:ProgressCount
    progress:ProgressView
    pace:PaceView
    projection:ProjectionView
    weeks:list[WeekView]
    backlog:list[BacklogView]
    checkin:CheckinView|None
    coach:CoachView
    rolling:RollingView
    skipped_task_ids:list[str]
class CandidateView(Contract):
    progress:ProgressView
    projection:ProjectionView
    weeks:list[WeekView]
class ProposalEffect(Contract):
    summary:str
    finish_before:str|None
    finish_after:str|None
    target_before:str
    target_after:str
    capacity_before_minutes:int
    capacity_after_minutes:int
    tasks_moved:list[str]=Field(default_factory=list)
    tasks_backlogged:list[str]=Field(default_factory=list)
    tasks_added:list[str]=Field(default_factory=list)
    tasks_removed:list[str]=Field(default_factory=list)
    decisions:list[dict]=Field(default_factory=list)
    warnings:list[str]=Field(default_factory=list)
    week_start:str|None=None
    workload_before_minutes:int|None=None
    workload_after_minutes:int|None=None
    uses_buffer:bool=False
    add_block_suggested:bool=False
class Proposal(Contract):
    id:str
    kind:Literal['pause','unpause','pace_cut_scope','pace_add_hours','pace_move_date','edit','scope','checkin','revision']
    base_revision:int
    created_at:str
    message:str|None=None
    week_start:str|None=None
    effect:ProposalEffect
    patch:dict
class ArchivedRoadmap(Contract):
    id:str
    schema_version:str
    role:str|None
    summary:str
    start_date:str|None
    target_date:str|None
    archived_at:str
    completed_minutes:int
    planned_minutes:int
    tasks_completed:int
    tasks_total:int
    milestones_completed:int
    milestones_total:int
class RoadmapSummary(Contract):
    """Reusable progress for other screens. It reads saved state and changes nothing."""
    has_active:bool
    schema_version:str|None=None
    role:str|None=None
    target_date:str|None=None
    current_week:str|None=None
    next_task:dict|None=None
    progress:ProgressView|None=None
    pace:PaceView|None=None
    projection:ProjectionView|None=None
class PlannerView(Contract):
    config:PlannerConfig
    config_saved:bool
    runway:Runway
    inputs:PlanInputs
    candidate:PlannedRoadmap|None
    candidate_review:PlanReview|None
    candidate_view:CandidateView|None=None
    candidate_blockers:list[RunwayIssue]
    active:PlannedRoadmap|LegacyRoadmap|None
    active_review:PlanReview|None
    active_view:ActiveView|None=None
    proposal:Proposal|None=None
    proposal_blockers:list[RunwayIssue]=Field(default_factory=list)
    archived:list[ArchivedRoadmap]=Field(default_factory=list)
    confirmations:dict[str,dict]
    signals:list[Signal]
    retry_generate:dict|None=None
    retry_checkin:dict|None=None

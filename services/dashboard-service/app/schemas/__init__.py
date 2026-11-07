"""Response contract for a read-only dashboard."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid')

class SourceState(Contract):
    state:Literal['available','current','stale','missing','unavailable','not_ready','conflict','mismatch']
    version:int|None=None
    id:str|None=None
    input_hash:str|None=None
    current_input_hash:str|None=None
    input_versions:dict|None=None
    updated_at:str|None=None
    created_at:str|None=None
    workspace_updated_at:str|None=None
    roadmap_match:Literal['matched','different','unknown']|None=None
    analysis_status:str|None=None
    research_coverage:str|None=None
    operation:dict|None=None

class Period(Contract):
    kind:Literal['daily','weekly','monthly','whole']
    focus_date:str|None
    start_date:str|None
    end_date:str|None
    time_zone:str|None

class Counts(Contract):
    total:int
    completed:int
    in_progress:int
    not_started:int
    completion_review:int
    completion_ratio:float|None
    remaining_estimated_minutes:int

class TaskReadiness(Contract):
    actionable:bool
    reasons:list[dict]

class TaskSummary(Contract):
    id:str
    title:str
    status:Literal['not_started','in_progress','completed']
    estimated_minutes:int
    schedule:list[dict]
    unscheduled_minutes:int
    definition_review_required:bool
    readiness:TaskReadiness|None

class TaskProgress(Contract):
    overall:Counts
    selected:Counts
    selected_task_ids:list[str]
    planned_minutes:int
    unscheduled_minutes:int
    remaining_unscheduled_minutes:int
    unscheduled_task_ids:list[str]
    removed_task_ids:list[str]
    tasks:list[TaskSummary]

class Milestone(Contract):
    id:str
    title:str
    outcome:dict
    progress:dict
    blocked_task_ids:list[str]
    blocked_reasons:list[dict]
    review_reasons:list[dict]

class Requirement(Contract):
    ref:str
    name:str|None
    kind:str|None
    match_status:str|None
    components:list[dict]
    linked_task_ids:list[str]

class Requirements(Contract):
    state:Literal['current','stale','missing','unavailable','not_ready','conflict','mismatch']
    items:list[Requirement]
    groups:list[dict]
    unlinked_task_ids:list[str]
    stale_link_task_ids:list[str]

class PaceItem(Contract):
    task_id:str
    planned_date:str
    planned_dates:list[str]
    classification:Literal['upcoming','overdue','completed_early','completed_on_time','completed_late','removed','changed','non_comparable']
    completed_at:str|None=None
    reason:str|None=None

class Pace(Contract):
    state:Literal['available','unavailable','empty']
    baseline_id:str|None=None
    baseline_created_at:str|None=None
    baseline_updated_at:str|None=None
    as_of:str
    items:list[PaceItem]=Field(default_factory=list)
    unscheduled_task_ids:list[str]=Field(default_factory=list)
    added_task_ids:list[str]=Field(default_factory=list)
    historical_added_scope_unknown:bool=False
    planned_minutes:int|None=None
    note:str

class Dashboard(Contract):
    state:Literal['available','empty','no_plan','unavailable','conflict']
    period:Period
    roadmap:SourceState
    assessment:SourceState
    progress:TaskProgress|None
    milestones:list[Milestone]
    requirements:Requirements
    pace:Pace
    warnings:list[str]=Field(default_factory=list)

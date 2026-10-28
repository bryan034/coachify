"""Public single-workspace response: structured state, never raw source/chat."""
from datetime import datetime
from typing import Literal
from app.schemas.providers import ResearchProvider
from pydantic import Field
from app.schemas.analysis import Contract,CareerGoal,DomainId,ResearchCoverage,Version
from app.schemas.jd import JDReply

class ReviewReference(Contract):
    id:DomainId
    version:Version

class CurrentCareerGoal(Contract):
    selection_version:int=Field(ge=0)
    goal:CareerGoal|None
    dependent_results_need_review:bool=False
    review_selection:ReviewReference|None=None

class WorkspaceView(Contract):
    session_id:DomainId|None
    revision:int=Field(ge=0)
    kind:Literal['jd','exploration']|None
    phase:Literal['empty','exploring','research_pending','researching','waiting_quota','research_failed','ready','expired']
    current:CurrentCareerGoal
    research_id:DomainId|None=None
    research_version:int|None=None
    activities:list[str]=Field(default_factory=list,max_length=12)
    coverage:list[ResearchCoverage]=Field(default_factory=list,max_length=6)
    edit_question:str|None=Field(default=None,max_length=600)
    error_code:str|None=Field(default=None,max_length=80)
    error:str|None=Field(default=None,max_length=1000)
    limit_scope:Literal['provider','user']|None=None
    provider:ResearchProvider=None
    retry_after:int|None=Field(default=None,ge=0)
    expires_at:datetime|None
    exploration_id:DomainId|None


class OperationView(Contract):
    activities:list[str]=Field(default_factory=list,max_length=12)
    operation_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    status: Literal['running', 'repairing', 'waiting_quota', 'succeeded']
    limit_scope:Literal['provider','user']|None=None
    provider:ResearchProvider=None
    retry_after: int | None = Field(default=None, ge=0)
    result: dict | None = None
    validation_feedback: dict | None = None


class OperationError(Contract):
    operation_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    code:str
    detail:str
    diagnostic:dict|None=None
    provider_error:dict|None=None
    retry_after:int|None=None
    limit_scope:Literal['provider','user']|None=None


class WorkspaceChatReply(JDReply):
    edit_status:Literal['clarifying','saved','cancelled']|None=None
    workspace:WorkspaceView|None=None

class CategoryProgress(Contract):
    status:Literal['pending','running','completed','partial','failed','not_applicable']
    error_code:str|None=None

class WorkspaceProgress(Contract):
    session_id:DomainId|None
    phase:str
    revision:int
    goal_id:DomainId|None
    selection_version:int
    activities:list[str]
    categories:dict[str,CategoryProgress]
    research_id:DomainId|None
    result_version:datetime|None
    error:str|None
    error_code:str|None
    retry_after:int|None
    limit_scope:Literal['provider','user']|None
    provider:ResearchProvider
    edit_question:str|None=None

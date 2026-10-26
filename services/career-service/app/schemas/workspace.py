"""Public single-workspace response: structured state, never raw source/chat."""
from datetime import datetime
from typing import Literal
from pydantic import Field
from app.schemas.analysis import Contract,CareerGoal,DomainId,InterviewResearch,ResearchCoverage,Version
from app.schemas.jd import JDExtractionResult,JDReply

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
    review:JDExtractionResult|None
    current:CurrentCareerGoal
    research:InterviewResearch|None
    coverage:list[ResearchCoverage]=Field(default_factory=list,max_length=6)
    edit_question:str|None=Field(default=None,max_length=600)
    error_code:str|None=Field(default=None,max_length=80)
    error:str|None=Field(default=None,max_length=1000)
    retry_after:int|None=Field(default=None,ge=0)
    expires_at:datetime|None
    exploration_id:DomainId|None


class OperationView(Contract):
    operation_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    status: Literal['running', 'repairing', 'waiting_quota', 'succeeded']
    retry_after: int | None = Field(default=None, ge=0)
    result: dict | None = None
    validation_feedback: dict | None = None


class WorkspaceChatReply(JDReply):
    edit_status:Literal['clarifying','saved','cancelled']|None=None
    workspace:WorkspaceView|None=None

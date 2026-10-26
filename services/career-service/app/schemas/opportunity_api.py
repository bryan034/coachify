"""Owner-scoped public API projection; worker tokens and private context never leave it."""
from datetime import datetime
from pydantic import Field
from app.schemas.opportunity import Model,Category,CategoryResult,OpportunityReport,Summary
from app.schemas.analysis import DomainId,ResearchSource
from typing import Literal

class OpportunityView(Model):
    available:bool
    availability_issues:list[Literal['research_disabled','reasoning_disabled','gemini_not_configured','brave_not_configured','brave_llm_context_required']]=Field(default_factory=list,max_length=5)
    job_id:str|None
    career_target_id:DomainId
    status:Literal['pending','running','partial','completed','failed']
    finished:bool=False
    historical:bool=False
    research:OpportunityReport|None
    categories:dict[Category,CategoryResult]=Field(default_factory=dict,max_length=3)
    sources:list[ResearchSource]=Field(default_factory=list,max_length=30)
    summary:Summary=Field(default_factory=Summary)
    metrics:dict[str,dict[str,int]]=Field(default_factory=dict)
    error_code:str|None=None
    updated_at:datetime|None=None
    retry_after:int|None=Field(default=None,ge=0,le=3600)

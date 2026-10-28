"""Owner-scoped public API projection; worker tokens and private context never leave it."""
from datetime import datetime
from pydantic import Field,ConfigDict
from app.schemas.opportunity import Model,Category,CategoryResult,OpportunityReport,Summary,Finding
from app.schemas.analysis import DomainId,ResearchSource
from typing import Literal

class PublicSource(ResearchSource):
    model_config=ConfigDict(extra='forbid',from_attributes=True)
    evidence:str|None=Field(default=None,exclude=True)

class PublicFinding(Finding):
    model_config=ConfigDict(extra='forbid',from_attributes=True)
    quotes:list[str]=Field(default_factory=list,exclude=True)

class PublicCategoryResult(CategoryResult):
    model_config=ConfigDict(extra='forbid',from_attributes=True)
    findings:list[PublicFinding]=Field(default_factory=list,max_length=20)

class EvidenceView(Model):
    finding_id:str
    quotes:list[str]
    sources:list[ResearchSource]

class ResearchProgress(Model):
    status:str
    finished:bool
    categories:dict[Category,dict[str,str|None]]
    result_version:datetime|None
    research_id:DomainId|None=None
    retry_after:int|None=None

class OpportunityView(Model):
    available:bool
    availability_issues:list[Literal['research_disabled','reasoning_disabled','gemini_not_configured','brave_not_configured','brave_llm_context_required']]=Field(default_factory=list,max_length=5)
    job_id:str|None
    career_target_id:DomainId
    status:Literal['pending','running','partial','completed','failed']
    finished:bool=False
    historical:bool=False
    research_id:DomainId|None=None
    research_version:int|None=None
    categories:dict[Category,PublicCategoryResult]=Field(default_factory=dict,max_length=5)
    sources:list[PublicSource]=Field(default_factory=list,max_length=30)
    summary:Summary=Field(default_factory=Summary)
    metrics:dict[str,dict[str,int]]=Field(default_factory=dict)
    error_code:str|None=None
    updated_at:datetime|None=None
    retry_after:int|None=Field(default=None,ge=0,le=3600)

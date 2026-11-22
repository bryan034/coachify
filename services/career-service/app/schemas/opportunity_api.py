"""Owner-scoped public API projection; worker tokens and private context never leave it."""
from datetime import datetime
from pydantic import Field,ConfigDict,computed_field
from app.schemas.opportunity import Model,Category,CategoryResult,Summary,Finding,MAX_RESEARCH_SOURCES
from app.schemas.analysis import DomainId,ResearchSource
from app.schemas.round_titles import RoundKey,ShortTitle
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

class QuestionResearchView(Model):
    research_id:DomainId
    research_version:int
    focus:str
    findings:list[PublicFinding]=Field(default_factory=list,max_length=12)
    sources:list[PublicSource]=Field(default_factory=list,max_length=12)
    updated_at:datetime

class RoundPreview(Model):
    expectation_id:str|None=None
    question_id:str|None=None
    preparation_id:str|None=None

class OpportunityView(Model):
    available:bool
    availability_issues:list[Literal['research_disabled','reasoning_disabled','brave_not_configured','model_not_configured','search_not_configured','brave_llm_context_required']]=Field(default_factory=list,max_length=5)
    job_id:str|None
    career_target_id:DomainId
    status:Literal['pending','running','partial','completed','failed']
    finished:bool=False
    historical:bool=False
    question_research:list[QuestionResearchView]=Field(default_factory=list,max_length=9)
    research_id:DomainId|None=None
    research_version:int|None=None
    categories:dict[Category,PublicCategoryResult]=Field(default_factory=dict,max_length=5)
    sources:list[PublicSource]=Field(default_factory=list,max_length=MAX_RESEARCH_SOURCES)
    round_titles:dict[RoundKey,ShortTitle]=Field(default_factory=dict,max_length=10)
    summary:Summary=Field(default_factory=Summary)
    metrics:dict[str,dict[str,int]]=Field(default_factory=dict)
    error_code:str|None=None
    updated_at:datetime|None=None
    retry_after:int|None=Field(default=None,ge=0,le=3600)

    @computed_field
    @property
    def round_previews(self)->dict[RoundKey,RoundPreview]:
        interview=self.categories.get('interview_intelligence')
        findings=interview.findings if interview else []
        previews={}
        fields={'expectation_id':('round_format','recruitment_stages','difficulty','application_timeline','candidate_experience'),
                'question_id':('interview_questions',),'preparation_id':('preparation_topics',)}
        for number in sorted({finding.round_number for finding in findings if finding.round_number is not None}):
            values=[finding for finding in findings if finding.round_number==number]
            selected={}
            for key,topics in fields.items():
                candidates=[finding for finding in values if finding.field in topics]
                candidates.sort(key=lambda finding:(finding.scope!='exact',finding.confidence in ('low','insufficient_evidence'),topics.index(finding.field)))
                selected[key]=candidates[0].finding_id if candidates else None
            previews[str(number)]=RoundPreview(**selected)
        return previews

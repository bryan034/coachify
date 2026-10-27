"""Public, claim-level opportunity intelligence; private target links live outside reports."""
from datetime import datetime
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,StringConstraints,model_validator

class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')
Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=600)]
Category=Literal['interview_intelligence','internship_insights','career_progression','conversion_outcomes','company_intelligence']
CATEGORIES=('interview_intelligence','internship_insights','career_progression','conversion_outcomes','company_intelligence')
LEGACY_FIELDS={
 'interview_intelligence':('recruitment_stages','interview_questions','difficulty','application_timeline','preparation_topics'),
 'internship_insights':('compensation','benefits','projects','work_culture','mentorship','work_life_balance','return_offer'),
 'company_intelligence':('overview','products_services','tech_stack','recent_developments','career_growth')}

FIELDS={
 'interview_intelligence':(*LEGACY_FIELDS['interview_intelligence'],'candidate_experience'),
 'internship_insights':('compensation','benefits','projects','mentorship','work_life_balance'),
 'career_progression':('full_time_role','career_path','conversion_salary'),
 'conversion_outcomes':('conversion_rate','historical_cohort','offer_acceptance'),
 'company_intelligence':('company_culture','team_culture','management','work_life_balance'),
}

class Finding(Model):
    finding_id:str=Field(pattern=r'^f[0-9a-f]{16}$')
    field:str=Field(max_length=40)
    value:Text
    confidence:Literal['high','medium','low','insufficient_evidence']
    evidence_type:Literal['official','candidate_reported','third_party','inferred']
    source_ids:list[str]=Field(min_length=1,max_length=3)
    quotes:list[Text]=Field(min_length=1,max_length=3)
    scope:Literal['exact','related_role','related_location','related_employment','general']
    conflict_group:str|None=Field(default=None,max_length=80)
    last_verified_at:datetime

class CategoryResult(Model):
    status:Literal['pending','running','completed','partial','failed','not_applicable']='pending'
    findings:list[Finding]=Field(default_factory=list,max_length=20)
    missing_fields:list[str]=Field(default_factory=list,max_length=20)
    warnings:list[Text]=Field(default_factory=list,max_length=10)
    error_code:str|None=None
    researched_at:datetime|None=None
    expires_at:datetime|None=None
    searches:int=Field(default=0,ge=0,le=12)
    model_calls:int=Field(default=0,ge=0)
    latency_ms:int=Field(default=0,ge=0)
    estimated_cost_usd:float|None=Field(default=None,ge=0)
    # No guessed prices or costs; provider numeric token metrics stay in existing usage logs.

class Summary(Model):
    overview_refs:list[str]=Field(default_factory=list,max_length=3)
    key_takeaway_refs:list[str]=Field(default_factory=list,max_length=6)
    consideration_refs:list[str]=Field(default_factory=list,max_length=6)

class OpportunityReport(Model):
    schema_version:Literal[1,2]=2
    fingerprint:str=Field(pattern=r'^[0-9a-f]{64}$')
    opportunity_id:str|None
    employment_type:Literal['internship','full_time','part_time','contract','unknown']='unknown'
    job_url:str|None=None
    categories:dict[Category,CategoryResult]
    summary:Summary=Field(default_factory=Summary)
    status:Literal['completed','partial','failed']
    researched_at:datetime
    expires_at:datetime
    warnings:list[Text]=Field(default_factory=list,max_length=10)
    models:dict[str,str]=Field(default_factory=dict,max_length=2)

    @model_validator(mode='after')
    def references(self):
        fields=LEGACY_FIELDS if self.schema_version==1 else FIELDS
        if set(self.categories)!=set(fields):raise ValueError('All categories require explicit status.')
        ids=set()
        for category,result in self.categories.items():
            for finding in result.findings:
                if finding.field not in fields[category] or finding.finding_id in ids:raise ValueError('Invalid or duplicate finding.')
                ids.add(finding.finding_id)
        if any(ref not in ids for refs in self.summary.model_dump().values() for ref in refs):raise ValueError('Summary must reference validated findings.')
        return self

class ResearchCommand(Model):
    expected_version:int=Field(strict=True,ge=1)
    expected_selection_version:int=Field(strict=True,ge=0)
    refresh:bool=False
    category:Category|None=None

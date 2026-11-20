"""Version 2 research briefs for the About the role and Interview preparation tabs: short, structured, cited data."""
from datetime import datetime
from typing import Annotated,Literal
from pydantic import AnyHttpUrl,BaseModel,ConfigDict,Field,StringConstraints
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid',alias_generator=to_camel,populate_by_name=True)


Short=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=240)]
Citations=Annotated[list[Annotated[int,Field(ge=1)]],Field(max_length=6)]
Tone=Literal['positive','mixed','negative']
Level=Literal['easy','average','difficult']
Tab=Literal['role','interview']
# Bumped when the saved shape or generation rules change, so older briefs are regenerated.
FORMAT=1

WORD_LIMITS={
    'summary':25,'interview.summary':15,'fact.label':3,'fact.value':5,'fact.note':6,'duty':10,
    'topic.title':4,'topic.takeaway':12,'report':20,'pay.label':3,'pay.value':4,'pay.caveat':10,
    'process.title':3,'process.when':5,'process.detail':12,'difficulty.reason':10,
    'question':15,'prep':20,'asked_about':3,'situational':15,'tone':12,'not_found':3,
    'source.title':8,'source.domain':3,
}


class BriefReport(Model):
    text:Short
    citations:Citations=Field(min_length=1)


class BriefFact(Model):
    label:Short
    value:Short
    note:Short|None=None
    citations:Citations=Field(default_factory=list)


class BriefTopic(Model):
    id:str=Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',max_length=40)
    title:Short
    tone:Tone
    takeaway:Short
    estimated:bool
    conflicting:bool=False
    reports:list[BriefReport]=Field(default_factory=list,max_length=8)


class BriefPay(Model):
    label:Short
    value:Short
    caveat:Short|None=None
    citations:Citations=Field(default_factory=list)


class BriefStep(Model):
    step:int=Field(ge=1,le=10)
    title:Short
    when:Short|None=None
    detail:Short|None=None
    citations:Citations=Field(default_factory=list)


class BriefDifficulty(Model):
    level:Level
    estimated:bool
    reason:Short


class BriefQuestion(Model):
    question:Short
    prep:Short
    estimated:bool


class BriefCited(Model):
    text:Short
    citations:Citations=Field(min_length=1)


class BriefAskedAbout(Model):
    label:Short
    citations:Citations=Field(min_length=1)


class BriefCandidateReports(Model):
    asked_about:list[BriefAskedAbout]=Field(default_factory=list,max_length=8)
    situational:BriefCited|None=None
    tone:BriefCited|None=None
    reports:list[BriefReport]=Field(default_factory=list,max_length=12)


class BriefSource(Model):
    index:int=Field(ge=1)
    title:Short
    domain:Short
    url:AnyHttpUrl


class Brief(Model):
    researched_at:datetime
    source_count:int=Field(ge=0)
    summary:Short
    not_found:list[Short]=Field(default_factory=list,max_length=10)
    sources:list[BriefSource]=Field(default_factory=list,max_length=60)


class RoleBrief(Brief):
    facts:list[BriefFact]=Field(default_factory=list,max_length=4)
    duties:list[Short]=Field(default_factory=list,max_length=6)
    topics:list[BriefTopic]=Field(default_factory=list,max_length=8)
    pay:list[BriefPay]=Field(default_factory=list,max_length=3)


class InterviewBrief(Brief):
    process:list[BriefStep]=Field(default_factory=list,max_length=6)
    difficulty:BriefDifficulty|None=None
    questions:list[BriefQuestion]=Field(default_factory=list,max_length=8)
    candidate_reports:BriefCandidateReports=Field(default_factory=BriefCandidateReports)


class RoleBriefView(Model):
    status:Literal['ready','missing','researching']
    brief:RoleBrief|None=None


class InterviewBriefView(Model):
    status:Literal['ready','missing','researching']
    brief:InterviewBrief|None=None


class BriefCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(strict=True,ge=1)
    refresh:bool=False

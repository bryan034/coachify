"""Keyword-only interview preparation guide for a specific job. No prose, only scannable terms."""
from datetime import date,datetime
from typing import Annotated,Literal
from pydantic import AfterValidator,BaseModel,ConfigDict,Field,StringConstraints

MAX_KEYWORD_WORDS=6
MAX_PROMPT_WORDS=14


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')


def _terse(limit):
    def check(value):
        # Keywords are labels, never sentences.
        if len(value.split())>limit or value.endswith(('.','!',';')):raise ValueError('Use a short keyword, not a sentence.')
        return value
    return check


Keyword=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=48),AfterValidator(_terse(MAX_KEYWORD_WORDS))]
Prompt=Annotated[str,StringConstraints(strip_whitespace=True,min_length=3,max_length=90),AfterValidator(_terse(MAX_PROMPT_WORDS))]
# confirmed: official/employer source; candidate_report: first-hand public report; prediction: no source.
Basis=Literal['confirmed','candidate_report','prediction']
Priority=Literal['high','medium','low']


class Stage(Model):
    round:int|None=Field(default=None,ge=1,le=10,strict=True)
    name:Keyword
    format:list[Keyword]=Field(default_factory=list,max_length=4)
    basis:Basis
    source_ids:list[str]=Field(default_factory=list,max_length=3)


class ResumeLink(Model):
    competency:Keyword
    skill:Keyword|None=None
    signals:list[Keyword]=Field(default_factory=list,max_length=4)
    status:Literal['strength','partial','gap']


class Topic(Model):
    name:Keyword
    priority:Priority
    depth:Literal['awareness','working','deep']
    terms:list[Keyword]=Field(default_factory=list,max_length=6)
    basis:Basis
    source_ids:list[str]=Field(default_factory=list,max_length=3)


class Question(Model):
    text:Prompt
    kind:Literal['behavioural','technical','case','ask']
    basis:Basis
    source_ids:list[str]=Field(default_factory=list,max_length=3)


class CompanyKeywords(Model):
    model:list[Keyword]=Field(default_factory=list,max_length=6)
    products:list[Keyword]=Field(default_factory=list,max_length=6)
    customers:list[Keyword]=Field(default_factory=list,max_length=6)
    competitors:list[Keyword]=Field(default_factory=list,max_length=6)
    risks:list[Keyword]=Field(default_factory=list,max_length=6)


class ScheduleStep(Model):
    when:Keyword
    focus:list[Keyword]=Field(min_length=1,max_length=4)


class GuideSource(Model):
    source_id:str
    url:str
    title:str|None=None


class InterviewPrepGuide(Model):
    goal_id:str
    goal_version:int
    research_id:str|None=None
    generated_at:datetime
    interview_date:date|None=None
    role:list[Keyword]=Field(default_factory=list,max_length=10)
    success:list[Keyword]=Field(default_factory=list,max_length=6)
    process:list[Stage]=Field(default_factory=list,max_length=10)
    resume:list[ResumeLink]=Field(default_factory=list,max_length=10)
    syllabus:list[Topic]=Field(default_factory=list,max_length=14)
    company:CompanyKeywords=Field(default_factory=CompanyKeywords)
    questions:list[Question]=Field(default_factory=list,max_length=30)
    schedule:list[ScheduleStep]=Field(default_factory=list,max_length=8)
    sources:list[GuideSource]=Field(default_factory=list,max_length=30)
    # Sections this version cannot fill from evidence, for example recent news.
    not_covered:list[Keyword]=Field(default_factory=list,max_length=6)


class PrepCommand(Model):
    expected_version:int=Field(strict=True,ge=1)
    interview_date:date|None=None
    refresh:bool=False

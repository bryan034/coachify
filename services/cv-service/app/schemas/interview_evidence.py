"""One evidence vocabulary for CV extraction, clarification and interview memory."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ReviewField = Literal['role', 'responsibilities', 'personal_contribution', 'assistance',
    'task_scope', 'complexity', 'problem_solving', 'outcome', 'skill_use', 'recency', 'frequency', 'limitations']
EvidenceStatus = Literal['supported', 'partial', 'unknown', 'conflicting', 'skipped', 'not_applicable']


class ReviewQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=500)


class ReviewFact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: ReviewField
    skill_name: str | None = Field(default=None, min_length=1, max_length=120)
    attribution: Literal['personal', 'shared', 'team', 'observed', 'denied', 'unknown'] | None = None
    status: EvidenceStatus
    value: str | None = Field(default=None, min_length=1, max_length=800)
    evidence: list[ReviewQuote] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def status_value(self):
        if self.status in {'supported', 'partial', 'conflicting'} and self.value is None:
            raise ValueError('Known or conflicting evidence needs its supported description.')
        if self.status in {'unknown', 'skipped', 'not_applicable'} and self.value is not None:
            raise ValueError('An unknown or omitted fact cannot carry a factual value.')
        return self


def fact_key(fact):
    from app.domain.capabilities import normalized_name
    return fact['field'], normalized_name(fact.get('skill_name') or '')


def fact_statement(fact):
    subject = f"For the user's {fact['skill_name']} work" if fact.get('skill_name') else 'For this experience'
    statement = f"{subject}, {fact['field']} is {fact['value']}" if fact['value'] is not None else f"{subject}, the user says {fact['field']} is {fact['status']}."
    if fact.get('attribution'):
        statement += f" Attribution is {fact['attribution']}; personal/shared means the user personally performed the stated work, team means teammates only, observed means watching only."
    return statement

"""One evidence vocabulary for CV extraction, clarification and interview memory."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ReviewField = Literal['role', 'responsibilities', 'personal_contribution', 'assistance',
    'task_scope', 'complexity', 'problem_solving', 'outcome', 'skill_use', 'recency', 'frequency', 'limitations', 'replication_confidence', 'self_rating']
EvidenceStatus = Literal['supported', 'partial', 'unknown', 'conflicting', 'skipped', 'not_applicable']


class ReviewQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1)


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
        if self.field=='self_rating' and self.status in {'supported','partial','conflicting'}:
            if self.value not in {str(i) for i in range(1,11)} or not self.skill_name:
                raise ValueError('A self-rating needs a named skill and a whole-number value from 1 to 10.')
        if self.status in {'supported', 'partial', 'conflicting'} and self.value is None:
            raise ValueError('Known or conflicting evidence needs its supported description.')
        if self.status in {'unknown', 'skipped', 'not_applicable'} and self.value is not None:
            raise ValueError('An unknown or omitted fact cannot carry a factual value.')
        return self


def fact_key(fact):
    from app.domain.capabilities import normalized_name
    return fact['field'], normalized_name(fact.get('skill_name') or '')


def unique_facts(facts):
    """Retain distinct claims, including different attribution or citations."""
    result = []
    for fact in facts:
        if fact not in result:
            result.append(fact)
    return result


def fact_groups(facts):
    groups = {}
    for fact in unique_facts(facts):
        groups.setdefault(fact_key(fact), []).append(fact)
    return groups


def facts_closed(facts):
    return bool(facts) and all(f['status'] in {'supported', 'unknown', 'skipped', 'not_applicable'} for f in facts)


def fact_group_value(facts):
    # Preserve existing attempt signatures for a single saved fact.
    return facts[0] if len(facts) == 1 else facts if facts else None


def fact_statement(fact):
    subject = f"For the user's {fact['skill_name']} work" if fact.get('skill_name') else 'For this experience'
    statement = f"{subject}, {fact['field']} is {fact['value']}" if fact['value'] is not None else f"{subject}, the user says {fact['field']} is {fact['status']}."
    # Unknown attribution is an absence of an ownership claim. Asking the
    # verifier to prove that the CV declares it unknown rejects valid task
    # descriptions whose ownership simply has not been established.
    if fact.get('attribution') not in (None, 'unknown'):
        statement += f" Attribution is {fact['attribution']}; personal/shared means the user personally performed the stated work, team means teammates only, observed means watching only."
    return statement


class SkillEstimate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(min_length=1, max_length=100)
    skill_name: str = Field(min_length=1, max_length=120)
    level: Literal['insufficient_evidence', 'guided_application', 'independent_application', 'complex_application']
    explanation: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)


# elo_shared.competence_scale: 1 = not competent, 5 = independent and understands, 10 = most complex work.
SkillLevel = Annotated[int, Field(ge=1, le=10, strict=True)]


class ExtractedSkillLevel(BaseModel):
    """A model-judged 1-10 level of one skill by itself, never a comparison with a career goal.

    Read pessimistically from the CV and capped by the backend where independence is not stated.
    Each level cites exact CV quotations.
    """
    model_config = ConfigDict(extra='forbid')
    skill_name: str = Field(min_length=1, max_length=120)
    level: SkillLevel
    rationale: str = Field(min_length=1, max_length=400)
    evidence: list[ReviewQuote] = Field(min_length=1, max_length=3)

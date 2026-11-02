"""Typed proposals; the agent cannot supply persistence or execution controls."""
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.cv import StrictModel, InterpretedClaim, InterpretedDates
from app.schemas.conversation import ConversationRoute, SkillEstimate, InterviewProgress
from app.schemas.interview_evidence import ReviewFact, ReviewField, ReviewQuote


class InterviewInterpretation(StrictModel):
    item_id: str = Field(min_length=1, max_length=100)
    resolution: Literal['resolved', 'partial', 'unanswerable']
    claims: list[InterpretedClaim] = Field(default_factory=list, max_length=20)
    dates: InterpretedDates | None = None
    statement_excerpt: str | None = Field(default=None, min_length=1, max_length=500)
    review_evidence: list[ReviewFact] = Field(default_factory=list, max_length=12)
    resolved_uncertainties: list[Literal['personal_contribution', 'responsibility', 'proficiency', 'duration', 'claim', 'qualification', 'date']] = Field(default_factory=list, max_length=7)
    remaining_uncertainties: list[Literal['personal_contribution', 'responsibility', 'proficiency', 'duration', 'claim', 'qualification', 'date']] = Field(default_factory=list, max_length=7)


class InterviewTurn(ConversationRoute):
    intent: Literal['answer', 'side_question', 'stop', 'skip', 'change']
    memory_notes: list[ReviewQuote] = Field(default_factory=list, max_length=4)
    interpretations: list[InterviewInterpretation] = Field(default_factory=list, max_length=5)

    @model_validator(mode='after')
    def safe_intent(self):
        if self.intent in {'side_question', 'stop'} and (self.actions or self.interpretations):
            raise ValueError('Questions and stop requests cannot change factual evidence.')
        ids = [value.item_id for value in self.interpretations]
        if len(ids) != len(set(ids)): raise ValueError('Duplicate source interpretations.')
        if set(ids) - {a.item_id for a in self.actions if a.kind in {'clarify', 'correct'}}:
            raise ValueError('Interpretation needs an explicit source-bound action.')
        return self


class InterviewTarget(StrictModel):
    field: ReviewField
    skill_name: str | None = Field(default=None, min_length=1, max_length=120)


class InterviewCoverage(StrictModel):
    item_id: str = Field(min_length=1, max_length=100)
    status: Literal['reviewed', 'reviewed_with_gaps', 'deferred']
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)


class InterviewDecision(StrictModel):
    action: Literal['ask', 'finish', 'pause', 'answer', 'recall']
    reply: str = Field(min_length=1, max_length=4000)
    item_id: str | None = Field(default=None, min_length=1, max_length=100)
    recall_ids: list[str] = Field(default_factory=list, max_length=4)
    targets: list[InterviewTarget] = Field(default_factory=list, max_length=3)
    coverage: list[InterviewCoverage] = Field(default_factory=list, max_length=160)
    estimates: list[SkillEstimate] = Field(default_factory=list, max_length=20)

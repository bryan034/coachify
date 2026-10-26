"""J08/J09 private drafts, bounded conversational context and explicit selection."""
from app.schemas.analysis import EmploymentType

from typing import Literal
from pydantic import Field, model_validator
from app.schemas.analysis import (Contract, Document, DomainId, Evidence, Generation, Text, TargetSkill,
    NonSkillRequirement, SourceUrl, AccountId)

Question = Literal['aspirations', 'education', 'experience', 'skills', 'interests', 'preferences']
QUESTIONS = {
    'aspirations': 'What would you like to achieve in your career, or what are you hoping to figure out?',
    'education': 'What have you studied, or what are you learning now?',
    'experience': 'Tell me about work, projects or activities, and what you personally contributed.',
    'skills': 'Which skills have you used? Tell me what you did with them; it is fine to be unsure.',
    'interests': 'Which activities do you enjoy, and which would you rather avoid?',
    'preferences': 'What matters in your next role: location, work style, industry or other constraints?',
}


class RoleSuggestion(Contract):
    role: Text
    field: Text
    rationale: Evidence
    uncertainty: Evidence


class ContextUpdate(Contract):
    topic: Question
    status: Literal['answered', 'partial', 'unknown']
    value: Evidence | None
    quote: Evidence

    @model_validator(mode='after')
    def known_value(self):
        if (self.status == 'unknown') != (self.value is None):
            raise ValueError('Unknown context remains null; other updates need a value.')
        return self


class ExplorationOutput(Contract):
    reply: Evidence
    follow_up: Evidence | None
    focus: Question | None
    context_updates: list[ContextUpdate] = Field(max_length=6)
    interests: list[Text] = Field(max_length=30)
    preferences: list[Text] = Field(max_length=30)
    suggestions: list[RoleSuggestion] = Field(max_length=5)

    @model_validator(mode='after')
    def bounded_message(self):
        if len(self.reply) + len(self.follow_up or '') + 2 > 600:
            raise ValueError('Keep the complete agent message within 600 characters.')
        if len({u.topic for u in self.context_updates}) != len(self.context_updates):
            raise ValueError('Only one update per context topic.')
        return self


class Answer(Contract):
    status: Literal['answered', 'partial', 'skipped']
    value: Evidence | None = None
    quote: Evidence | None = None

    @model_validator(mode='after')
    def answer_value(self):
        if (self.status != 'skipped') != (self.value is not None):
            raise ValueError('An answered question needs a value; a skipped question remains unknown.')
        return self


class Turn(Contract):
    question: str = Field(max_length=40)
    answer: Answer
    reply: Evidence


class CvContext(Contract):
    mode: Literal['none', 'temporary', 'saved'] = 'none'
    cv_id: DomainId | None = None
    filename: Text | None = None
    extraction_version: Text | None = None
    profile_version: int | None = Field(default=None, ge=1)
    version: int | None = Field(default=None, ge=1)
    attachment_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class GoalDraft(Document):
    record_type: Literal['exploration_draft'] = 'exploration_draft'
    user_id: AccountId
    answers: dict[Question, Answer] = Field(default_factory=dict, max_length=6)
    focus: Question | None = 'aspirations'
    agent_question: Evidence | None = QUESTIONS['aspirations']
    total_turns: int = Field(default=0, ge=0)
    turns: list[Turn] = Field(default_factory=list, max_length=30)
    interests: list[Text] = Field(default_factory=list, max_length=30)
    preferences: list[Text] = Field(default_factory=list, max_length=30)
    suggestions: list[RoleSuggestion] = Field(default_factory=list, max_length=5)
    cv: CvContext = Field(default_factory=CvContext)
    generation: Generation | None = None

    def next_question(self):
        unresolved = [key for key in QUESTIONS if key not in self.answers or self.answers[key].status == 'partial']
        return self.focus if self.focus in unresolved else next(iter(unresolved), None)


class StartExploration(Contract):
    consent: Literal[True]
    cv_id: DomainId | None = None
    temporary_filename: Text | None = None

    @model_validator(mode='after')
    def one_cv(self):
        if self.cv_id and self.temporary_filename:
            raise ValueError('Choose one CV source.')
        return self


class SendAnswer(Contract):
    expected_version: int = Field(strict=True, ge=1)
    answer: Evidence | None = None
    skip: bool = False
    attachment_text: str | None = Field(default=None, min_length=1, max_length=20000, repr=False)

    @model_validator(mode='after')
    def one_answer(self):
        if (self.answer is not None) == self.skip:
            raise ValueError('Answer the question or skip it.')
        return self


class SaveGoal(Contract):
    expected_selection_version: int = Field(strict=True, ge=0)
    expected_draft_version: int | None = Field(default=None, strict=True, ge=1)
    draft_id: DomainId | None = None
    target_type: Literal['specific_job', 'career_exploration']
    role: Text
    field: Text
    employment_type: EmploymentType = 'unknown'
    company: Text | None = None
    location: Text | None = None
    seniority_level: Text | None = None
    job_url: SourceUrl | None = None
    replace_current: bool = False
    review_id: DomainId | None = None
    expected_review_version: int | None = Field(default=None, strict=True, ge=1)
    # Skills/provenance are server-owned; later J03/J10 workers supply them.

    @model_validator(mode='after')
    def draft_version(self):
        if (self.review_id is None) != (self.expected_review_version is None):
            raise ValueError('A review reference needs its expected version.')
        if self.review_id and self.draft_id:
            raise ValueError('Choose a review or an exploration draft.')
        if (self.draft_id is None) != (self.expected_draft_version is None):
            raise ValueError('A draft reference needs its expected version.')
        if self.target_type == 'career_exploration' and self.draft_id is None and self.review_id is None:
            raise ValueError('Review an exploration draft before confirming.')
        return self


class AssessmentStatus(Contract):
    status: Literal['no_cv', 'not_evaluated', 'evaluated', 'unavailable']
    cv_uploaded: bool | None
    skills_evaluated: bool | None


class CvSummary(Contract):
    id: DomainId = Field(alias='_id')
    user_id: AccountId
    file_name: Text
    extraction_status: Literal['pending', 'processing', 'succeeded', 'failed']
    extraction_version: Text
    version: int = Field(strict=True, ge=1)

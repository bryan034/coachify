"""Provider-neutral payloads. Only transient requests may contain source text."""
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.analysis import (Contract, Evidence, GapResult, InputVersions, InterviewSkill,
    NonSkillRequirement, ResearchContext, ResearchSource, TargetSkill, Text, SkillId, CvSkill, SourceUrl)


class Message(Contract):
    role: Literal['user', 'assistant']
    content: Evidence


class TargetOutput(Contract):
    field: Text
    role: Text
    company: Text | None = None
    skills: list[TargetSkill] = Field(max_length=200)
    non_skill_requirements: list[NonSkillRequirement] = Field(default_factory=list, max_length=100)


class ChatOutput(Contract):
    reply: Evidence
    suggested_roles: list[Text] = Field(default_factory=list, max_length=5)


class ResearchOutput(Contract):
    skills: list[InterviewSkill] = Field(max_length=200)


class GapOutput(Contract):
    job_skill_gaps: list[GapResult] = Field(max_length=200)
    interview_prep_gaps: list[GapResult] = Field(max_length=200)
    summary: Evidence
    analysis_status: Literal['succeeded', 'partial']


class AIInput(Contract):
    stage: Literal['extraction', 'chat', 'guidance', 'research', 'gap_analysis']
    source_text: str | None = Field(default=None, min_length=1, max_length=20000, repr=False)
    conversation: list[Message] = Field(default_factory=list, max_length=30, repr=False)
    # Callers build this from authenticated, approved structured snapshots.
    context: str = Field(default='', max_length=20000, repr=False)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=100)
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)
    versions: InputVersions | None = None
    public_context: ResearchContext | None = None
    allowed_skill_ids: list[SkillId] = Field(default_factory=list, max_length=400)
    cv_skills: list[CvSkill] = Field(default_factory=list, max_length=200)
    target_skills: list[TargetSkill] = Field(default_factory=list, max_length=200)
    interview_skills: list[InterviewSkill] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def input_for_stage(self):
        if self.stage == 'extraction' and not self.source_text:
            raise ValueError('Extraction requires transient JD text.')
        if self.stage != 'extraction' and self.source_text is not None:
            raise ValueError('Raw JD text is only accepted by the extraction stage.')
        if self.stage == 'chat' and not self.conversation:
            raise ValueError('Chat requires a conversation.')
        if self.stage == 'gap_analysis' and self.versions is None:
            raise ValueError('Gap analysis requires pinned input versions.')
        if self.stage == 'research' and (self.conversation or self.context or self.cv_skills or self.target_skills or self.interview_skills or self.source_urls or self.versions or not self.public_context):
            raise ValueError('Shared research accepts only public context and verified public sources.')
        return self


OUTPUTS = {'extraction': TargetOutput, 'chat': ChatOutput, 'guidance': TargetOutput,
           'research': ResearchOutput, 'gap_analysis': GapOutput}

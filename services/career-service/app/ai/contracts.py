"""Provider-neutral payloads. Only transient requests may contain source text."""
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.goals import ExplorationOutput
from app.schemas.jd import ChatText, JDExtraction, JDReply
from app.schemas.analysis import (Contract, Evidence, GapResult, InputVersions, InterviewSkill,
    NonSkillRequirement, BraveAnswer, ResearchContext, ResearchSource, TargetSkill, Text, SkillId, CvSkill, SourceUrl)


class Message(Contract):
    role: Literal['user', 'assistant']
    content: ChatText


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
    stage: Literal['jd_scope', 'extraction', 'chat', 'guidance', 'research', 'gap_analysis', 'exploration', 'jd_extraction', 'jd_chat', 'jd_edit', 'role_guidance', 'interview_synthesis', 'workspace_chat', 'question_route', 'focused_answer', 'goal_edit', 'context_route', 'context_answer', 'research_plan', 'research_assess', 'opportunity_plan','opportunity_evaluate','opportunity_support','opportunity_summary','discovery_turn','discovery_plan','discovery_extract','discovery_summary']
    source_text: str | None = Field(default=None, min_length=1, max_length=8000, repr=False)
    conversation: list[Message] = Field(default_factory=list, max_length=30, repr=False)
    # Callers build this from authenticated, approved structured snapshots.
    context: str = Field(default='', max_length=40000, repr=False)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=100)
    summaries: list[BraveAnswer] = Field(default_factory=list,max_length=2)
    search_queries:list[str]=Field(default_factory=list,max_length=6)
    research_hints:list[Text]=Field(default_factory=list,max_length=8)
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)
    versions: InputVersions | None = None
    public_context: ResearchContext | None = None
    allowed_skill_ids: list[SkillId] = Field(default_factory=list, max_length=400)
    cv_skills: list[CvSkill] = Field(default_factory=list, max_length=200)
    target_skills: list[TargetSkill] = Field(default_factory=list, max_length=200)
    interview_skills: list[InterviewSkill] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def input_for_stage(self):
        if (self.search_queries or self.research_hints) and self.stage not in ('research_plan','research_assess'):
            raise ValueError('Search planning fields belong to public research only.')
        if any(len(query)>180 for query in self.search_queries):raise ValueError('Search query exceeds its limit.')
        if self.summaries and self.stage!='interview_synthesis':raise ValueError('Brave summaries belong to public interview synthesis only.')
        if self.stage in ('extraction','jd_extraction','jd_scope') and not self.source_text:
            raise ValueError('Extraction requires transient JD text.')
        if self.stage not in ('extraction','jd_extraction','jd_scope') and self.source_text is not None:
            raise ValueError('Raw JD text is only accepted by extraction stages.')
        if self.stage in ('chat', 'jd_chat', 'jd_edit', 'workspace_chat', 'question_route', 'focused_answer', 'goal_edit', 'context_route', 'context_answer') and not self.conversation:
            raise ValueError('Chat requires a conversation.')
        if self.stage in ('jd_chat', 'jd_edit', 'workspace_chat', 'question_route', 'focused_answer', 'goal_edit', 'context_route', 'context_answer') and not self.context:
            raise ValueError('JD chat requires extracted career-goal context.')
        if self.stage == 'gap_analysis' and self.versions is None:
            raise ValueError('Gap analysis requires pinned input versions.')
        if self.stage in ('research','interview_synthesis','research_plan','research_assess') and (self.conversation or self.context or self.cv_skills or self.target_skills or self.interview_skills or self.source_urls or self.versions or not self.public_context):
            raise ValueError('Shared research accepts only public context and verified public sources.')
        return self


OUTPUTS = {'extraction': TargetOutput, 'chat': ChatOutput, 'guidance': TargetOutput,
           'research': ResearchOutput, 'gap_analysis': GapOutput, 'exploration': ExplorationOutput, 'jd_extraction':JDExtraction, 'jd_chat':JDReply}

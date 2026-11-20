"""Provider-neutral payloads. Only transient requests may contain source text."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from app.schemas.goals import ExplorationOutput
from app.schemas.jd import ChatText, JDExtraction
from app.schemas.analysis import (Contract, BraveAnswer, ResearchContext, ResearchSource, Text, SourceUrl)

MAX_SEARCH_QUERY = 180


class Message(Contract):
    role: Literal['user', 'assistant']
    content: ChatText


class DiscoveryHistoryMessage(Message):
    content: Annotated[str, Field(min_length=1, max_length=12000)]


class AIInput(Contract):
    stage: Literal['goal_summary', 'interview_prep', 'role_summary', 'jd_scope', 'exploration', 'jd_extraction', 'passage_scope', 'role_guidance', 'interview_synthesis', 'workspace_chat', 'question_route', 'focused_answer', 'goal_edit', 'context_route', 'context_answer', 'career_guidance', 'research_plan', 'research_assess', 'opportunity_plan','opportunity_triage','opportunity_structure','opportunity_skill_levels','discovery_turn','discovery_plan','discovery_assess','discovery_extract','discovery_summary']
    source_text: str | None = Field(default=None, min_length=1, max_length=8000, repr=False)
    conversation: list[Message | DiscoveryHistoryMessage] = Field(default_factory=list, max_length=30, repr=False)
    context: str = Field(default='', repr=False)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=100)
    summaries: list[BraveAnswer] = Field(default_factory=list,max_length=2)
    search_queries:list[str]=Field(default_factory=list,max_length=6)
    research_hints:list[Text]=Field(default_factory=list,max_length=8)
    source_urls: list[SourceUrl] = Field(default_factory=list, max_length=10)
    public_context: ResearchContext | None = None

    @model_validator(mode='after')
    def input_for_stage(self):
        if self.stage != 'discovery_turn':
            for message in self.conversation:Message.model_validate(message.model_dump())
        if (self.search_queries or self.research_hints) and self.stage not in ('research_plan','research_assess'):
            raise ValueError('Search planning fields belong to public research only.')
        if any(len(query)>MAX_SEARCH_QUERY for query in self.search_queries):raise ValueError('Search query exceeds its limit.')
        if self.summaries and self.stage!='interview_synthesis':raise ValueError('Brave summaries belong to public interview synthesis only.')
        if self.stage in ('jd_extraction','jd_scope') and not self.source_text:
            raise ValueError('Extraction requires transient JD text.')
        if self.stage not in ('jd_extraction','jd_scope') and self.source_text is not None:
            raise ValueError('Raw JD text is only accepted by extraction stages.')
        if self.stage in ('workspace_chat', 'question_route', 'focused_answer', 'goal_edit', 'context_route', 'context_answer', 'career_guidance') and not self.conversation:
            raise ValueError('Chat requires a conversation.')
        if self.stage in ('workspace_chat', 'question_route', 'focused_answer', 'goal_edit', 'context_route', 'context_answer', 'career_guidance') and not self.context:
            raise ValueError('JD chat requires extracted career-goal context.')
        if self.stage in ('interview_synthesis','research_plan','research_assess') and (self.conversation or self.context or self.source_urls or not self.public_context):
            raise ValueError('Shared research accepts only public context and verified public sources.')
        return self


OUTPUTS = {'exploration': ExplorationOutput, 'jd_extraction':JDExtraction}

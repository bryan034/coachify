"""Additive CV conversation contracts; transcript revisions are not evidence versions."""
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.schemas.cv import StrictModel, Text, ConfirmedContext, ItemMutation


class ConversationStart(StrictModel):
    cv_id: str | None = Field(default=None, max_length=100)
    mutation_id: UUID


class ConversationMutation(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    mutation_id: UUID


class ConversationSend(ConversationMutation):
    text: Text
    command: Literal['review', 'continue', 'skip'] | None = None
    item_id: str | None = Field(default=None, max_length=100)

    @field_validator('text')
    @classmethod
    def readable(cls, value):
        if any((ord(char) < 32 and char not in '\n\t') or ord(char) == 127 for char in value):
            raise ValueError('Use readable text.')
        return value


class ConversationDecision(ConversationMutation):
    decision: Literal['save', 'cancel', 'retry']
    item_id: str | None = Field(default=None, max_length=100)
    mode: Literal['attach', 'distinct'] | None = None
    attach_to_id: str | None = Field(default=None, max_length=100)


class ChatChoice(StrictModel):
    id: str
    label: str
    description: str
    kind: Literal['item', 'declaration'] = 'item'


class ChatChange(StrictModel):
    field: str
    before: str | None = None
    after: str | None = None


class ChatAction(StrictModel):
    id: str
    kind: Literal['clarify', 'correct', 'remove', 'add_capability', 'choose_source', 'route', 'skip']
    status: Literal['awaiting_confirmation', 'needs_source', 'pending', 'saved', 'failed', 'cancelled', 'stale']
    title: str
    summary: str
    item_id: str | None = None
    item_title: str | None = None
    question_id: str | None = None
    changes: list[ChatChange] = Field(default_factory=list)
    choices: list[ChatChoice] = Field(default_factory=list, max_length=260)
    error: str | None = None


class ChatMessage(StrictModel):
    id: str
    sequence: int
    role: Literal['user', 'assistant']
    text: str
    created_at: str
    actions: list[ChatAction] = Field(default_factory=list)


class ActiveQuestion(StrictModel):
    id: str
    item_id: str
    title: str
    question: str


class ChatLimits(StrictModel):
    max_message_chars: int = 4000
    max_messages: int = 500


class ConversationView(StrictModel):
    id: str
    cv_id: str | None
    revision: int
    read_only: bool
    previous_conversation_id: str | None = None
    active_question: ActiveQuestion | None = None
    context: ConfirmedContext | None = None
    context_error: str | None = None
    messages: list[ChatMessage]
    next_before: int | None = None
    limits: ChatLimits = Field(default_factory=ChatLimits)


class ConversationSummary(StrictModel):
    id: str
    cv_id: str | None
    updated_at: str
    read_only: bool
    message_count: int


class ConversationList(StrictModel):
    conversations: list[ConversationSummary]


class RouteAction(StrictModel):
    """Model-proposed data. It cannot choose mutation IDs, versions or destinations."""
    kind: Literal['clarify', 'correct', 'remove', 'add_capability', 'skip']
    item_id: str | None = Field(default=None, max_length=100)
    question_id: str | None = Field(default=None, max_length=100)
    excerpt: str = Field(min_length=1, max_length=4000)
    fields: dict = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=120)
    candidate_item_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def action_shape(self):
        if self.fields:
            if self.kind != 'correct': raise ValueError('Only corrections may supply fields.')
            ItemMutation.model_validate({'action': 'update', 'expected_version': 0,
                'mutation_id': '00000000-0000-0000-0000-000000000000', **self.fields})
            if set(self.fields) & {'action', 'expected_version', 'mutation_id'}:
                raise ValueError('A model cannot supply execution controls.')
        if self.kind == 'add_capability' and not self.name:
            raise ValueError('Name the stated capability.')
        if self.kind != 'add_capability' and self.name is not None:
            raise ValueError('Only manual capabilities supply a name.')
        return self


class ConversationRoute(StrictModel):
    reply: str = Field(min_length=1, max_length=2000)
    actions: list[RouteAction] = Field(default_factory=list, max_length=5)

"""Private operational records; additional to the five logical domain collections."""
from typing import Literal
from pydantic import Field, model_validator
from app.ai.contracts import Message
from app.schemas.analysis import AccountId, Document, DomainId, Generation, InputVersions, Text


class ExplorationSession(Document):
    user_id: AccountId
    messages: list[Message] = Field(default_factory=list, max_length=30)
    interests: list[Text] = Field(default_factory=list, max_length=30)
    preferences: list[Text] = Field(default_factory=list, max_length=30)
    selected_career_goal_id: DomainId | None = None
    generation: Generation | None = None


class StoredOperation(Document):
    user_id: AccountId
    stage: Literal['extraction', 'chat', 'guidance', 'research', 'gap_analysis']
    status: Literal['pending', 'running', 'succeeded', 'failed', 'cancelled']
    input_revision: Text
    inputs: InputVersions | None = None
    result_id: DomainId | None = None
    generation: Generation | None = None
    error_code: Literal['not_configured', 'invalid_operation', 'stale_input', 'busy', 'capacity',
        'rate_limited', 'timeout', 'unavailable', 'provider_auth', 'provider_configuration',
        'context_limit', 'output_limit', 'incomplete_output', 'invalid_output', 'cancelled'] | None = None

    @model_validator(mode='after')
    def completed_operation(self):
        if self.status == 'succeeded' and (not self.result_id or not self.generation or self.error_code):
            raise ValueError('Successful operations need a result and generation provenance.')
        if self.status == 'failed' and not self.error_code:
            raise ValueError('Failed operations need a safe error code.')
        if self.status != 'succeeded' and self.result_id:
            raise ValueError('Unsuccessful operations cannot publish a result.')
        return self

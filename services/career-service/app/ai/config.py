"""Server-only settings. A missing key leaves previews usable."""
import os
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


REASONING_MODEL='gemini-3.5-flash-lite'


class AISettings(BaseModel):
    """Gemini adapter configuration; credentials remain server-only."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool = False
    provider: str = Field(default='gemini', min_length=1, max_length=80)
    base_url: str = 'https://generativelanguage.googleapis.com/v1beta/openai'
    model: str = Field(default=REASONING_MODEL, min_length=1, max_length=160)
    api_key: SecretStr = SecretStr('')
    response_mode: Literal['json_object', 'json_schema', 'json_schema_strict'] = 'json_schema'
    token_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_tokens'
    timeout_seconds: float = Field(default=45, ge=1, le=60)
    retries: int = Field(default=1, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=128, le=8192)
    context_tokens: int = Field(default=65536, ge=2048, le=262144)

    @model_validator(mode='after')
    def valid_provider(self):
        p = urlsplit(self.base_url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('The model API base URL must use HTTPS without credentials/query.')
        if self.enabled and (not self.model.strip() or not self.api_key.get_secret_value().strip()):
            raise ValueError('Enabled AI requires GEMINI_REASONING_MODEL and GEMINI_API_KEY.')
        return self

    @classmethod
    def from_env(cls):
        """Load the single Gemini configuration used by every model stage."""
        key=os.getenv('GEMINI_API_KEY','').strip()
        values={'api_key':key,'enabled':os.getenv('AI_ENABLED','true' if key else 'false'),
                'model':os.getenv('GEMINI_REASONING_MODEL',REASONING_MODEL).strip()}
        for field in ('timeout_seconds','retries','max_output_tokens','context_tokens'):
            if 'AI_'+field.upper() in os.environ:values[field]=os.environ['AI_'+field.upper()]
        try:return cls(**values)
        except ValueError:raise ValueError('Invalid server Gemini configuration. Check AI_ENABLED, GEMINI_API_KEY, GEMINI_REASONING_MODEL and AI task limits.') from None


class GeminiSettings(AISettings):
    """Named Gemini settings for production composition."""
    reasoning_from_env = classmethod(AISettings.from_env.__func__)

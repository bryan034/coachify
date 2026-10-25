"""Server-only settings. A missing key leaves previews usable."""
import os
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class AISettings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool = False
    provider: str = Field(default='groq', min_length=1, max_length=80)
    base_url: str = 'https://api.groq.com/openai/v1'
    model: str = Field(default='', max_length=160)
    api_key: SecretStr = SecretStr('')
    response_mode: Literal['json_object', 'json_schema', 'json_schema_strict'] = 'json_object'
    token_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_completion_tokens'
    timeout_seconds: float = Field(default=45, ge=1, le=60)
    retries: int = Field(default=1, ge=0, le=2)
    max_output_tokens: int = Field(default=4096, ge=128, le=8192)
    context_tokens: int = Field(default=65536, ge=2048, le=262144)
    requests_per_minute: int = Field(default=10, ge=1, le=60)
    concurrency: int = Field(default=2, ge=1, le=8)

    @model_validator(mode='after')
    def valid_provider(self):
        p = urlsplit(self.base_url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('AI_BASE_URL must be an HTTPS API base URL without credentials/query.')
        if self.enabled and (not self.model.strip() or not self.api_key.get_secret_value().strip()):
            raise ValueError('Enabled AI requires AI_MODEL and AI_API_KEY.')
        return self

    @classmethod
    def from_env(cls):
        names = {key: os.environ['AI_' + key.upper()] for key in cls.model_fields if 'AI_' + key.upper() in os.environ}
        try:
            return cls(**names)
        except ValueError:
            # Startup configuration errors must not echo env values or secret inputs.
            raise ValueError('Invalid server AI configuration. Check the Career service settings.') from None

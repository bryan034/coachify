"""Server-only settings. A missing key leaves previews usable."""
import os
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from elo_shared.model_sdk import resolve_model_api_key


OPENROUTER_BASE_URL='https://openrouter.ai/api/v1'
REASONING_MODEL='openai/gpt-4o-mini'


class AISettings(BaseModel):
    """OpenAI-compatible adapter configuration; credentials remain server-only."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool = False
    provider: Literal['compatible'] = 'compatible'
    base_url: str = OPENROUTER_BASE_URL
    model: str = Field(default=REASONING_MODEL, min_length=1, max_length=160)
    api_key: SecretStr = SecretStr('')
    response_mode: Literal['json_object', 'json_schema', 'json_schema_strict'] = 'json_schema_strict'
    token_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_tokens'
    timeout_seconds: float = Field(default=60, ge=1, le=300)
    retries: int = Field(default=1, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=128)
    context_tokens: int | None = Field(default=None, ge=2048)
    # Plain HTTP only for synthetic fixture providers in a development stack.
    allow_http: bool = False

    @model_validator(mode='after')
    def valid_provider(self):
        if self.timeout_seconds>60:
            raise ValueError('Cloud model request timeouts cannot exceed 60 seconds.')
        p = urlsplit(self.base_url)
        if p.scheme not in (('http','https') if self.allow_http else ('https',)) or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('The model API base URL requires HTTPS (HTTP only for explicit development fixtures), without credentials/query.')
        if self.enabled and (not self.model.strip() or not self.api_key.get_secret_value().strip()):
            raise ValueError('Enabled AI requires CAREER_LLM_MODEL and CAREER_LLM_API_KEY.')
        return self

    @classmethod
    def from_env(cls):
        """Load the single configured model used by every Career stage."""
        # An explicitly empty canonical key overrides the deprecated alias.
        configured_base=os.getenv('CAREER_LLM_BASE_URL','').strip() or OPENROUTER_BASE_URL
        key=resolve_model_api_key(configured_base,os.getenv('CAREER_LLM_API_KEY','').strip())
        values={'api_key':key,'enabled':os.getenv('AI_ENABLED','true' if key else 'false'),
                'base_url':configured_base,
                'model':os.getenv('CAREER_LLM_MODEL',REASONING_MODEL).strip(),
                'response_mode':os.getenv('CAREER_LLM_RESPONSE_MODE','').strip() or 'json_schema_strict',
                'token_parameter':os.getenv('CAREER_LLM_TOKEN_PARAMETER','max_tokens').strip(),
                'allow_http':os.getenv('APP_ENV')=='development' and os.getenv('CAREER_LLM_ALLOW_HTTP')=='true'}
        for field in ('timeout_seconds','retries','max_output_tokens','context_tokens'):
            setting='AI_'+field.upper()
            if setting in os.environ:
                if field in ('max_output_tokens','context_tokens') and not os.environ[setting].strip():continue
                values[field]=os.environ[setting]
        try:return cls(**values)
        except ValueError:raise ValueError('Invalid Career model configuration. Check AI_ENABLED, CAREER_LLM_BASE_URL, CAREER_LLM_RESPONSE_MODE, CAREER_LLM_TOKEN_PARAMETER, CAREER_LLM_API_KEY, CAREER_LLM_ALLOW_HTTP, CAREER_LLM_MODEL and AI task limits.') from None


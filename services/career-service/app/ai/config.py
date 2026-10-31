"""Server-only settings. A missing key leaves previews usable."""
import os
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


REASONING_MODEL='gemini-3.5-flash-lite'


class AISettings(BaseModel):
    """OpenAI-compatible adapter configuration; credentials remain server-only."""
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool = False
    provider: str = Field(default='gemini', min_length=1, max_length=80)
    base_url: str = 'https://generativelanguage.googleapis.com/v1beta/openai'
    model: str = Field(default=REASONING_MODEL, min_length=1, max_length=160)
    api_key: SecretStr = SecretStr('')
    response_mode: Literal['json_object', 'json_schema', 'json_schema_strict'] = 'json_schema'
    token_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_tokens'
    timeout_seconds: float = Field(default=45, ge=1, le=300)
    retries: int = Field(default=1, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, ge=128, le=8192)
    context_tokens: int = Field(default=65536, ge=2048, le=262144)

    @model_validator(mode='after')
    def valid_provider(self):
        if self.provider!='local' and self.timeout_seconds>60:
            raise ValueError('Cloud model request timeouts cannot exceed 60 seconds.')
        p = urlsplit(self.base_url)
        if p.scheme not in (('http','https') if self.provider=='local' else ('https',)) or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('The model API base URL requires HTTPS (HTTP is allowed only for the local provider), without credentials/query.')
        if self.enabled and (not self.model.strip() or self.provider!='local' and not self.api_key.get_secret_value().strip()):
            raise ValueError('Enabled AI requires CAREER_LLM_MODEL and CAREER_LLM_API_KEY.')
        return self

    @classmethod
    def from_env(cls):
        """Load the single configured model used by every Career stage."""
        # An explicitly empty canonical key overrides the deprecated alias.
        provider=os.getenv('CAREER_LLM_PROVIDER','gemini').strip()
        defaults={'gemini':('https://generativelanguage.googleapis.com/v1beta/openai',REASONING_MODEL,'json_schema'),
                  'deepseek':('https://api.deepseek.com/v1','deepseek-flash','json_object'),
                  'local':('http://host.docker.internal:11434/v1','deepseek-r1:1.5b','json_schema_strict'),
                  'compatible':('https://api.deepseek.com/v1','deepseek-flash','json_object')}
        if provider not in defaults:raise ValueError('Invalid CAREER_LLM_PROVIDER. Use local, deepseek, compatible or gemini.')
        base,model,mode=defaults[provider]
        key=os.getenv('CAREER_LLM_API_KEY',os.getenv('GEMINI_API_KEY','') if provider=='gemini' else '').strip()
        values={'api_key':key,'enabled':os.getenv('AI_ENABLED','true' if key else 'false'),
                'provider':provider,'base_url':os.getenv('CAREER_LLM_BASE_URL','').strip() or base,
                'model':os.getenv('CAREER_LLM_MODEL',model).strip(),
                'response_mode':os.getenv('CAREER_LLM_RESPONSE_MODE','').strip() or mode,
                'token_parameter':os.getenv('CAREER_LLM_TOKEN_PARAMETER','max_tokens').strip(),
                'context_tokens':16384 if provider=='local' else 65536}
        for field in ('timeout_seconds','retries','max_output_tokens','context_tokens'):
            setting='AI_'+field.upper()
            if setting in os.environ:
                if field=='context_tokens' and not os.environ[setting].strip():continue
                values[field]=os.environ[setting]
        if provider=='local':values['timeout_seconds']=os.getenv('CAREER_LOCAL_TIMEOUT_SECONDS','45')
        try:return cls(**values)
        except ValueError:raise ValueError('Invalid Career model configuration. Check AI_ENABLED, CAREER_LLM_PROVIDER, CAREER_LLM_BASE_URL, CAREER_LLM_RESPONSE_MODE, CAREER_LLM_TOKEN_PARAMETER, CAREER_LLM_API_KEY, CAREER_LLM_MODEL, CAREER_LOCAL_TIMEOUT_SECONDS and AI task limits.') from None


class GeminiSettings(AISettings):
    """Named Gemini settings for production composition."""
    reasoning_from_env = classmethod(AISettings.from_env.__func__)

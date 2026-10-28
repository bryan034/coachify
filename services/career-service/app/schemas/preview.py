from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

MAX_TEXT = 20_000  # Temporary CV previews keep their existing limit.
MAX_JD_TEXT = 8_000
MAX_FILE = 10 * 1024 * 1024
MAX_BODY = MAX_FILE + 64 * 1024


class UrlInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=2048)


class ImportErrorView(BaseModel):
    detail: str


class Preview(BaseModel):
    kind: Literal['url', 'document']
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    source_name: str
    source_url: str | None = None
    notices: list[str] = Field(default_factory=list)


class JDPreview(Preview):
    text: str = Field(min_length=1, max_length=MAX_JD_TEXT)

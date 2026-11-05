"""Reviewed employer board registry; user input cannot select arbitrary provider origins."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from app.schemas import Industry


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['greenhouse', 'lever', 'ashby']
    board: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    company: str = Field(min_length=1, max_length=120)
    industry: Industry
    enabled: bool = True


def load_sources(path=Path(__file__).with_name('sources.json')):
    rows = TypeAdapter(list[Source]).validate_python(json.loads(Path(path).read_text()))
    if len({(r.provider, r.board) for r in rows}) != len(rows):
        raise ValueError('sources.json lists a board twice.')
    return [r.model_dump() for r in rows if r.enabled]


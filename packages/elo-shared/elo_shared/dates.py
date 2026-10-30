"""Sourced job dates: full dates normalize, partial/ranged wording remains text."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class JobDate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['application_deadline','interview','job_start']
    text: str=Field(min_length=1,max_length=120)
    evidence: str=Field(min_length=1,max_length=600)
    date: str|None=None
    @model_validator(mode='after')
    def normalize(self):
        self.date=None
        for pattern in ('%Y-%m-%d','%d %B %Y','%d %b %Y','%B %d, %Y','%b %d, %Y'):
            try: self.date=datetime.strptime(self.text.strip(),pattern).date().isoformat(); break
            except ValueError: pass
        if self.text.casefold() not in self.evidence.casefold(): raise ValueError('Date wording needs exact supporting evidence.')
        return self

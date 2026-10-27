"""Bounded Gemini public research configuration."""
import os
from app.ai.config import REASONING_MODEL
from pydantic import BaseModel,ConfigDict,Field

class OpportunitySettings(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    enabled:bool=True
    gemini_model:str=Field(default=REASONING_MODEL,min_length=1,max_length=160)
    max_searches:int=Field(default=2,ge=1,le=4)
    max_followups:int=Field(default=1,ge=0,le=2)
    concurrency:int=Field(default=3,ge=1,le=3)
    timeout_seconds:float=Field(default=30,ge=1,le=40)
    retries:int=Field(default=1,ge=0,le=2)
    schema_repairs:int=Field(default=1,ge=0,le=2)
    evidence_tokens:int=Field(default=8192,ge=256,le=32768)
    freshness_hours:int=Field(default=168,ge=1,le=720)
    incomplete_hours:int=Field(default=1,ge=1,le=24)
    run_seconds:int=Field(default=300,ge=60,le=600)
    @classmethod
    def from_env(cls):
        try:return cls(**{key:os.environ['OPPORTUNITY_'+key.upper()] for key in cls.model_fields if key!='gemini_model' and 'OPPORTUNITY_'+key.upper() in os.environ})
        except ValueError:raise ValueError('Invalid Opportunity Intelligence settings. Check OPPORTUNITY_* server configuration.') from None

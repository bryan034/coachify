"""Bounded public research configuration."""
import os
from app.ai.config import REASONING_MODEL
from pydantic import BaseModel,ConfigDict,Field

class OpportunitySettings(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    enabled:bool=True
    model:str=Field(default=REASONING_MODEL,min_length=1,max_length=160)
    topic_searches:int=Field(default=2,ge=1,le=4)
    run_searches:int=Field(default=8,ge=1,le=200)
    concurrency:int=Field(default=3,ge=1,le=3)
    timeout_seconds:float=Field(default=30,ge=1,le=40)
    retries:int=Field(default=1,ge=0,le=2)
    schema_repairs:int=Field(default=1,ge=0,le=2)
    evidence_tokens:int|None=Field(default=None,ge=256)
    freshness_hours:int=Field(default=168,ge=1,le=720)
    incomplete_hours:int=Field(default=1,ge=1,le=24)
    run_seconds:int=Field(default=300,ge=60,le=600)
    token_budget:int=Field(default=230000,ge=100000,le=5000000)
    @classmethod
    def from_env(cls):
        values={key:os.environ['OPPORTUNITY_'+key.upper()] for key in cls.model_fields if key!='model' and 'OPPORTUNITY_'+key.upper() in os.environ}
        if not values.get('evidence_tokens','0').strip():values.pop('evidence_tokens')
        try:return cls(**values)
        except ValueError:raise ValueError('Invalid Opportunity Intelligence settings. Check OPPORTUNITY_* server configuration.') from None

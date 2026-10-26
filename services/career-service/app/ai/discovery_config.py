"""Optional server-side discovery bounds; no additional provider credentials."""
import os
from pydantic import BaseModel,ConfigDict,Field

class DiscoverySettings(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    target_listings:int=Field(default=10,ge=1,le=20)
    max_listings:int=Field(default=20,ge=10,le=30)
    target_employers:int=Field(default=5,ge=1,le=10)
    max_followups:int=Field(default=2,ge=0,le=2)
    freshness_hours:int=Field(default=168,ge=1,le=720)

    @classmethod
    def from_env(cls):
        try:return cls(**{key:os.environ['DISCOVERY_'+key.upper()] for key in cls.model_fields if 'DISCOVERY_'+key.upper() in os.environ})
        except ValueError:raise ValueError('Invalid career discovery configuration. Check DISCOVERY_* settings.') from None

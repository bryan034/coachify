"""About the role digest: short cited bullets per card, summarised from the goal and saved research."""
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel,ConfigDict,Field,StringConstraints


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')


BulletText=Annotated[str,StringConstraints(strip_whitespace=True,min_length=2,max_length=160)]


class Bullet(Model):
    text:BulletText
    # Card item refs: req:<requirement_id>, summary, resp:<index>, or a research finding_id.
    refs:list[str]=Field(min_length=1,max_length=4)


class CardDigest(Model):
    card_id:str=Field(max_length=60)
    bullets:list[Bullet]=Field(min_length=1,max_length=5)


class GeneratedCard(Model):
    """A card no source filled: the model wrote it from the goal and research context. Never a sourced fact."""
    card_id:str=Field(max_length=60)
    bullets:list[BulletText]=Field(min_length=1,max_length=4)


class RoleSummary(Model):
    goal_id:str
    goal_version:int
    research_id:str|None=None
    generated_at:datetime
    cards:list[CardDigest]=Field(default_factory=list,max_length=24)
    generated:list[GeneratedCard]=Field(default_factory=list,max_length=24)


class SummaryCommand(Model):
    expected_version:int=Field(strict=True,ge=1)
    refresh:bool=False

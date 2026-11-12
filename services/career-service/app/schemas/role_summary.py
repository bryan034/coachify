"""About the role digest: short cited bullets per card, summarised from the goal and saved research."""
import re
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel,ConfigDict,Field,StringConstraints


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid')


BulletText=Annotated[str,StringConstraints(strip_whitespace=True,min_length=2,max_length=110)]
# A 2-6 word takeaway shown under the topic title; plain text, no markup.
Headline=Annotated[str,StringConstraints(strip_whitespace=True,min_length=2,max_length=60,pattern=r'^[^*]+$')]
# Bumped when the saved shape or style changes; older saved digests are regenerated.
FORMAT=2
BOLD=re.compile(r'\*\*(?=\S)([^*\n]{1,40}?)(?<=\S)\*\*')


def markup_issue(text):
    """Bullets may bold one to three short key terms with **…**; any other asterisk or markdown is rejected."""
    spans=BOLD.findall(text)
    rest=BOLD.sub('',text)
    if '*' in rest or re.search(r'[`#<>]|\]\(',rest):return 'unsupported_markup'
    if len(spans)>3:return 'too_much_bold'
    if spans and len(rest.strip())<len(''.join(spans)):return 'bold_dominates'
    return None


class Bullet(Model):
    text:BulletText
    # Card item refs: req:<requirement_id>, summary, resp:<index>, or a research finding_id.
    refs:list[str]=Field(min_length=1,max_length=4)


class CardDigest(Model):
    card_id:str=Field(max_length=60)
    headline:Headline|None=None
    bullets:list[Bullet]=Field(min_length=1,max_length=3)


class GeneratedCard(Model):
    """A card no source filled: the model wrote it from the goal and research context. Never a sourced fact."""
    card_id:str=Field(max_length=60)
    headline:Headline|None=None
    bullets:list[BulletText]=Field(min_length=1,max_length=3)


class RoleSummary(Model):
    goal_id:str
    goal_version:int
    format:int=FORMAT
    research_id:str|None=None
    generated_at:datetime
    cards:list[CardDigest]=Field(default_factory=list,max_length=24)
    generated:list[GeneratedCard]=Field(default_factory=list,max_length=24)


class SummaryCommand(Model):
    expected_version:int=Field(strict=True,ge=1)
    refresh:bool=False

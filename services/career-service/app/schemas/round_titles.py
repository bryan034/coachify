from typing import Annotated

from pydantic import Field, StringConstraints

from app.schemas.opportunity import MAX_ROUNDS, Model

TITLE_WORDS = 3
ShortTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r'^\S+(?: \S+){0,2}$')]
RoundKey = Annotated[str, Field(pattern=r'^(?:[1-9]|10)$')]


class RoundTitle(Model):
    round_number: int = Field(strict=True, ge=1, le=MAX_ROUNDS)
    title: ShortTitle


class RoundTitles(Model):
    titles: list[RoundTitle] = Field(min_length=1, max_length=MAX_ROUNDS)

"""A task's notes document: Word-like text plus inserted checkboxes and single-choice questions.

The document is plain structured data, never HTML, so nothing a user types is ever rendered as markup.
"""
from typing import Annotated, Literal
from pydantic import Field, StringConstraints, model_validator
from .base import Contract

MAX_BLOCKS = 300
MAX_TEXT = 20000
NoteId = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,40}$')]

class Run(Contract):
    text: str = Field(max_length=2000)
    bold: bool = False
    italic: bool = False
    underline: bool = False

class TextBlock(Contract):
    type: Literal['paragraph', 'heading', 'bullet', 'numbered']
    runs: list[Run] = Field(default_factory=list, max_length=100)

class CheckboxBlock(Contract):
    type: Literal['checkbox']
    checked: bool = False
    runs: list[Run] = Field(default_factory=list, max_length=100)

class ChoiceOption(Contract):
    id: NoteId
    text: str = Field(max_length=200)

class ChoiceBlock(Contract):
    type: Literal['choice']
    id: NoteId
    question: str = Field(default='', max_length=500)
    options: list[ChoiceOption] = Field(min_length=2, max_length=8)
    selected: NoteId | None = None

    @model_validator(mode='after')
    def known_selection(self):
        ids = [option.id for option in self.options]
        if len(set(ids)) != len(ids): raise ValueError('Choice options need distinct identifiers.')
        if self.selected is not None and self.selected not in ids: raise ValueError('The selected option must be one of the choices.')
        return self

Block = Annotated[TextBlock | CheckboxBlock | ChoiceBlock, Field(discriminator='type')]

class NotesDocument(Contract):
    blocks: list[Block] = Field(default_factory=list, max_length=MAX_BLOCKS)

    @model_validator(mode='after')
    def bounded(self):
        total = sum(len(run.text) for block in self.blocks for run in getattr(block, 'runs', []))
        total += sum(len(block.question) + sum(len(o.text) for o in block.options) for block in self.blocks if isinstance(block, ChoiceBlock))
        if total > MAX_TEXT: raise ValueError(f'Notes can hold up to {MAX_TEXT} characters.')
        ids = [block.id for block in self.blocks if isinstance(block, ChoiceBlock)]
        if len(set(ids)) != len(ids): raise ValueError('Each choice needs its own identifier.')
        return self

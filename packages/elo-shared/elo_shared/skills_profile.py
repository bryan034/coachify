"""Shared Profile-owned skills intake contract; model output is never a write patch."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from elo_shared.skill_groups import skill_groups, skill_subgroups

Area = Literal['work', 'project', 'education', 'interest']
Status = Literal['answered', 'unknown', 'skipped', 'not_applicable']
FieldName = Literal['company', 'location', 'role', 'description', 'dates', 'contribution',
                    'tools', 'complexity', 'independence', 'recency', 'frequency', 'outcome',
                    'limitations', 'institution', 'qualification', 'completion']
FIELDS = {
    'work': ('company', 'location', 'role', 'description', 'contribution'),
    'project': ('description', 'contribution'),
    'education': ('institution', 'qualification', 'completion'),
    'interest': ('description',),
}
SKILL_FIELDS = ('contribution', 'tools', 'complexity', 'independence', 'recency', 'frequency', 'outcome', 'limitations')
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*', mode='before')
    @classmethod
    def readable(cls, value, info):
        if isinstance(value, str):
            allowed = {'\n', '\t'} if info.field_name not in {'name', 'title', 'message_id', 'kind', 'status'} else set()
            if any((ord(char) < 32 and char not in allowed) or ord(char) == 127 for char in value):
                raise ValueError('Use readable text without control characters.')
        return value


class ProfileEvidence(Strict):
    message_id: Annotated[str, Field(min_length=1, max_length=150)]
    quote: Text


class IntakeField(Strict):
    status: Status
    value: Text | None = None
    evidence: list[ProfileEvidence] = Field(default_factory=list, max_length=4)

    @model_validator(mode='after')
    def supported_value(self):
        if self.status == 'answered' and (not self.value or not self.evidence):
            raise ValueError('An answered field needs a value and its source statement.')
        if self.status != 'answered' and self.value is not None:
            raise ValueError('Unknown, skipped and inapplicable fields have no value.')
        return self


from elo_shared.skills import resolve, MAPPING_VERSION

class ProfileSkill(Strict):
    canonical_skill_id:str|None=None
    skill_registry_version:str=MAPPING_VERSION
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Text
    evidence: list[ProfileEvidence] = Field(min_length=1, max_length=4)
    dimensions: dict[FieldName, IntakeField] = Field(default_factory=dict, max_length=8)

    @model_validator(mode='after')
    def skill_dimensions(self):
        self.canonical_skill_id=resolve(self.name)
        self.skill_registry_version=MAPPING_VERSION
        if set(self.dimensions) - set(SKILL_FIELDS):
            raise ValueError('Use skill evidence dimensions only.')
        return self


class ProfileEntry(Strict):
    id: UUID
    kind: Area
    title: Annotated[str, Field(min_length=1, max_length=200)]
    fields: dict[FieldName, IntakeField] = Field(default_factory=dict, max_length=16)
    skills: list[ProfileSkill] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def unique_skills(self):
        names = [skill.name.casefold() for skill in self.skills]
        if len(set(names)) != len(names):
            raise ValueError('Each skill appears once per experience.')
        return self


class SkillsProfile(Strict):
    version: int = Field(default=0, ge=0, strict=True)
    status: Literal['empty', 'draft', 'saved'] = 'empty'
    saved_at: str | None = None
    areas: dict[Area, Status] = Field(default_factory=dict, max_length=4)
    entries: list[ProfileEntry] = Field(default_factory=list, max_length=40)
    # Display categories by skill name, derived on read and never stored; see skill_groups.
    skill_groups: dict[str, str] = Field(default_factory=dict)
    skill_subgroups: dict[str,str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def display_groups(self):
        self.skill_groups = skill_groups((skill.name, None) for entry in self.entries for skill in entry.skills)
        self.skill_subgroups = skill_subgroups((skill.name,None) for entry in self.entries for skill in entry.skills)
        return self

    @model_validator(mode='after')
    def unique_entries(self):
        ids = [entry.id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError('Entry identifiers must be unique.')
        if any(status == 'answered' and not any(e.kind == area for e in self.entries)
               for area, status in self.areas.items()):
            raise ValueError('An answered area needs an experience; use unknown, skip or not applicable otherwise.')
        return self


class SkillsProfileWrite(Strict):
    expected_version: int = Field(ge=0, strict=True)
    mutation_id: UUID
    status: Literal['draft', 'saved'] = 'draft'
    areas: dict[Area, Status] = Field(default_factory=dict, max_length=4)
    entries: list[ProfileEntry] = Field(default_factory=list, max_length=40)

    @model_validator(mode='after')
    def unique_entries(self):
        SkillsProfile(entries=self.entries, areas=self.areas)
        return self

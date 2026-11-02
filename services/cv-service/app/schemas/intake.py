from uuid import UUID
from pydantic import Field
from elo_shared.skills_profile import Area, Status, FieldName, IntakeField, ProfileEvidence
from app.schemas.cv import StrictModel


class SkillProposal(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=1800)
    evidence: list[ProfileEvidence] = Field(default_factory=list, max_length=4)
    dimensions: dict[FieldName, IntakeField] = Field(default_factory=dict, max_length=8)


class EntryProposal(StrictModel):
    id: UUID | None = None
    kind: Area
    title: str = Field(min_length=1, max_length=200)
    title_evidence: str = Field(min_length=1, max_length=2000)
    fields: dict[FieldName, IntakeField] = Field(default_factory=dict, max_length=16)
    skills: list[SkillProposal] = Field(default_factory=list, max_length=12)


class AreaProposal(StrictModel):
    area: Area
    status: Status
    evidence: str = Field(min_length=1, max_length=2000)


class EntryRemoval(StrictModel):
    entry_id: UUID
    evidence: str = Field(min_length=1, max_length=2000)
    skill_name: str | None = Field(default=None, min_length=1, max_length=120)


class IntakeEvaluation(StrictModel):
    reply: str = Field(min_length=1, max_length=2000)
    entries: list[EntryProposal] = Field(default_factory=list, max_length=5)
    areas: list[AreaProposal] = Field(default_factory=list, max_length=4)
    removals: list[EntryRemoval] = Field(default_factory=list, max_length=5)

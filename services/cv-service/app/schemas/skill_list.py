"""The person's skills from every source, merged by skill identity."""
from typing import Literal
from pydantic import Field
from app.schemas.cv import StrictModel, SkillLevelInfo

Attribution = Literal['personal', 'team', 'observed', 'denied', 'unknown']
Assistance = Literal['independent', 'assisted', 'supervised', 'unknown']


class SkillListEvidence(StrictModel):
    quote: str
    location: str | None = None


class SkillListFact(StrictModel):
    field: str
    value: str | None
    status: str


class SkillListSource(StrictModel):
    kind: Literal['cv', 'chat', 'declaration'] = Field(description='cv: a saved CV item; chat: the Skills Profile built in chat; declaration: a manual capability.')
    id: str
    title: str | None = Field(default=None, description='The experience or profile entry title; absent for manual capabilities.')
    item_kind: str | None = None
    attribution: Attribution | None = None
    assistance: Assistance | None = None
    description: str | None = None
    draft: bool = False
    facts: list[SkillListFact] = Field(default_factory=list)
    evidence: list[SkillListEvidence] = Field(default_factory=list)


class ListedSkill(StrictModel):
    key: str = Field(description='Skill identity: the canonical skill ID, or the normalised name when the registry has none.')
    canonical_skill_id: str | None = None
    name: str
    level: SkillLevelInfo | None = Field(default=None, description='The strongest 1-10 level across sources, preferring rated over assumed levels.')
    application: Literal['guided_application', 'independent_application', 'complex_application'] | None = Field(
        default=None, description='Strongest supported application estimate from the CV review when no 1-10 level exists.')
    proficiency: str | None = None
    basis: Literal['level', 'application', 'proficiency', 'described', 'draft', 'declared', 'none'] = Field(
        description='What the displayed strength rests on, strongest first.')
    added_in_review: bool = False
    note: str | None = None
    sources: list[SkillListSource]


class SkillList(StrictModel):
    cv_id: str | None
    cv_version: int | None
    profile_version: int | None
    declarations_version: int | None
    unavailable: list[Literal['chat', 'declarations']] = Field(default_factory=list, description='Sources that could not be read; their skills are missing from this list.')
    skills: list[ListedSkill]
    skill_groups: dict[str, str] = Field(default_factory=dict)
    skill_subgroups: dict[str, str] = Field(default_factory=dict)

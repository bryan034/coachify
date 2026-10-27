"""Account-level declarations; CV evidence remains in its originating service."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CvMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cv_id: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
    item_id: Annotated[str, Field(min_length=1, max_length=100)]
    cv_version: Annotated[int, Field(strict=True, ge=0)]


class CapabilityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    mutation_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(min_length=1, max_length=2000)]
    mode: Literal["new", "distinct", "attach"]
    attach_to_id: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    cv_match: CvMatch | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def bounded_text(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Enter a text name and description.")
        value = value.strip()
        allowed = {"\n", "\t"} if info.field_name == "description" else set()
        if not value or any((ord(c) < 32 and c not in allowed) or ord(c) == 127 for c in value):
            raise ValueError("Enter nonblank text without control characters.")
        return value

    @model_validator(mode="after")
    def explicit_match(self):
        if self.mode == "attach" and bool(self.attach_to_id) == bool(self.cv_match):
            raise ValueError("Choose one existing declaration or CV item to attach to.")
        if self.mode != "attach" and self.attach_to_id is not None:
            raise ValueError("A declaration attachment requires attach mode.")
        if self.mode == "new" and self.cv_match is not None:
            raise ValueError("Choose attach or distinct for a matching CV item.")
        return self


class CapabilityAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    mutation_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
    declaration_id: Annotated[str, Field(min_length=1, max_length=80)]
    cv_match: CvMatch | None


SourceFingerprint = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class AttachmentHistory(BaseModel):
    at: datetime
    previous: CvMatch | None
    previous_source_fingerprint: SourceFingerprint | None = None
    attached_to: CvMatch | None
    attached_source_fingerprint: SourceFingerprint | None = None


class Contribution(BaseModel):
    id: str
    description: str
    created_at: datetime


class Declaration(BaseModel):
    id: str
    name: str
    description: str
    skill_id: str
    provenance: Literal["user_declared"]
    proficiency: None = None
    experience_months: None = None
    independence: None = None
    contributions: list[Contribution]
    attached_to: CvMatch | None = None
    attached_source_fingerprint: SourceFingerprint | None = None
    attachment_history: list[AttachmentHistory] = Field(default_factory=list, max_length=100)
    created_at: datetime
    updated_at: datetime


class CapabilityLimits(BaseModel):
    max_declarations: int = 100
    name: int = 120
    description: int = 2000
    max_contributions: int = 10


class CapabilityView(BaseModel):
    user_id: str
    version: int
    declarations: list[Declaration]
    limits: CapabilityLimits = Field(default_factory=CapabilityLimits)


class CapabilityError(BaseModel):
    detail: str
    code: str | None = None
    matches: list[Declaration] | None = None

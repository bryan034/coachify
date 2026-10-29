from typing import Literal
from pydantic import BaseModel
from app.schemas.cv import CapabilityInput, ConfirmedContext


class DeclarationLink(BaseModel):
    declaration_id: str
    status: Literal['standalone', 'current', 'changed', 'removed', 'unavailable', 'unverified']
    selected: bool
    current_cv_version: int | None


class DeclarationLinks(BaseModel):
    declarations_version: int
    links: list[DeclarationLink]


class SourceSnapshot(CapabilityInput):
    cv_version: int
    upload_profile_version: int
    declaration_links: list[DeclarationLink]


class AnalysisInput(BaseModel):
    schema_version: Literal['2'] = '2'
    capabilities: SourceSnapshot
    target: ConfirmedContext
    requires_consumer_revalidation: Literal[True] = True

from typing import Literal
from pydantic import BaseModel
from app.schemas.profile import SchoolCategory


class CategoryView(BaseModel):
    id: SchoolCategory
    label: str


class CountryView(BaseModel):
    code: str
    name: str


class InstitutionView(BaseModel):
    id: str
    name: str
    categories: list[SchoolCategory]
    country_code: str
    country: str
    domains: list[str]
    source: str


class InstitutionResults(BaseModel):
    items: list[InstitutionView]
    total: int
    offset: int
    limit: int
    snapshot_date: str
    coverage_note: str


class AuthConfigView(BaseModel):
    mode: Literal["google", "email", "local_test"]
    email_password_enabled: bool
    google_enabled: bool
    email_verification_required: bool = True

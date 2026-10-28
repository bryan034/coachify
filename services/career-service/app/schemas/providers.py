"""Public provider names; historical unsupported providers are not exposed."""
from typing import Annotated, Literal
from pydantic import BeforeValidator


def public_provider(value):
    return value if isinstance(value,str) and value in ('gemini','brave') else None


ResearchProvider = Annotated[Literal['gemini','brave'] | None, BeforeValidator(public_provider)]

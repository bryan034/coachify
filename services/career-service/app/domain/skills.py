"""Explicit versioned synonym maps; names alone never establish skill identity."""
from app.schemas.analysis import SkillId
from pydantic import TypeAdapter


def canonical_skill_id(name: str, category: str, aliases: dict[tuple[str, str], str]) -> str:
    key = (' '.join(category.casefold().split()), ' '.join(name.casefold().split()))
    if key not in aliases:
        raise ValueError('Unmapped skill: review it before publishing a canonical ID.')
    return TypeAdapter(SkillId).validate_python(aliases[key])

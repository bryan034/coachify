"""Small local reference directory; free-form profile values do not depend on it."""
import json
from functools import lru_cache
from pathlib import Path
from app.domain.schools import normalise


@lru_cache(maxsize=1)
def snapshot():
    return json.loads((Path(__file__).parents[1] / "data" / "employment.json").read_text())


def search(kind: str, query: str, limit: int):
    words = normalise(query).split()
    return [row for row in snapshot()[kind] if all(word in normalise(row["name"]) for word in words)][:limit]

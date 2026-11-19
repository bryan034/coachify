"""Small local reference directory; free-form profile values do not depend on it."""
import json
from functools import lru_cache
from pathlib import Path
from app.domain.schools import normalise


@lru_cache(maxsize=1)
def snapshot():
    return json.loads((Path(__file__).parents[1] / "data" / "employment.json").read_text())


@lru_cache(maxsize=1)
def _indexed_snapshot():
    data = snapshot()
    indexed = {}
    for kind, rows in data.items():
        if isinstance(rows, list) and all(isinstance(row, dict) and "name" in row for row in rows):
            entries = tuple((row, normalise(row["name"])) for row in rows)
            ordered = tuple(row for row, _ in sorted(entries, key=lambda item: item[1])) if kind == "companies" else tuple(rows)
            indexed[kind] = (entries, ordered)
    return data, indexed


def search(kind: str, query: str, limit: int):
    words = normalise(query).split()
    data = snapshot()
    cached_data, indexed = _indexed_snapshot()
    if data is cached_data and kind in indexed:
        entries, ordered = indexed[kind]
        if not words:
            return list(ordered[:limit])
        return [row for row, text in entries if all(word in text for word in words)][:limit]
    rows = data[kind]
    if kind == "companies" and not words:
        rows = sorted(rows, key=lambda row: normalise(row["name"]))
    return [row for row in rows if all(word in normalise(row["name"]) for word in words)][:limit]

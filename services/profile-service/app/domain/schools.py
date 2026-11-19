import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from app.schemas.profile import CATEGORY_LABELS


@lru_cache(maxsize=65536)
def normalise(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def snapshot():
    return json.loads((Path(__file__).parents[1] / "data" / "schools.json").read_text())


@lru_cache(maxsize=1)
def _indexed_snapshot():
    data = snapshot()
    by_category = {}
    for row in data["institutions"]:
        search_text = normalise(row["name"] + " " + " ".join(row.get("domains", [])))
        entry = (row, row["country_code"], search_text)
        for category in row["categories"]:
            by_category.setdefault(category, []).append(entry)
    return data, {key: tuple(entries) for key, entries in by_category.items()}


def categories():
    return [{"id": key, "label": label} for key, label in CATEGORY_LABELS.items()]


def search(category, query, country, offset, limit):
    data = snapshot()
    words = normalise(query).split()
    cached_data, by_category = _indexed_snapshot()
    if data is cached_data:
        entries = by_category.get(category, ())
        rows = [row for row, code, text in entries
                if (not country or country == code)
                and all(word in text for word in words)]
    else:
        rows = [r for r in data["institutions"] if category in r["categories"]
                and (not country or country == r["country_code"])
                and all(word in normalise(r["name"] + " " + " ".join(r.get("domains", []))) for word in words)]
    return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset,
            "limit": limit, "snapshot_date": data["snapshot_date"], "coverage_note": data["coverage_note"]}


@lru_cache(maxsize=1)
def _cached_countries():
    rows = snapshot()["institutions"]
    names = {r["country_code"]: r["country"] for r in rows if "university" in r["categories"]}
    return tuple({"code": code, "name": name} for code, name in sorted(names.items(), key=lambda x: x[1]))


def countries():
    data = snapshot()
    if data is _indexed_snapshot()[0]:
        return [dict(item) for item in _cached_countries()]
    rows = data["institutions"]
    names = {r["country_code"]: r["country"] for r in rows if "university" in r["categories"]}
    return [{"code": code, "name": name} for code, name in sorted(names.items(), key=lambda x: x[1])]


@lru_cache(maxsize=1)
def institution_index():
    return {row["id"]: row for row in snapshot()["institutions"]}


def institution_by_id(identifier):
    return institution_index().get(identifier)

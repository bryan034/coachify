import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from app.schemas.profile import CATEGORY_LABELS


def normalise(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def snapshot():
    return json.loads((Path(__file__).parents[1] / "data" / "schools.json").read_text())


def categories():
    return [{"id": key, "label": label} for key, label in CATEGORY_LABELS.items()]


def search(category, query, country, offset, limit):
    data = snapshot()
    words = normalise(query).split()
    rows = [r for r in data["institutions"] if category in r["categories"]
            and (not country or country == r["country_code"])
            and all(word in normalise(r["name"] + " " + " ".join(r.get("domains", []))) for word in words)]
    return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset,
            "limit": limit, "snapshot_date": data["snapshot_date"], "coverage_note": data["coverage_note"]}


def countries():
    rows = snapshot()["institutions"]
    names = {r["country_code"]: r["country"] for r in rows if "university" in r["categories"]}
    return [{"code": code, "name": name} for code, name in sorted(names.items(), key=lambda x: x[1])]

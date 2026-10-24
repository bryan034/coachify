"""Refresh public reference data explicitly; no external calls during app requests."""
import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1] / "app" / "data"
MOE_ID = "d_688b934f82c1059ed0a6993d2a829089"
HIPO_REVISION = "603e10f51b67c6553b9bca9aecc0db4c2417ed10"
MOE_URL = "https://data.gov.sg/api/action/datastore_search"
HIPO_URL = f"https://raw.githubusercontent.com/Hipo/university-domains-list/{HIPO_REVISION}/world_universities_and_domains.json"


def download_moe():
    records = []
    while True:
        headers = {"x-api-key": os.environ["DATA_GOV_SG_API_KEY"]} if os.getenv("DATA_GOV_SG_API_KEY") else {}
        response = requests.get(MOE_URL, params={"resource_id": MOE_ID, "limit": 500, "offset": len(records)}, headers=headers, timeout=60)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError("MOE download was unsuccessful")
        result = payload["result"]
        records.extend(result["records"])
        if len(records) >= result["total"]:
            return {"result": {"records": records, "total": result["total"]}}
        if not result["records"]:
            raise RuntimeError("Incomplete MOE download")


def build(moe, universities):
    if len(moe["result"]["records"]) != moe["result"]["total"] or not universities:
        raise ValueError("Incomplete input snapshots")
    rows = []
    for row in moe["result"]["records"]:
        level = row["mainlevel_code"]
        categories = []
        # Mixed primary/secondary schools use P1-S4 rather than S1.
        if "SECONDARY" in level or re.search(r"\bS[1-5]\b", level):
            categories.append("secondary")
        if "JUNIOR COLLEGE" in level or "JC" in level or "CENTRALISED" in level:
            categories.append("junior_college")
        if categories:
            rows.append({"name": row["school_name"].strip(), "categories": categories,
                         "country_code": "SG", "country": "Singapore", "domains": [], "source": "moe"})
    manual = json.loads((ROOT / "singapore-tertiary.json").read_text())
    rows.extend(manual)
    overridden = {r["name"].casefold() for r in manual}
    for row in universities:
        code = row["alpha_two_code"].strip().upper()
        name = row["name"].strip()
        if not name or not re.fullmatch("[A-Z]{2}", code):
            raise ValueError("Invalid university record")
        # The domains list also includes some non-university SG institutions.
        if code == "SG" and (name.casefold() in overridden or name == "Institute of Technical Education" or name == "Australian International School"):
            continue
        rows.append({"name": name, "categories": ["university"], "country_code": code,
                     "country": row["country"], "domains": sorted(set(row["domains"])), "source": "hipo"})
    unique = {}
    for row in rows:
        key = row["country_code"] + ":" + row["name"].casefold()
        row["id"] = "school_" + hashlib.sha256(key.encode()).hexdigest()[:24]
        if key in unique:
            unique[key]["categories"] = sorted(set(unique[key]["categories"] + row["categories"]))
            unique[key]["domains"] = sorted(set(unique[key]["domains"] + row["domains"]))
        else:
            unique[key] = row
    return {"snapshot_date": date.today().isoformat(),
            "coverage_note": "Suggestions from MOE and a community-maintained international directory. Not exhaustive, not accreditation verification; names may include former institutions. Unlisted institutions remain valid; this list is not an eligibility filter.",
            "sources": {"moe": {"url": f"https://data.gov.sg/datasets/{MOE_ID}/view", "licence": "Singapore Open Data Licence"},
                        "hipo": {"url": HIPO_URL, "revision": HIPO_REVISION, "licence": "MIT; see HIPO-LICENSE.txt"},
                        "ite": {"url": "https://www.ite.edu.sg/about-ite/colleges/"},
                        "moe-psei": {"url": "https://www.moe.gov.sg/post-secondary/overview"}},
            "institutions": sorted(unique.values(), key=lambda r: (r["name"].casefold(), r["country_code"]))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moe-file", type=Path)
    parser.add_argument("--universities-file", type=Path)
    args = parser.parse_args()
    moe = json.loads(args.moe_file.read_text()) if args.moe_file else download_moe()
    if args.universities_file:
        universities = json.loads(args.universities_file.read_text())
    else:
        response = requests.get(HIPO_URL, timeout=60)
        response.raise_for_status()
        universities = response.json()
    output = build(moe, universities)
    target = ROOT / "schools.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)
    print(f"Saved {len(output['institutions'])} institutions. Review the diff before committing.")

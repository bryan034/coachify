"""Validate an explicitly chosen CV source through its owning authenticated API."""
import json
import os
import re
import requests
from fastapi import HTTPException
from app.domain.capabilities import CapabilityConflict, skill_id


def validate_cv_match(match, name, authorization):
    base = os.getenv("CV_SERVICE_URL", "http://cv-service:8000").rstrip("/")
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(base + "/api/v1/cv/" + match.cv_id,
                             headers={"Authorization": authorization}, timeout=5,
                             allow_redirects=False, stream=True) as response:
                if response.status_code == 401:
                    raise HTTPException(401, "Your session ended. Sign in again.")
                if response.status_code in (403, 404):
                    raise CapabilityConflict("The matching CV is unavailable. Reload and review your draft.", "match_changed")
                if response.status_code != 200:
                    raise ValueError("CV unavailable")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 16 * 1024 * 1024:
                        raise ValueError("CV response too large")
                    chunks.append(chunk)
                cv = json.loads(b"".join(chunks))
        if not isinstance(cv, dict) or not isinstance(cv.get("items"), list):
            raise ValueError("Invalid CV response")
        item = next((row for row in cv["items"] if isinstance(row, dict) and row.get("id") == match.item_id), None)
        if (cv.get("id") != match.cv_id or cv.get("version") != match.cv_version or cv.get("status") != "ready"
            or not item or item.get("removed")):
            raise CapabilityConflict("The matching CV item changed or was removed. Reload and review your draft.", "match_changed")
        if not isinstance(item.get("skill_ids", []), list) or any(not isinstance(v, str) for v in item.get("skill_ids", [])):
            raise ValueError("Invalid CV skill identity")
        canonical = skill_id(name)
        supported = False
        if "skills" in cv:
            if not isinstance(cv["skills"], list): raise ValueError("Invalid effective skills")
            for skill in cv["skills"]:
                if not isinstance(skill, dict): raise ValueError("Invalid effective skill")
                if skill.get("skill_id") != canonical: continue
                if not isinstance(skill.get("item_ids"), list) or not isinstance(skill.get("sources"), list):
                    raise ValueError("Invalid effective skill source")
                supported = canonical in item.get("skill_ids", []) and match.item_id in skill["item_ids"] and any(
                    isinstance(source, dict) and source.get("item_id") == match.item_id
                    and source.get("attribution", "unknown") in {"personal", "unknown"}
                    for source in skill["sources"])
        else:
            # Compatibility for older source responses: only an explicit, standalone
            # skill with its canonical identity can establish the relationship.
            supported = (item.get("kind") == "skill" and skill_id(item.get("title", "")) == canonical
                and canonical in item.get("skill_ids", []) and item.get("provenance", "explicit") == "explicit"
                and not item.get("support_uncertain"))
        if not supported:
            raise CapabilityConflict("This CV item no longer supports that skill. Review its evidence or keep your declaration separate.", "match_changed")
        fingerprint = item.get("source_fingerprint")
        if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)):
            raise ValueError("Invalid source fingerprint")
        return {**item, "_attachment_fingerprint": fingerprint, "_matched_skill_id": canonical}
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(503, "CV source verification is unavailable. Keep your draft and retry.") from exc

"""Current CV review policy and non-destructive legacy snapshot upgrades."""
from copy import deepcopy

from app.domain.errors import Conflict

CURRENT_REVIEW_POLICY = {'scope': 'item', 'version': 1}


def validate_policy(value):
    return (isinstance(value, dict) and type(value.get('version')) is int
            and value['version'] == 1 and value.get('scope') in {'section', 'item'})


def effective_policy(value=None):
    """All accounts receive item scope; fail closed on an unknown stored policy."""
    if value is not None and not validate_policy(value):
        raise Conflict('The saved CV review policy is invalid. Your evidence is retained.')
    return deepcopy(CURRENT_REVIEW_POLICY)


def map_legacy_counts(document, source):
    """Follow only explicit same-CV source mappings, including later revisions."""
    counts = {key: min(value, 2) for key, value in (source or {}).items()
              if isinstance(key, str) and type(value) is int and value > 0}
    for entry in document.get('history', []):
        candidate = entry.get('candidate') or {}
        if (entry.get('operation') != 'reconcile' or entry.get('action') != 'accept_candidate'
                or candidate.get('source_cv_id') != document.get('_id')):
            continue
        for choice in entry.get('choices', []):
            old, target = choice.get('item_id'), choice.get('target_item_id')
            if target and old != target and old in counts:
                counts[target] = min(2, counts.get(target, 0) + counts.pop(old))
    return counts

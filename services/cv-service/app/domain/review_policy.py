"""Current CV review policy and non-destructive legacy snapshot upgrades."""
from copy import deepcopy

from app.domain.capabilities import digest
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
                # Explicitly mapped sources converging on one item reserve both allowances, capped at two.
                counts[target] = min(2, counts.get(target, 0) + counts.pop(old))
    return counts


def migrate_snapshot(document, previous, legacy_counts=None):
    """Upgrade a snapshot in an existing versioned write without changing receipts."""
    from app.conversation.interview_memory import durable_review_questions

    stored = document.get('review_policy_snapshot')
    if stored is not None and stored != previous:
        raise Conflict('Your review policy changed. Continue with the latest review.')
    current = effective_policy(previous)
    if previous and previous != current:
        ids = sorted(q['id'] for q in durable_review_questions(document))
        document.setdefault('review_policy_migrations', []).append({
            'from': deepcopy(previous), 'to': deepcopy(current),
            'question_count': len(ids), 'receipt_basis': digest(ids)})
    # Carry only bounded numeric legacy counts into the CV aggregate.
    if legacy_counts:
        known = {item['id'] for item in document.get('original_items', [])}
        counts = document.setdefault('review_legacy_counts', {})
        for item_id, count in map_legacy_counts(document, legacy_counts).items():
            if item_id in known and type(count) is int and count > 0:
                existing = counts.get(item_id, 0)
                counts[item_id] = max(existing if type(existing) is int and existing >= 0 else 0, min(count, 2))
    document['review_policy_snapshot'] = current
    return current

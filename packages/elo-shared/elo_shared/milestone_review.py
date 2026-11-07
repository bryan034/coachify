"""Conservative review of removed roadmap work without modifying saved data."""
from datetime import datetime


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo and result.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def removal_needs_review(task, outcome, has_active_members):
    """Check for a later self-report while retaining the removal tombstone.

    Missing or ambiguous times, pending review, and an empty milestone fail
    closed. Either self-reported demonstrated value can acknowledge a change;
    this function does not decide whether the milestone has been achieved.
    """
    if not task.get('removed'):
        return False
    if not has_active_members or not isinstance(outcome, dict):
        return True
    if (type(outcome.get('demonstrated')) is not bool or outcome.get('source') != 'self_reported'
            or outcome.get('definition_review_required') or outcome.get('membership_review_required')):
        return True
    removal = task.get('removal')
    if not isinstance(removal, dict):
        return True
    removed_at = _timestamp(removal.get('at'))
    reviewed_at = _timestamp(outcome.get('recorded_at'))
    return not (removed_at and reviewed_at and reviewed_at > removed_at)

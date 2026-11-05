"""Invalidate self-reported milestone outcomes when their task membership changes."""
import copy

from app.planning.tasks import ensure_tasks


def mark_membership_review(plan, keys):
    """Retain the old self-report but require review for changed milestones."""
    keys=set(keys)-{None}
    for milestone in plan.get('milestones', []):
        if milestone['key'] not in keys:
            continue
        outcome=milestone.get('outcome') or {}
        if outcome.get('demonstrated'):
            outcome['definition_review_required']=True
            outcome['membership_review_required']=True


def mark_plan_membership_changes(previous, plan, *, reset_unchanged=False):
    """Compare canonical active task identities without migrating either snapshot."""
    if not previous:
        return
    def membership(snapshot):
        tasks=ensure_tasks(copy.deepcopy(snapshot))
        groups={}
        for task in tasks:
            key=task.get('milestone_key')
            if key and not task.get('removed'):
                groups.setdefault(key,set()).add(task['id'])
        return groups
    before=membership(previous);after=membership(plan)
    keys={key for key in before.keys()|after.keys() if before.get(key,set())!=after.get(key,set())}
    mark_membership_review(plan, keys)
    if not reset_unchanged:
        return
    earlier={m['key']:m for m in previous.get('milestones',[])}
    for milestone in plan.get('milestones',[]):
        key=milestone['key'];prior=earlier.get(key)
        outcome=milestone.get('outcome') or {}
        old=(prior or {}).get('outcome') or {}
        if key in keys or not outcome.get('membership_review_required') or not prior or old.get('membership_review_required'):
            continue
        # Discarding every newly proposed member can restore the exact active
        # membership. Do not erase any pre-existing or definition-change review.
        outcome.pop('membership_review_required',None)
        if not old.get('definition_review_required') and prior.get('demonstrable_outcome')==milestone.get('demonstrable_outcome'):
            outcome.pop('definition_review_required',None)

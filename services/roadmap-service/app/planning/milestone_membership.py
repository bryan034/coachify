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


def mark_plan_membership_changes(previous, plan):
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

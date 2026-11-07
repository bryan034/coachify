"""A removal is reviewed only by a later explicit, unambiguous self-report."""
import copy
import pytest

from elo_shared.milestone_review import removal_needs_review


@pytest.mark.parametrize('demonstrated', [True, False])
def test_valid_later_self_report_acknowledges_removal_without_mutating_inputs(demonstrated):
    task={'removed':True,'removal':{'at':'2030-01-01T00:00:00Z','reason':'Synthetic'}}
    outcome={'source':'self_reported','demonstrated':demonstrated,'recorded_at':'2030-01-01T08:00:01+08:00'}
    original=copy.deepcopy((task,outcome))
    assert not removal_needs_review(task,outcome,True)
    assert (task,outcome)==original


@pytest.mark.parametrize('changes', [
    {'recorded_at':None}, {'recorded_at':'bad'}, {'recorded_at':42},
    {'recorded_at':'2030-01-01T00:00:00'},
    {'recorded_at':'2030-01-01T00:00:00+00:00'},
    {'recorded_at':'2029-12-31T23:59:59Z'},
    {'source':'generated'}, {'source':None}, {'demonstrated':None},
    {'demonstrated':1}, {'definition_review_required':True}, {'membership_review_required':True},
])
def test_ambiguous_or_unreviewed_evidence_keeps_warning(changes):
    task={'removed':True,'removal':{'at':'2030-01-01T00:00:00Z'}}
    outcome={'source':'self_reported','demonstrated':True,'recorded_at':'2030-01-02T00:00:00Z',**changes}
    assert removal_needs_review(task,outcome,True)


@pytest.mark.parametrize('removal', [None, {}, {'at':None}, {'at':'bad'}, {'at':42}, {'at':'2030-01-01T00:00:00'}])
def test_unknown_removal_time_keeps_warning(removal):
    task={'removed':True,'removal':removal}
    outcome={'source':'self_reported','demonstrated':True,'recorded_at':'2030-01-02T00:00:00Z'}
    assert removal_needs_review(task,outcome,True)


def test_empty_milestone_and_missing_outcome_cannot_clear_removal():
    task={'removed':True,'removal':{'at':'2030-01-01T00:00:00Z'}}
    outcome={'source':'self_reported','demonstrated':True,'recorded_at':'2030-01-02T00:00:00Z'}
    assert removal_needs_review(task,outcome,False)
    assert removal_needs_review(task,None,True)
    assert not removal_needs_review({'removed':False},None,False)

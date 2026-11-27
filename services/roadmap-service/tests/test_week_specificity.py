"""A planned week fills the user's hours across the week with labelled, specific tasks. All data is synthetic."""
from datetime import date
import pytest
from pydantic import ValidationError
from test_backend_review import CONFIG, outline_data, week_errors
from test_placement import placer
from test_planner_flow import task, week_draft
from app.planning.weeks import check_week
from app.schemas.weeks import WeekDraft, WeekTask

TARGET={'week_start':'2030-01-14','target_minutes':300}
def errors_with_scope(output,scope):
    return check_week(WeekDraft.model_validate(output),outline_data(),CONFIG,None,[],[],TARGET,scope)

def test_a_week_fills_the_weekly_hours_even_when_the_milestone_estimate_is_smaller():
    assert errors_with_scope(week_draft([task('a','Build the expense API',280)]),{'m1':60})==[]
    short=errors_with_scope(week_draft([task('a','Build the expense API',60)]),{'m1':60})
    assert any("240 minutes under the user's weekly hours" in error for error in short)

def test_every_generated_task_says_what_it_is_for():
    item=week_draft([task('a','Build the expense API')])['tasks'][0]
    assert WeekTask.model_validate(item).label=='Synthetic project'
    item.pop('label')
    with pytest.raises(ValidationError):WeekTask.model_validate(item)

def test_leetcode_practice_must_name_each_problem_by_number():
    vague=week_draft([task('a','Solve LeetCode array problems',280)])
    assert any('LeetCode without naming problems' in error for error in week_errors(vague))
    named=week_draft([task('a','Solve LeetCode array problems',280,materials=['LeetCode 1. Two Sum','LeetCode 49. Group Anagrams'])])
    assert week_errors(named)==[]

EVERY_EVENING=[{'day':day,'start_time':'18:00','duration_minutes':180} for day in range(7)]

def test_spread_work_uses_every_study_day_instead_of_packing_the_first():
    packed=placer(blocks=EVERY_EVENING,break_minutes_per_hour=0)
    assert sorted({slot['date'] for slot in packed.place(420)})==['2030-01-14','2030-01-15','2030-01-16']
    spread=placer(blocks=EVERY_EVENING,break_minutes_per_hour=0);spread.spread(420)
    days=[slot['date'] for slot in spread.place_spread(240)+spread.place_spread(180)]
    assert sorted(days)==[date(2030,1,day).isoformat() for day in range(14,21)]

def test_spread_work_still_places_when_the_even_shares_are_full():
    spread=placer(blocks=EVERY_EVENING,break_minutes_per_hour=0);spread.spread(60)
    schedule=spread.place_spread(600)
    assert sum(slot['duration_minutes'] for slot in schedule)==600 and spread.share==60

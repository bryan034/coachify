"""Deterministic session placement: session length, breaks, windows and limits, with no model involved."""
from datetime import date, datetime, timezone
from app.planning.capacity import Placer, session_lengths
from app.planning.placement import week_target
from app.schemas.roadmap import PlannerConfig

NOW=datetime(2030,1,13,0,0,tzinfo=timezone.utc)  # Sunday 08:00 in Singapore; the week of Monday the 14th is ahead.
WEEK=(date(2030,1,14),date(2030,1,21))
EVENING={'day':0,'start_time':'18:00','duration_minutes':180}
def config(**changes):
    return PlannerConfig.model_validate({'start_date':'2030-01-07','target_date':'2030-02-10','time_zone':'Asia/Singapore','weekly_minutes':600,
        'blocks':[EVENING],'preferred_session_minutes':60,**changes})
def placer(reserved=(),**changes):
    return Placer(config(**changes),NOW,list(reserved),*WEEK)
def times(schedule):
    return [(s['date'][-2:],s['start_time'],s['duration_minutes']) for s in schedule]

def test_work_longer_than_a_session_is_split_into_even_sessions():
    settings=config()
    assert session_lengths(60,settings)==[60] and session_lengths(45,settings)==[45]
    assert session_lengths(130,settings)==[45,45,40] and session_lengths(61,settings)==[35,26]
    assert session_lengths(200,config(preferred_session_minutes=90))==[70,70,60]

def test_sessions_never_exceed_the_limit_and_each_is_followed_by_ten_minutes_per_hour():
    assert times(placer().place(150))==[('14','18:00',50),('14','19:00',50),('14','20:00',50)]
    assert times(placer().place(120))==[('14','18:00',60),('14','19:10',60)]
    assert times(placer(break_minutes_per_hour=0).place(180))==[('14','18:00',60),('14','19:00',60),('14','20:00',60)]
    long=placer(preferred_session_minutes=90,blocks=[{**EVENING,'duration_minutes':240}])
    assert times(long.place(180))==[('14','18:00',90),('14','19:45',90)]

def test_work_that_cannot_fit_is_not_half_placed():
    filled=placer()
    assert filled.place(400) is None and not any(filled.busy.values()) and not any(filled.week_used.values())
    assert times(filled.place(60))==[('14','18:00',60)]

def test_saved_sessions_keep_a_break_on_both_sides():
    saved=[{'date':'2030-01-14','start_time':'19:00','duration_minutes':60}]
    split=placer(saved).place(60)
    assert sum(slot['duration_minutes'] for slot in split)==60
    assert all(slot['duration_minutes']<=60 for slot in split)
    assert split[-1]['start_time']=='20:10'
    assert times(placer(saved).place(45))==[('14','18:00',45)]
    assert times(placer(saved).place(50))==[('14','18:00',50)]
    assert times(placer(saved,break_minutes_per_hour=0).place(60))==[('14','18:00',60)]

def test_extra_time_is_used_only_when_study_blocks_are_full_and_spreads_over_quiet_days():
    extra=placer(allow_overflow=True)
    first=[times(extra.place(60))[0] for _ in range(2)]
    assert first==[('14','18:00',60),('14','19:10',60)]
    later=[times(extra.place(60))[0] for _ in range(3)]
    assert later==[('15','09:00',60),('16','09:00',60),('17','09:00',60)]
    assert placer().place(60) and placer(blocks=[]).place(60) is None

def test_blackouts_and_zero_hour_periods_are_never_scheduled():
    rules=[{'frequency':'once','start_date':'2030-01-14'},{'frequency':'once','start_date':'2030-01-15','start_time':'09:00','end_time':'12:00'}]
    blocked=placer(allow_overflow=True,blackouts=rules,reduced_periods=[{'start_date':'2030-01-16','end_date':'2030-01-16','weekly_minutes':0}])
    assert times(blocked.place(60))==[('15','12:00',60)]
    assert times(blocked.place(60))==[('17','09:00',60)]

def test_daily_limit_rest_days_weekly_hours_and_notice_are_enforced():
    daily=placer(allow_overflow=True,max_daily_minutes=60)
    assert [times(daily.place(60))[0][0] for _ in range(3)]==['14','15','16']
    resting=placer(allow_overflow=True,blocks=[],rest_days_per_week=5)
    days={times(resting.place(60))[0][0] for _ in range(6)}
    assert len(days)==2
    capped=placer(allow_overflow=True,weekly_minutes=120)
    assert capped.place(60) and capped.place(60) and capped.place(25) is None
    soon=Placer(config(allow_overflow=True,blocks=[],lead_minutes=180),NOW,[],date(2030,1,13),date(2030,1,14))
    assert times(soon.place(60))==[('13','11:00',60)]

def test_the_week_target_is_the_agreed_hours_unless_less_can_be_placed_and_says_why():
    full=week_target(config(allow_overflow=True,weekly_minutes=300),NOW,[],*WEEK)
    assert (full['target_minutes'],full['shortfall_minutes'],full['reasons'])==(300,0,[])
    tight=week_target(config(weekly_minutes=300),NOW,[],*WEEK)
    assert tight['target_minutes']==160 and [r['code'] for r in tight['reasons']]==['limited_time'] and '2h 40m' in tight['reasons'][0]['message']
    partial=week_target(config(weekly_minutes=300,target_date='2030-01-14'),NOW,[],date(2030,1,14),date(2030,1,15))
    assert [r['code'] for r in partial['reasons']]==['partial_week'] and partial['target_minutes']==160
    reduced=week_target(config(allow_overflow=True,weekly_minutes=300,reduced_periods=[{'start_date':'2030-01-15','end_date':'2030-01-16','weekly_minutes':120}]),NOW,[],*WEEK)
    assert reduced['target_minutes']==120 and [r['code'] for r in reduced['reasons']]==['reduced_availability']
    saved=[{'date':'2030-01-14','start_time':'18:00','duration_minutes':60}]
    busy=week_target(config(allow_overflow=True,weekly_minutes=300),NOW,saved,*WEEK)
    assert busy['target_minutes']==240 and [r['code'] for r in busy['reasons']]==['saved_work']

def test_capacity_search_is_bounded_by_daily_limits_and_occupied_rest_days():
    plan=placer(allow_overflow=True,blocks=[],preferred_session_minutes=480,
        weekly_minutes=10080,max_daily_minutes=60,rest_days_per_week=6)
    calls=0;find=plan.find
    def counted(*args,**kwargs):
        nonlocal calls
        calls+=1
        return find(*args,**kwargs)
    plan.find=counted
    assert plan.room()==60
    assert calls<200
    assert not any(plan.busy.values()) and not any(plan.day_used.values())

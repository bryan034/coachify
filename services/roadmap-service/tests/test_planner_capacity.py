from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError
from app.planning.capacity import Capacity, add_duration, matched_duration
from app.schemas.roadmap import Duration, PlannerConfig

NOW=datetime(2030,1,9,0,0,tzinfo=timezone.utc)
BLOCKS=[{'day':0,'start_time':'19:00','duration_minutes':120,'kind':'preferred'},
    {'day':2,'start_time':'19:00','duration_minutes':90,'kind':'preferred'},
    {'day':5,'start_time':'10:00','duration_minutes':120,'kind':'preferred'},
    {'day':5,'start_time':'11:00','duration_minutes':120,'kind':'preferred'},
    {'day':6,'start_time':'09:00','duration_minutes':120,'kind':'backup'}]
def config(**changes):
    return PlannerConfig.model_validate({'start_date':'2030-01-09','target_date':'2030-01-27','time_zone':'Asia/Singapore','weekly_minutes':300,
        'blocks':BLOCKS,'blackouts':[{'frequency':'once','start_date':'2030-01-12'}],'break_minutes_per_hour':0,**changes})

def test_partial_week_blackout_overlap_and_cap_are_calculated_from_real_dates():
    report=Capacity(config(),NOW).report()
    assert report['can_generate'] and report['calendar']=={'days':19,'weeks':2,'extra_days':5,'label':'2 weeks, 5 days','partial_first_week':True}
    assert [(w['preferred_minutes'],w['overflow_minutes'],w['usable_minutes']) for w in report['weeks']]==[(90,0,90),(300,0,300),(300,0,300)]
    assert report['study']=={'preferred_minutes':690,'overflow_minutes':0,'usable_minutes':690}
    assert report['weeks'][0]['partial'] and not report['weeks'][1]['partial']
    assert report['first_planning_week']=='2030-01-07'

def test_retired_backup_blocks_are_dropped_unless_they_were_switched_on():
    assert len(config().blocks)==4 and all(not hasattr(block,'kind') for block in config().blocks)
    kept=config(use_backup=True)
    assert len(kept.blocks)==5 and 'use_backup' not in kept.model_dump()
    assert Capacity(kept,NOW).report()['study']=={'preferred_minutes':810,'overflow_minutes':0,'usable_minutes':810}

def test_extra_time_fills_only_what_study_blocks_cannot_and_respects_blackouts():
    report=Capacity(config(allow_overflow=True),NOW).report()
    assert [(w['preferred_minutes'],w['overflow_minutes'],w['usable_minutes']) for w in report['weeks']]==[(90,210,300),(300,0,300),(300,0,300)]
    capacity=Capacity(config(allow_overflow=True),NOW)
    assert capacity.days[date(2030,1,12)]=={'preferred':[],'overflow':[]}
    assert capacity.days[date(2030,1,10)]['overflow']==[(540,1380)]
    timed=Capacity(config(allow_overflow=True,blackouts=[{'frequency':'once','start_date':'2030-01-10','start_time':'12:00','end_time':'14:00'}]),NOW)
    assert timed.days[date(2030,1,10)]['overflow']==[(540,720),(840,1380)]

def test_breaks_session_length_daily_limit_and_rest_days_reduce_what_a_week_can_hold():
    evening=[{'day':d,'start_time':'18:00','duration_minutes':180} for d in range(7)]
    week=lambda **changes:Capacity(config(blocks=evening,blackouts=[],weekly_minutes=3000,start_date='2030-01-14',target_date='2030-01-20',**changes),NOW).report()['weeks'][0]['usable_minutes']
    assert week()==7*180
    assert week(break_minutes_per_hour=10)==7*160
    assert week(break_minutes_per_hour=10,preferred_session_minutes=90)==7*165
    assert week(max_daily_minutes=60)==7*60
    assert week(rest_days_per_week=2)==5*180
    report=Capacity(config(blocks=evening[:1],blackouts=[],start_date='2030-01-14',target_date='2030-01-27'),NOW).report()
    assert report['can_generate'] and [n['code'] for n in report['notices']]==['windows_below_target']

def test_a_reduced_period_lowers_its_weeks_and_a_zero_hour_period_closes_its_days():
    evening=[{'day':d,'start_time':'18:00','duration_minutes':120} for d in range(7)]
    periods=[{'start_date':'2030-01-16','end_date':'2030-01-17','weekly_minutes':120},{'start_date':'2030-01-22','end_date':'2030-01-23','weekly_minutes':0}]
    base=dict(blocks=evening,blackouts=[],weekly_minutes=600,start_date='2030-01-14',target_date='2030-01-27',reduced_periods=periods)
    report=Capacity(config(**base),NOW).report()
    assert [(w['weekly_cap'],w['usable_minutes'],w['reduced']) for w in report['weeks']]==[(120,120,True),(600,600,False)]
    assert Capacity(config(**base),NOW).days[date(2030,1,22)]['preferred']==[]
    assert 'reduced_periods' in [n['code'] for n in report['notices']]
    ignored=Capacity(config(**base,apply_reduced_periods=False),NOW).report()
    assert [(w['weekly_cap'],w['reduced']) for w in ignored['weeks']]==[(600,False),(600,False)]

def test_a_week_can_start_on_another_day():
    report=Capacity(config(week_start_day=6,blackouts=[]),NOW).report()
    assert [w['week_start'] for w in report['weeks']]==['2030-01-06','2030-01-13','2030-01-20','2030-01-27']
    assert report['first_planning_week']=='2030-01-06'

def test_time_already_passed_today_is_not_counted():
    evening=datetime(2030,1,9,11,30,tzinfo=timezone.utc)
    assert Capacity(config(),evening).report()['weeks'][0]['usable_minutes']==60

def test_skipped_daylight_saving_hour_is_removed_and_a_repeated_hour_counts_once():
    block=[{'day':6,'start_time':'02:00','duration_minutes':120,'kind':'preferred'}]
    spring=Capacity(config(blocks=block,start_date='2030-03-10',target_date='2030-03-11',time_zone='America/New_York',blackouts=[]),NOW).report()
    assert spring['study']['usable_minutes']==60
    block=[{'day':6,'start_time':'00:30','duration_minutes':120,'kind':'preferred'}]
    autumn=Capacity(config(blocks=block,start_date='2030-11-03',target_date='2030-11-04',time_zone='America/New_York',blackouts=[]),NOW).report()
    assert autumn['study']['usable_minutes']==120

def test_invalid_inputs_are_reported_as_generation_blockers():
    codes=lambda **changes:[i['code'] for i in Capacity(config(**changes),NOW).report()['issues']]
    assert codes(target_date=None)==['missing_target']
    assert codes(target_date='2030-01-09')==['target_before_start']
    assert codes(start_date='2030-01-02')==['start_in_past']
    assert codes(target_date='2031-02-01')==['runway_too_long']
    assert codes(weekly_minutes=0)==['no_budget']
    assert codes(blocks=[])==['no_blocks']
    assert codes(blocks=[BLOCKS[-1]])==['no_blocks']
    assert codes(blocks=[BLOCKS[2]],target_date='2030-01-13')==['no_usable_time']

def test_start_defaults_to_today_and_duration_resolves_and_matches_the_target():
    report=Capacity(config(start_date=None,target_date=None,duration={'value':8,'unit':'weeks'}),NOW).report()
    assert report['resolved']['start_date']=='2030-01-09' and report['resolved']['target_date']=='2030-03-06'
    assert report['resolved']['matched_duration']=={'value':8,'unit':'weeks'}
    assert add_duration(date(2030,1,31),Duration(value=1,unit='months'))==date(2030,2,28)
    assert matched_duration(date(2030,1,31),date(2030,2,28))==Duration(value=4,unit='weeks')
    assert matched_duration(date(2030,1,15),date(2030,4,15))==Duration(value=3,unit='months')
    assert matched_duration(date(2030,1,15),date(2030,1,20)) is None

def test_completed_sessions_keep_their_time_and_count_against_that_week():
    session={'date':'2030-01-09','start_time':'19:00','duration_minutes':60}
    capacity=Capacity(config(weekly_minutes=100,blocks=[BLOCKS[1]],blackouts=[]),NOW,[session])
    assert capacity.days[date(2030,1,9)]['preferred']==[(1200,1230)]
    assert capacity.week_left(date(2030,1,7))==40
    assert capacity.report()['weeks'][0]['completed_minutes']==60 and capacity.report()['weeks'][0]['usable_minutes']==30

EVENING={'day':1,'start_time':'19:00','duration_minutes':120,'kind':'preferred'}
def usable(*rules,blocks=(EVENING,)):
    report=Capacity(config(blocks=list(blocks),start_date='2030-01-14',target_date='2030-02-24',weekly_minutes=600,blackouts=list(rules)),NOW).report()
    return [w['usable_minutes'] for w in report['weeks']]

def test_weekly_blackout_removes_the_chosen_weekdays_from_every_week():
    assert usable()==[120]*6
    assert usable({'frequency':'weekly','start_date':'2030-01-14','weekdays':[1]})==[0]*6
    assert usable({'frequency':'weekly','start_date':'2030-01-14','weekdays':[2]})==[120]*6

def test_weekly_interval_counts_from_the_start_week_and_end_date_stops_the_rule():
    assert usable({'frequency':'weekly','interval':2,'start_date':'2030-01-14','weekdays':[1]})==[0,120,0,120,0,120]
    assert usable({'frequency':'weekly','start_date':'2030-01-14','end_date':'2030-01-28','weekdays':[1]})==[0,0,120,120,120,120]
    assert usable({'frequency':'weekly','start_date':'2030-01-28','weekdays':[1]})==[120,120,0,0,0,0]

def test_daily_blackout_covers_a_range_and_honours_its_interval():
    assert usable({'frequency':'daily','start_date':'2030-01-15','end_date':'2030-01-22'})==[0,0,120,120,120,120]
    assert usable({'frequency':'daily','interval':14,'start_date':'2030-01-15'})==[0,120,0,120,0,120]

def test_monthly_blackout_repeats_on_the_day_and_clamps_to_short_months():
    assert usable({'frequency':'monthly','start_date':'2030-01-15'})==[0,120,120,120,120,120]
    assert usable({'frequency':'monthly','start_date':'2029-12-12'})==[120,120,120,120,0,120]
    assert usable({'frequency':'monthly','interval':3,'start_date':'2029-12-12'})==[120]*6
    capacity=Capacity(config(start_date='2030-01-14',target_date='2030-03-05',blocks=[{**EVENING,'day':3}],blackouts=[{'frequency':'monthly','start_date':'2030-01-31'}]),NOW)
    assert capacity.blackout_windows(date(2030,2,28))==[(0,1440)] and capacity.blackout_windows(date(2030,2,27))==[]

def test_a_time_slot_removes_only_its_overlap_and_a_whole_day_removes_everything():
    slot={'frequency':'weekly','start_date':'2030-01-14','weekdays':[1],'start_time':'20:00','end_time':'20:30'}
    capacity=Capacity(config(start_date='2030-01-14',target_date='2030-01-20',weekly_minutes=600,blocks=[EVENING],blackouts=[slot]),NOW)
    assert capacity.days[date(2030,1,15)]['preferred']==[(1140,1200),(1230,1260)]
    assert capacity.report()['weeks'][0]['usable_minutes']==90
    assert usable({**slot,'start_time':'08:00','end_time':'09:00'})==[120]*6

def test_a_slot_ending_at_2359_runs_through_midnight():
    late={'day':1,'start_time':'23:00','duration_minutes':60,'kind':'preferred'}
    rule={'frequency':'once','start_date':'2030-01-15','start_time':'23:30','end_time':'23:59'}
    capacity=Capacity(config(start_date='2030-01-14',target_date='2030-01-20',blocks=[late],blackouts=[rule]),NOW)
    assert capacity.days[date(2030,1,15)]['preferred']==[(1380,1410)]

def test_invalid_blackouts_block_generation_with_an_explanation_and_remove_nothing():
    cases=[({'frequency':'daily','start_date':'2030-01-20','end_date':'2030-01-15'},'ends before it starts'),
        ({'frequency':'once','start_date':'2030-01-15','start_time':'20:00'},'needs both a start and an end time'),
        ({'frequency':'once','start_date':'2030-01-15','start_time':'20:00','end_time':'19:00'},'must end after it starts'),
        ({'frequency':'weekly','start_date':'2030-01-15'},'needs at least one weekday')]
    for rule,message in cases:
        report=Capacity(config(start_date='2030-01-14',target_date='2030-01-20',blocks=[EVENING],blackouts=[{'frequency':'once','start_date':'2030-01-16'},rule]),NOW).report()
        assert not report['can_generate'] and [i['code'] for i in report['issues']]==['blackout_invalid']
        assert report['issues'][0]['message'].startswith('Blackout 2 ') and message in report['issues'][0]['message']
        assert report['weeks'][0]['usable_minutes']==120

def test_blackout_rule_fields_are_range_checked():
    for bad in ({'frequency':'hourly'},{'interval':0},{'weekdays':[7]},{'start_time':'25:00','end_time':'26:00'}):
        with pytest.raises(ValidationError):config(blackouts=[{'frequency':'once','start_date':'2030-01-15',**bad}])

@pytest.mark.parametrize('old',[{'buffer_percent':20},{'checkin_day':4},{'checkin_time':'18:00'},{'blackout_dates':['2030-01-12']}])
def test_settings_cannot_hold_removed_fields(old):
    with pytest.raises(ValidationError):PlannerConfig.model_validate({'time_zone':'Asia/Singapore',**old})

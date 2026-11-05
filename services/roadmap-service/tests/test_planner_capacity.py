from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError
from app.planning.capacity import Capacity, add_duration, matched_duration
from app.schemas.roadmap import Duration, PlannerConfig

# 2030-01-09 is a Wednesday; 08:00 in Singapore.
NOW=datetime(2030,1,9,0,0,tzinfo=timezone.utc)
BLOCKS=[{'day':0,'start_time':'19:00','duration_minutes':120,'kind':'preferred'},
    {'day':2,'start_time':'19:00','duration_minutes':90,'kind':'preferred'},
    {'day':5,'start_time':'10:00','duration_minutes':120,'kind':'preferred'},
    {'day':5,'start_time':'11:00','duration_minutes':120,'kind':'preferred'},
    {'day':6,'start_time':'09:00','duration_minutes':120,'kind':'backup'}]
def config(**changes):
    return PlannerConfig.model_validate({'start_date':'2030-01-09','target_date':'2030-01-27','time_zone':'Asia/Singapore','weekly_minutes':300,
        'blocks':BLOCKS,'blackouts':[{'frequency':'once','start_date':'2030-01-12'}],**changes})

def test_partial_week_blackout_overlap_cap_and_backup_are_calculated_from_real_dates():
    report=Capacity(config(),NOW).report()
    assert report['can_generate'] and report['calendar']=={'days':19,'weeks':2,'extra_days':5,'label':'2 weeks, 5 days','partial_first_week':True}
    # Week 1 only has Wednesday (90); Saturday is blacked out. Later weeks have 390 merged minutes, capped at 300.
    assert [(w['preferred_minutes'],w['backup_extra_minutes'],w['usable_minutes']) for w in report['weeks']]==[(90,120,90),(300,0,300),(300,0,300)]
    assert report['study']=={'preferred_minutes':690,'backup_extra_minutes':120,'usable_minutes':690}
    assert report['weeks'][0]['partial'] and not report['weeks'][1]['partial']
    assert report['first_planning_week']=='2030-01-07'

def test_enabling_backup_adds_only_the_extra_capacity_under_the_cap():
    report=Capacity(config(use_backup=True),NOW).report()
    assert report['study']=={'preferred_minutes':690,'backup_extra_minutes':120,'usable_minutes':810}

def test_overlapping_preferred_and_backup_blocks_count_once():
    blocks=[{'day':0,'start_time':'10:00','duration_minutes':60,'kind':'preferred'},{'day':0,'start_time':'10:30','duration_minutes':60,'kind':'backup'}]
    report=Capacity(config(blocks=blocks,start_date='2030-01-14',target_date='2030-01-20',use_backup=True,blackouts=[]),NOW).report()
    assert report['study']=={'preferred_minutes':60,'backup_extra_minutes':30,'usable_minutes':90}

def test_time_already_passed_today_is_not_counted():
    evening=datetime(2030,1,9,11,30,tzinfo=timezone.utc)  # 19:30 Wednesday in Singapore: 60 of the 90 minutes remain.
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
    assert codes(blocks=[BLOCKS[-1]])==['no_usable_time']

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

# Blackout rules, over the Monday 2030-01-14 to Sunday 2030-02-24 runway.
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
    # 2030-02-12 is a Tuesday: the 12th of each month from an earlier start.
    assert usable({'frequency':'monthly','start_date':'2029-12-12'})==[120,120,120,120,0,120]
    assert usable({'frequency':'monthly','interval':3,'start_date':'2029-12-12'})==[120]*6
    # The 31st falls back to 28 February 2030, a Thursday.
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

def test_saved_blackout_dates_are_read_as_one_off_rules():
    saved=PlannerConfig.model_validate({'time_zone':'Asia/Singapore','blackout_dates':['2030-01-12','2030-01-13']})
    assert [(r.frequency,r.start_date.isoformat()) for r in saved.blackouts]==[('once','2030-01-12'),('once','2030-01-13')]
    assert 'blackout_dates' not in saved.model_dump()

def test_buffer_is_reserved_each_week_and_reported_before_generation():
    report=Capacity(config(),NOW).report()
    assert [(w['usable_minutes'],w['planned_minutes'],w['buffer_minutes']) for w in report['weeks']]==[(90,72,18),(300,240,60),(300,240,60)]
    assert report['budget']=={'available_weeks':3,'eligible_minutes':690,'planned_minutes':552,'buffer_minutes':138}
    none=Capacity(config(buffer_percent=0),NOW).report()['budget']
    assert none['planned_minutes']==690 and none['buffer_minutes']==0
    half=Capacity(config(buffer_percent=50),NOW).report()['budget']
    assert half['planned_minutes']==345 and half['buffer_minutes']==345

def test_buffer_percentage_and_checkin_settings_are_validated_with_safe_defaults():
    saved=config()
    assert (saved.buffer_percent,saved.checkin_day,saved.checkin_time)==(20,4,'18:00')
    for bad in ({'buffer_percent':51},{'buffer_percent':-1},{'checkin_day':7},{'checkin_time':'25:00'}):
        with pytest.raises(ValidationError):config(**bad)

def test_buffer_rounds_up_so_the_plan_never_uses_reserved_minutes():
    report=Capacity(config(buffer_percent=33,weekly_minutes=100,blocks=[{'day':0,'start_time':'10:00','duration_minutes':100,'kind':'preferred'}],start_date='2030-01-14',target_date='2030-01-20',blackouts=[]),NOW).report()
    assert (report['weeks'][0]['planned_minutes'],report['weeks'][0]['buffer_minutes'])==(67,33)

def test_backup_adds_capacity_only_where_the_weekly_maximum_allows():
    report=Capacity(config(use_backup=True),NOW).report()
    # Week one has room, so backup adds 120. Weeks two and three are already capped at 300.
    assert [w['usable_minutes'] for w in report['weeks']]==[210,300,300]

def test_weeks_follow_the_plan_timezone_at_a_week_boundary():
    # Sunday 23:30 in New York is already Monday in Singapore.
    moment=datetime(2030,1,14,4,30,tzinfo=timezone.utc)
    late=[{'day':6,'start_time':'23:40','duration_minutes':20,'kind':'preferred'},{'day':0,'start_time':'09:00','duration_minutes':60,'kind':'preferred'}]
    york=Capacity(config(time_zone='America/New_York',start_date='2030-01-13',target_date='2030-01-20',blocks=late,blackouts=[]),moment).report()
    assert [w['week_start'] for w in york['weeks']]==['2030-01-07','2030-01-14'] and york['weeks'][0]['usable_minutes']==20
    singapore=Capacity(config(time_zone='Asia/Singapore',start_date='2030-01-14',target_date='2030-01-20',blocks=late,blackouts=[]),moment).report()
    assert [w['week_start'] for w in singapore['weeks']]==['2030-01-14']

def test_paused_week_has_no_capacity_and_is_labelled():
    report=Capacity(config(),NOW,paused=['2030-01-14']).report()
    assert [(w['usable_minutes'],w['paused']) for w in report['weeks']]==[(90,False),(0,True),(300,False)]

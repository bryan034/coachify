from datetime import datetime,timezone,date
from app.schemas.roadmap import PlannerConfig
from app.planning.capacity import Capacity,week_of

def test_overflow_fills_capacity_and_never_uses_blackouts():
    config=PlannerConfig(start_date='2030-01-07',target_date='2030-01-13',weekly_minutes=600,
        time_zone='UTC',allow_overflow=True,overflow_start='08:00',overflow_end='22:00',
        blocks=[{'day':0,'start_time':'19:00','duration_minutes':60}],
        blackouts=[{'frequency':'daily','start_date':'2030-01-07','start_time':'20:00','end_time':'21:00'}, {'frequency':'once','start_date':'2030-01-08'}])
    capacity=Capacity(config,datetime(2030,1,7,7,tzinfo=timezone.utc))
    report=capacity.report()
    assert report['study']['usable_minutes']==600 and report['study']['preferred_minutes']==60
    windows=capacity.windows_for_week(date(2030,1,7))
    assert windows[0]['kind']=='preferred'
    assert not any(window['date']=='2030-01-08' for window in windows)
    assert all(window['end_time']<='20:00' or window['start_time']>='21:00' for window in windows)
    assert all('08:00'<=window['start_time']<window['end_time']<='22:00' for window in windows)

def test_legacy_config_keeps_its_declared_capacity_until_overflow_is_enabled():
    config=PlannerConfig(start_date='2030-01-07',target_date='2030-01-13',weekly_minutes=600,time_zone='UTC',blocks=[{'day':0,'start_time':'19:00','duration_minutes':60}])
    assert Capacity(config,datetime(2030,1,7,tzinfo=timezone.utc)).report()['study']['usable_minutes']==60

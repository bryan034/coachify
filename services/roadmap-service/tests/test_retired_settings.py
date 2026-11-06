"""The startup cleanup that removes retired planner settings from saved records."""
import copy
from planner_fixtures import CleanableStore, FakeCollection
from app.planning.retired_settings import PLAN_CONFIGS, WORKSPACE_CONFIGS, clean_collection, config_update, remove_retired_settings

OLD={'buffer_percent':20,'checkin_day':4,'checkin_time':'18:00'}
RULE={'frequency':'weekly','start_date':'2030-01-01','weekdays':[1]}
def workspace(**config):
    plan={'id':'p1','assignments':[{'id':'a1','status':'completed'}],'config':{'time_zone':'Asia/Singapore',**config}}
    return {'version':7,'messages':[{'id':'m1'}],'planner':{'config':{'weekly_minutes':300,**config},'candidate':copy.deepcopy(plan),'active':copy.deepcopy(plan)}}

def test_old_fields_leave_every_workspace_config_and_nothing_else_changes():
    documents={'owner':workspace(**OLD)}
    clean_collection(FakeCollection(documents),WORKSPACE_CONFIGS)
    assert documents=={'owner':workspace()}

def test_each_old_field_is_removed_on_its_own():
    for field,value in OLD.items():
        documents={'owner':workspace(**{field:value})}
        clean_collection(FakeCollection(documents),WORKSPACE_CONFIGS)
        assert documents=={'owner':workspace()}

def test_blackout_dates_become_one_off_rules():
    documents={'owner':workspace(blackout_dates=['2030-01-12','2030-01-13'])}
    clean_collection(FakeCollection(documents),WORKSPACE_CONFIGS)
    rules=[{'frequency':'once','start_date':'2030-01-12'},{'frequency':'once','start_date':'2030-01-13'}]
    assert documents=={'owner':workspace(blackouts=rules)}

def test_existing_blackout_rules_win_over_old_dates():
    documents={'owner':workspace(blackouts=[RULE],blackout_dates=['2030-01-12'])}
    clean_collection(FakeCollection(documents),WORKSPACE_CONFIGS)
    assert documents=={'owner':workspace(blackouts=[RULE])}

def test_a_second_run_changes_nothing():
    documents={'owner':workspace(**OLD,blackout_dates=['2030-01-12'])}
    collection=FakeCollection(documents)
    clean_collection(collection,WORKSPACE_CONFIGS);once=copy.deepcopy(documents)
    clean_collection(collection,WORKSPACE_CONFIGS)
    assert documents==once

def test_saved_plans_are_cleaned_and_earlier_untimed_plans_are_left_alone():
    timed={'id':'p1','summary':'Keep me.','config':{'time_zone':'Asia/Singapore',**OLD}}
    untimed={'id':'p2','preferences':{'buffer_percent':20},'tasks':[]}
    documents={'p1':timed,'p2':copy.deepcopy(untimed)}
    clean_collection(FakeCollection(documents),PLAN_CONFIGS)
    assert documents=={'p1':{'id':'p1','summary':'Keep me.','config':{'time_zone':'Asia/Singapore'}},'p2':untimed}

def test_empty_and_missing_settings_are_ignored():
    documents={'new':{'version':1,'planner':{'config':None,'candidate':None,'active':None}},'old':{'version':1}}
    before=copy.deepcopy(documents)
    clean_collection(FakeCollection(documents),WORKSPACE_CONFIGS)
    assert documents==before
    assert config_update(None,'planner.config')==({},{})

def test_cleanup_covers_both_collections_and_skips_stores_without_them():
    store=CleanableStore()
    store.data['owner']=workspace(**OLD);store.results[('owner','p1')]={'id':'p1','config':dict(OLD)}
    remove_retired_settings(store)
    assert store.data['owner']==workspace() and store.results[('owner','p1')]['config']=={}
    remove_retired_settings(object())

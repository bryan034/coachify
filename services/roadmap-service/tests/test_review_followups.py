"""Regressions for workarounds removed after a roadmap code review. All data and providers are synthetic."""
from datetime import date, timedelta
import pytest
from planner_fixtures import NOW, assessment, draft, milestone, settings
from test_planner_flow import Scripted, Sources, client_for, configure, generate, request, task, accepted
from test_partial_outline import mixed_outline
from app.planning.capacity import Capacity, Placer
from app.planning.outlines import check_objectives
from app.planning.partial_outline import recover_outline
from app.planning.sessions import calendar, locate, place, skip_session
from app.planning.state import evaluation_current, planning_source_changed, with_periods
from app.planning.tasks import project_assignments, slot_id
from app.schemas.outlines import OutlineDraft
from app.schemas.roadmap import PlannerConfig


def test_planning_gates_fail_closed_without_an_evaluation_status():
    assert evaluation_current({'evaluation':{'freshness':'current'}})
    assert not evaluation_current({}) and not evaluation_current({'evaluation':None}) and not evaluation_current({'evaluation':{}})
    assert planning_source_changed({'evaluation':{'freshness':'current'}},{})


def test_accepting_an_outline_needs_an_explicitly_current_evaluation():
    class NoStatus(Sources):
        drop=False
        async def read(self,service,path,token,params=None):
            value=await super().read(service,path,token,params)
            if self.drop and path.endswith('/context'):value.pop('evaluation',None)
            return value
    source=NoStatus()
    with client_for(Scripted([draft()]),source) as client:
        state=generate(client,configure(client))
        assert state['planner']['outline_candidate'] is not None
        source.drop=True
        response=request(client,'/outlines/'+state['planner']['outline_candidate']['id']+'/accept',state)
        assert response.status_code==409 and response.json()['code']=='assessment_required',response.text


def three_slot_plan():
    days=[date(2030,1,7),date(2030,1,7),date(2030,1,8)]
    task={'id':'t1','title':'Practise','instructions':'Practise.','completion_outcome':'Done.','estimated_minutes':90,'requirement_refs':[],
        'prerequisites':[],'milestone_key':'m1','status':'not_started','history':[],'removed':False,'origin':'user','overrides':[],
        'schedule':[{'date':day.isoformat(),'start_time':start,'duration_minutes':30} for day,start in zip(days,('09:00','10:00','09:00'))]}
    return {'config':settings(),'milestones':[{'key':'m1','gap_ids':[]}],'gaps':[],'editable_tasks':[task]},task


def test_skipping_one_session_keeps_the_ids_of_the_others():
    plan,task=three_slot_plan()
    before=[slot_id(task,index) for index in range(3)]
    skip_session(plan,calendar(plan,NOW),before[1])
    assert [slot_id(task,index) for index in range(2)]==[before[0],before[2]]
    assert locate(plan,before[2])==(task,1)
    assert [row['id'] for row in project_assignments(plan)]==[before[0],before[2]]
    place(task,1,date(2030,1,10),'19:00',30,update_estimate=False)
    assert slot_id(task,1)==before[2]


def test_skipping_the_first_session_keeps_the_ids_of_later_ones():
    plan,task=three_slot_plan()
    before=[slot_id(task,index) for index in range(3)]
    skip_session(plan,calendar(plan,NOW),before[0])
    assert [slot_id(task,index) for index in range(2)]==before[1:]


def test_a_batch_cannot_move_two_sessions_into_the_same_time():
    model=Scripted([draft(assignments=[task('one','First',45),task('two','Second',45)])])
    with client_for(model) as client:
        state=accepted(client,break_minutes_per_hour=0)
        first,second=state['planner']['active_sessions']
        response=request(client,'/sessions/move',state,moves=[{'session_id':first['id'],'date':'2030-01-14','start_time':'19:00'},
            {'session_id':second['id'],'date':'2030-01-14','start_time':'19:30'}])
        assert response.status_code==409 and response.json()['code']=='slot_taken',response.text


def bare_outline(value):
    value=dict(value);value.pop('assignments',None)
    return value


def test_partial_recovery_never_rewrites_the_deadline_claim():
    value=bare_outline(mixed_outline())
    value['weeks']=[{'week_start':'2030-01-07','objective':'Build endpoints','expected_outcome':'Test passes','estimated_minutes':60,'milestone_key':'m1','gap_ids':['python']}]
    value['beyond_deadline']=[{'title':'Infrastructure later','gap_ids':['invalid'],'reason':'After the target.','estimated_minutes':60}]
    assert recover_outline(OutlineDraft.model_validate(value),assessment())==(None,None)
    value['beyond_deadline'].append({'title':'Python depth later','gap_ids':['python'],'reason':'After the target.','estimated_minutes':60})
    recovered,review=recover_outline(OutlineDraft.model_validate(value),assessment())
    assert recovered.deadline_outcome.fits_in_runway is False and [b.title for b in recovered.beyond_deadline]==['Python depth later']
    omitted=[item['id'] for item in review['omitted_items'] if item['kind']=='beyond_deadline']
    _,again=recover_outline(OutlineDraft.model_validate(value),assessment())
    assert omitted and omitted[0].startswith('beyond:') and omitted==[item['id'] for item in again['omitted_items'] if item['kind']=='beyond_deadline']


def test_the_outline_model_is_told_which_requirement_refs_it_may_use():
    model=Scripted([draft()])
    with client_for(model) as client:
        generate(client,configure(client))
    assert model.sent('OutlineDraft')[0]['permitted_requirement_refs']==['job:git','job:python','job:sql']


def test_milestones_moved_up_to_the_planning_start_are_recorded():
    model=Scripted([draft(milestones=[milestone(projected_start='2030-01-07')])])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        outline=state['planner']['outline_candidate']
        assert outline['milestones'][0]['projected_start']=='2030-01-09'
        assert outline['generation']['clamped_milestones']==['m1']


def test_an_invalid_profile_period_is_skipped_without_dropping_the_others():
    config=PlannerConfig.model_validate(settings())
    periods=[{'start_date':'2030-01-14','end_date':'2030-01-20','weekly_hours':2},
        {'start_date':'2030-01-20','end_date':'2030-01-14','weekly_hours':2},
        {'start_date':'2030-01-21','end_date':'2030-01-27','weekly_hours':500}]
    kept=with_periods(config,periods).reduced_periods
    assert [(str(p.start_date),p.weekly_minutes) for p in kept]==[('2030-01-14',120)]


def test_weekly_objective_errors_quote_the_usable_minutes_being_checked():
    capacity=Capacity(PlannerConfig.model_validate(settings()),NOW)
    week=capacity.weeks()[0]
    value=bare_outline(draft())
    value['weeks']=[{'week_start':week['week_start'],'objective':'Too much','expected_outcome':'An API','estimated_minutes':week['usable_minutes']+30,'milestone_key':'m1','gap_ids':['python']}]
    errors=[e for e in check_objectives(OutlineDraft.model_validate(value),capacity) if e['code']=='week_effort_exceeds_hours']
    assert errors and f"{week['usable_minutes']} usable minutes" in errors[0]['message']


class LinearPlacer(Placer):
    def longest_fit(self,low,high,kind):
        for length in range(high,low-1,-1):
            if self.find(length,kind=kind):return length
        return None


@pytest.mark.parametrize('changes',[{},{'break_minutes_per_hour':10},{'break_minutes_per_hour':30,'preferred_session_minutes':95},
    {'max_daily_minutes':70,'min_session_minutes':20},{'rest_days_per_week':2,'allow_overflow':True},{'allow_overflow':True,'preferred_session_minutes':240}])
def test_the_capacity_search_matches_a_one_minute_search(changes):
    config=PlannerConfig.model_validate(settings(**changes))
    reserved=[{'date':'2030-01-14','start_time':'19:20','duration_minutes':35},{'date':'2030-01-16','start_time':None,'duration_minutes':40}]
    start,end=date(2030,1,9),date(2030,1,28)
    for first in (start,date(2030,1,14),date(2030,1,21)):
        last=min(end,first+timedelta(days=7))
        assert Placer(config,NOW,reserved,first,last).room_details()==LinearPlacer(config,NOW,reserved,first,last).room_details()

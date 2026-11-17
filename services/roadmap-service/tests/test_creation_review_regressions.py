"""Regression cases found while reviewing automatic roadmap activation."""
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from app.main import create_app
from planner_fixtures import draft, milestone, NOW
from test_planner_flow import Scripted, Sources, configure, finish, read, H, PREFIX, week_draft, task
from test_automatic_creation import create


def test_r2_update_with_all_weeks_scheduled_preserves_tasks_and_activates_outline():
    short=draft(milestones=[milestone(estimated_minutes=60,projected_end='2030-01-13')])
    updated={**short,'summary':'Updated outline with the existing scheduled work.'}
    model=Scripted([short,updated])
    with TestClient(create_app(MemoryStore(),Sources(),model,clock=lambda:NOW)) as client:
        state,_=create(client,configure(client,target_date='2030-01-13',break_minutes_per_hour=0,
            blocks=[{'day':2,'start_time':'19:00','duration_minutes':180}]))
        assert state['operation']['status']=='succeeded'
        before=state['planner']['active']['editable_tasks']
        blocks=state['planner']['week_blocks']
        state,_=create(client,state)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['active']['summary']==updated['summary']
        assert state['planner']['outline_active']['summary']==updated['summary']
        assert state['planner']['active']['editable_tasks']==before
        assert [b['task_ids'] for b in state['planner']['week_blocks']]==[b['task_ids'] for b in blocks]
        assert model.schemas==['OutlineDraft','WeekDraft','OutlineDraft']
        assert state['planner']['outline_candidate'] is None


@pytest.mark.parametrize('change_after',[1,2])
def test_r3_availability_changed_after_week_check_prevents_automatic_activation(change_after):
    class ChangingAvailability(Sources):
        changed=False
        week_written=False
        checked=0
        async def read(self,service,path,token,params=None):
            result=await super().read(service,path,token,params)
            if path.endswith('/context') and self.week_written:self.checked+=1
            if self.checked==change_after and not self.changed:
                self.periods=[{'start_date':'2030-01-09','end_date':'2030-01-27','weekly_hours':0}]
                self.changed=True
            return result
    source=ChangingAvailability()
    class MarkWeek(Scripted):
        async def generate(self,schema,instructions,context,max_tokens=8192):
            result=await super().generate(schema,instructions,context,max_tokens)
            if schema.__name__=='WeekDraft':source.week_written=True
            return result
    store=MemoryStore()
    with TestClient(create_app(store,source,MarkWeek([draft()]),clock=lambda:NOW)) as client:
        state,_=create(client,configure(client))
        assert source.changed
        assert state['operation']['status']=='failed',state['operation']
        assert state['operation']['error']['code']=='inputs_changed'
        assert state['planner']['active'] is None
        assert state['planner']['outline_candidate'] is None and state['planner']['week_candidate'] is None
        assert store.results=={}


def test_r4_retry_after_capture_and_publication_failure_keeps_one_coherent_attempt():
    class CaptureThenFail(MemoryStore):
        first=True
        def cas(self,owner,version,row):
            if self.first and (row.get('last_operation') or {}).get('status')=='succeeded':
                self.first=False
                raise Problem('Synthetic publication failure.',503,'storage')
            return super().cas(owner,version,row)
    source=Sources()
    model=Scripted([draft(summary='First attempt'),draft(summary='Second attempt')],
        weeks=[week_draft([task('first','Build first endpoint')]),week_draft([task('second','Build second endpoint')])])
    with TestClient(create_app(CaptureThenFail(),source,model,clock=lambda:NOW)) as client:
        state,body=create(client,configure(client))
        assert state['operation']['status']=='failed' and state['planner']['active'] is None
        response=client.post(PREFIX+'/outlines/generate',headers=H,json=body)
        assert response.status_code==202,response.text
        state=finish(client);planner=state['planner'];active=planner['active']
        assert state['operation']['status']=='succeeded',state['operation']
        assert active['summary']==planner['outline_active']['summary']=='Second attempt'
        assert [t['title'] for t in active['editable_tasks']]==['Build second endpoint']
        assert planner['week_blocks'][0]['task_ids']==[t['id'] for t in active['editable_tasks']]
        history=client.get('/api/v1/roadmaps/history/'+active['id'],headers=H)
        assert history.status_code==200 and history.json()==active
        replay=client.post(PREFIX+'/outlines/generate',headers=H,json=body)
        assert replay.status_code==202
        assert read(client)['planner']['active']==active
        assert model.schemas==['OutlineDraft','WeekDraft','OutlineDraft','WeekDraft']

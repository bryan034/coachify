"""Creation publishes tasks without a second request, with atomic failure and replay."""
import copy
from uuid import uuid4
from elo_shared.runtime import Problem
from planner_fixtures import draft
from test_planner_flow import (H, PREFIX, Scripted, accepted, client_for, configure, finish,
                               read, task, week_draft)

def create(client,state,**changes):
    body={'expected_version':state['version'],'mutation_id':str(uuid4()),'auto_accept':True,**changes}
    response=client.post(PREFIX+'/outlines/generate',headers=H,json=body)
    assert response.status_code==202,response.text
    return finish(client),body

def test_create_publishes_first_week_and_history_without_accept_request_and_replays_once():
    model=Scripted([draft()])
    with client_for(model) as client:
        state,body=create(client,configure(client))
        assert state['operation']['status']=='succeeded',state['operation']
        planner=state['planner'];active=planner['active']
        assert planner['outline_candidate'] is None and planner['week_candidate'] is None
        assert planner['outline_active']['status']=='accepted'
        assert len(active['editable_tasks'])==1 and len(planner['active_sessions'])==1
        assert len(planner['week_blocks'])==1 and planner['week_blocks'][0]['status']=='accepted'
        assert active['pace_baseline_id']==active['id']
        history=client.get('/api/v1/roadmaps/history/'+active['id'],headers=H)
        assert history.status_code==200 and history.json()==active
        replay=client.post(PREFIX+'/outlines/generate',headers=H,json=body)
        assert replay.status_code==202
        reloaded=read(client)
        assert reloaded['version']==state['version'] and reloaded['planner']['active']==active
        assert model.schemas==['OutlineDraft','WeekDraft']

def test_failed_first_week_does_not_publish_empty_roadmap_and_can_retry():
    model=Scripted([draft(),draft()],weeks=[Problem('Synthetic unavailable provider.',503,'model_provider'),week_draft([task('new','Write endpoint tests')])])
    with client_for(model) as client:
        state,_=create(client,configure(client))
        assert state['operation']['status']=='failed'
        assert state['planner']['active'] is None and state['planner']['outline_active'] is None
        assert state['planner']['outline_candidate'] is None and state['planner']['week_candidate'] is None
        assert state['planner']['retry_outline']['auto_accept'] is True
        state,_=create(client,state)
        assert state['operation']['status']=='succeeded',state['operation']
        assert state['planner']['active_sessions'][0]['title']=='Write endpoint tests'

def test_failed_automatic_regeneration_preserves_saved_roadmap():
    model=Scripted([draft(),draft()],weeks=[week_draft([task('old','Write original endpoint')]),Problem('Synthetic unavailable provider.',503,'model_provider')])
    with client_for(model) as client:
        state=accepted(client)
        before=copy.deepcopy(state['planner']['active'])
        state,_=create(client,state)
        assert state['operation']['status']=='failed'
        assert state['planner']['active']==before
        assert state['planner']['outline_candidate'] is None and state['planner']['week_candidate'] is None


def test_checkpoints_and_timeouts_do_not_expose_an_automatic_creation_preview():
    from planner_fixtures import NOW, OWNER
    from app.planning.state import planner_state, planner_view
    with client_for(Scripted([draft()])) as client:
        saved=accepted(client)
        row=client.app.state.store.load(OWNER)
        state=planner_state(row)
        expected=planner_view(row,saved['context'],NOW)['active']
        state['outline_candidate']=copy.deepcopy(state['outline_active'])
        for field in ('pending','last_operation'):
            row['pending']=None
            row[field]={'kind':'outline_generate','body':{'auto_accept':True},'status':'failed' if field=='last_operation' else 'running'}
            view=planner_view(row,saved['context'],NOW)
            assert view['outline_candidate'] is None and view['week_candidate'] is None
            assert view['preview_sessions']==[]
            assert view['active']==expected
            assert state['outline_candidate'] is not None

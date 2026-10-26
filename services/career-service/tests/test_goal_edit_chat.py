"""Guided edits use real MongoDB/versioning with deterministic model decisions."""
import json
from types import SimpleNamespace
from uuid import uuid4
from app.ai.goal_edit_contracts import GoalEditDecision
from app.schemas.analysis import Generation
from app.repositories.goals import now
from tests.test_workspace import flow,ingest,wait,headers,BASE,OWNER


def install(flow,decisions):
    ai=flow[2];original=ai.generate;seen=[]
    async def generate(request,operation,**kwargs):
        if request.stage!='goal_edit':return await original(request,operation,**kwargs)
        seen.append(request)
        result=GoalEditDecision.model_validate(decisions.pop(0))
        if kwargs.get('validate_output'):kwargs['validate_output'](result)
        return SimpleNamespace(data=result,generation=Generation(provider='fixture',model='fixture',prompt_version='edit-test',generated_at=now()))
    flow[0].app.state.ai=SimpleNamespace(generate=generate,settings=ai.settings)
    return seen


def decision(status,reply,changes=(),intent='Update career goal'):
    return {'status':status,'reply':reply,'intent':intent,'changes':list(changes)}


def field(name,value):return {'collection':'goal','action':'set','field':name,'value':value}


def send(flow,current,message,key=None,extra=None):
    return flow[0].post(BASE+'/messages',headers={**headers(key),**(extra or {})},json={
        'session_id':current['session_id'],'expected_version':current['revision'],'message':message})


def test_multiple_guided_questions_keep_current_goal_until_a_complete_edit_and_replay_once(flow):
    client,db,ai,sources=flow;ingest(flow);initial=wait(flow);identifier=initial['current']['goal']['_id']
    seen=install(flow,[decision('clarify','Which part: role, location or a skill?'),
        decision('clarify','Which city or country should the role be based in?',intent='Change the goal location'),
        decision('ready','Your target location is now London.',[field('location','London')],intent='Set location to London')])
    assert send(flow,initial,'Change my career goal').json()['edit_status']=='clarifying'
    assert send(flow,initial,'The location').json()['edit_status']=='clarifying'
    pending=client.get(BASE,headers=headers()).json()
    assert pending['current']['goal']['_id']==identifier and pending['revision']==initial['revision']
    assert pending['edit_question']=='Which city or country should the role be based in?'
    draft=db.career_state.find_one({'_id':OWNER})['workspace']['edit_draft']
    assert 'conversation' not in draft and 'messages' not in draft
    key=str(uuid4());response=send(flow,initial,'London',key)
    assert response.status_code==200,response.text
    saved=response.json();assert saved['edit_status']=='saved'
    assert saved['workspace']['review']['extraction']['location']=='London'
    assert saved['workspace']['review']['extraction']['skills']==initial['review']['extraction']['skills']
    assert saved['workspace']['edit_question'] is None
    assert json.loads(seen[-1].context)['pending_edit']['intent']=='Change the goal location'
    assert all(len(r.conversation)==1 for r in seen)
    ready=wait(flow);assert ready['revision']==2 and ready['current']['goal']['location']=='London'
    replay=send(flow,initial,'London',key)
    assert replay.status_code==200 and replay.json()['edit_status']=='saved' and len(seen)==3
    assert send(flow,initial,'Singapore',key).status_code==409
    assert ready['review']['requirements_need_review']  # Earlier requirements were not silently re-certified.


def test_skill_change_is_automatically_applied_with_user_provenance(flow):
    client,db,ai,sources=flow;ingest(flow);initial=wait(flow)
    response=send(flow,initial,'Add Python')
    assert response.status_code==200,response.text
    result=response.json();assert result['edit_status']=='saved' and result['proposed_skills'] is None
    skills=result['workspace']['review']['extraction']['skills']
    assert skills[0]==initial['review']['extraction']['skills'][0]
    assert skills[-1]['name']=='Python' and skills[-1]['origin']=='user_declaration' and skills[-1]['evidence']=='Add Python'
    assert wait(flow)['current']['goal']['skills'][-1]['name']=='Python'


def test_pending_edits_can_be_cancelled_or_replaced_by_a_new_jd(flow):
    client,db,ai,sources=flow;ingest(flow);initial=wait(flow)
    install(flow,[decision('clarify','Which skill should change?'),decision('cancel','Kept your current goal unchanged.'),
        decision('clarify','What new role are you considering?')])
    send(flow,initial,'Change my skills')
    assert client.get(BASE,headers=headers(other=True)).json()['edit_question'] is None
    assert send(flow,initial,'Cancel that edit').json()['edit_status']=='cancelled'
    assert client.get(BASE,headers=headers()).json()['edit_question'] is None
    assert str(db.career_state.find_one({'_id':OWNER})['goal_id'])==initial['current']['goal']['_id']
    send(flow,initial,'Change my role')
    ingest(flow,text='Second Analyst. SQL is required.');replaced=wait(flow)
    assert replaced['session_id']!=initial['session_id'] and replaced['edit_question'] is None
    assert 'edit_draft' not in db.career_state.find_one({'_id':OWNER})['workspace']


def test_bad_change_reference_is_repaired_inside_the_graph_before_any_save(flow):
    import time
    client,db,ai,sources=flow;ingest(flow);initial=wait(flow)
    seen=install(flow,[decision('ready','Changing it.',[{'collection':'skills','action':'remove','reference':'s999'}]),
        decision('ready','Updated the company.',[field('company','Example')])])
    response=send(flow,initial,'Change my company to Example',extra={'Prefer':'respond-async'})
    assert response.status_code==202,response.text
    path=BASE+'/operations/'+response.json()['operation_id']
    for _ in range(100):
        result=client.get(path,headers=headers())
        assert result.status_code==200,result.text
        if result.json()['status']=='succeeded':break
        time.sleep(.02)
    assert result.json()['status']=='succeeded' and result.json()['result']['edit_status']=='saved'
    ready=wait(flow);assert ready['revision']==2 and ready['review']['extraction']['company']=='Example'
    assert ready['review']['extraction']['skills']==initial['review']['extraction']['skills'] and len(seen)==2


def test_stale_edit_is_rejected_before_using_the_model(flow):
    ingest(flow);initial=wait(flow);seen=install(flow,[decision('ready','Updated the company.',[field('company','Example')])])
    assert send(flow,initial,'Change my company to Example').status_code==200
    wait(flow)
    stale=send(flow,initial,'Change my location to London')
    assert stale.status_code==409 and len(seen)==1


def test_explicit_refinement_can_update_saved_goal_while_research_is_unavailable(flow):
    from tests.test_workspace import BASE,headers,ingest,wait
    flow[3].block=True
    assert ingest(flow).status_code==202
    current=wait(flow,phase='research_failed')
    response=flow[0].post(BASE+'/messages',headers=headers(),json={'session_id':current['session_id'],'expected_version':current['review']['version'],'message':'Add Python to my goal','mode':'refine'})
    assert response.status_code==200,response.text
    assert response.json()['edit_status']=='saved'
    assert any(s['name']=='Python' for s in response.json()['workspace']['review']['extraction']['skills'])

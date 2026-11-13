"""Timed-roadmap endpoints. Writes reuse the workspace's version and receipt protection."""
from fastapi import Depends, Request
from uuid import NAMESPACE_URL, uuid5
import copy
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, begin, launch, operation_view, stamp, digest
from app.planning.capacity import Capacity, normalized
from app.planning.generator import PLANNING_SECONDS
from app.planning.milestone_membership import mark_plan_membership_changes
from app.planning.state import candidate_blockers, completed_sessions, learning_view, planner_state, saved_config
from app.planning.tasks import change_status, ensure_tasks, project_assignments
from app.planning.task_routes import register_task_routes
from app.planning.session_routes import register_session_routes
from app.schemas.roadmap import (AssignmentStatus, CheckpointReached, ExperienceConfirmation, GeneratePlan, LearningPlan, OperationAccepted, Runway, MilestoneOutcome,
    PlannerConfig, RunwayRequest, SaveConfig)
from app.schemas.planner import Mutation, Workspace

from pydantic import Field
class ConfirmEvidence(Mutation):
    expected_declarations_version:int=Field(ge=0)
    proposal_hash:str=Field(min_length=64,max_length=64)

def evidence_proposals(row):
    state=planner_state(row);plan=copy.deepcopy(state.get('active'))
    if not plan:return []
    ensure_tasks(plan);project_assignments(plan)
    gaps={gap['id']:gap for gap in plan.get('gaps',[])}
    proposals=[]
    for session in plan.get('assignments',[]):
        if session.get('status')!='completed' or not session.get('evidence_note'):continue
        identifiers=session.get('skill_gap_ids') or ([session['gap_id']] if session.get('gap_id') else [])
        for gap_id in identifiers:
            gap=gaps.get(gap_id)
            if not gap:continue
            proposal={'id':session['id']+'_'+gap_id,'session_id':session['id'],'name':gap['name'],
                'description':'Self-reported roadmap practice: '+session['evidence_note']}
            if len(proposal['name'])>120 or len(proposal['description'])>2000:continue  # Original note stays saved; never truncate evidence.
            proposal['proposal_hash']=digest({'plan':plan['id'],**proposal})
            if proposal['proposal_hash'] not in state.get('confirmed_evidence',[]):proposals.append(proposal)
    return proposals

def register_planner(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner'
    register_task_routes(app,context,mutate)
    register_session_routes(app,context,mutate)
    @app.get('/api/v1/roadmaps/learning',response_model=LearningPlan)
    async def learning(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        return learning_view(planner_state(row)['active'],app.state.clock())

    @app.post(prefix+'/runway',response_model=Runway)
    async def runway(body:RunwayRequest,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        capacity=Capacity(body.config,app.state.clock(),completed_sessions(state['active']))
        return capacity.report(allow_past_start=bool(state['active']))

    @app.post(prefix+'/config',response_model=Workspace)
    async def save_config(body:SaveConfig,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            today=Capacity(body.config,app.state.clock()).today
            planner_state(row)['config']=normalized(body.config,today).model_dump(mode='json')
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/generate',status_code=202,response_model=OperationAccepted)
    async def generate(body:GeneratePlan,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        repeated=any(r['id']==str(body.mutation_id) for r in row['receipts']) or (row.get('pending') or {}).get('id')==str(body.mutation_id)
        if not repeated:
            source=await context(account)
            if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
            config=saved_config(state)
            report=Capacity(config,app.state.clock(),completed_sessions(state['active'])).report(allow_past_start=bool(state['active']))
            if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
        row=await thread(begin,app.state.store,account['id'],body,'generate',PLANNING_SECONDS)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.post(prefix+'/roll-forward',status_code=202,response_model=OperationAccepted)
    async def roll_forward(body:GeneratePlan,request:Request,account=Depends(authenticated)):
        from app.planning.capacity import week_of
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        active=state.get('active')
        if not active or state.get('candidate'):raise Problem('A saved active roadmap without a pending preview is required.',409,'roll_forward_blocked')
        today=Capacity(saved_config(state),app.state.clock()).today
        if active.get('first_planning_week','')>=week_of(today).isoformat():return {'version':row['version'],'operation':operation_view(row)}
        row=await thread(begin,app.state.store,account['id'],body,'roll_forward',PLANNING_SECONDS)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.get(prefix+'/evidence-proposals')
    async def proposals(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        declarations=await app.state.upstream.read('profile','/api/v1/profile/capabilities',account['token'])
        return {'version':row['version'],'declarations_version':declarations['version'],'items':evidence_proposals(row)}

    @app.post(prefix+'/evidence-proposals/{proposal_id}/confirm',response_model=Workspace)
    async def confirm_evidence(proposal_id:str,body:ConfirmEvidence,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        if row['version']!=body.expected_version:raise Problem('Your roadmap changed. Review the evidence proposal again.',409,'inputs_changed')
        proposal=next((item for item in evidence_proposals(row) if item['id']==proposal_id and item['proposal_hash']==body.proposal_hash),None)
        if not proposal:raise Problem('This evidence proposal changed or was already confirmed.',409,'inputs_changed')
        await app.state.upstream.write('profile','/api/v1/profile/capabilities',account['token'],
            {'expected_version':body.expected_declarations_version,'mutation_id':'roadmap_'+body.proposal_hash,
             'name':proposal['name'],'description':proposal['description'],'mode':'new'})
        def apply(current,source):
            if not any(item['proposal_hash']==body.proposal_hash for item in evidence_proposals(current)):raise Problem('The session note changed before confirmation.',409,'inputs_changed')
            state=planner_state(current);state.setdefault('confirmed_evidence',[]).append(body.proposal_hash)
            return current
        return await mutate(body,account,apply,operation='evidence.confirm')

    @app.post(prefix+'/accept',response_model=Workspace)
    async def accept(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row)
            if not state['candidate']:raise Problem('There is no previewed roadmap to accept.')
            blockers=candidate_blockers(state,source,app.state.clock())
            if blockers:raise Problem(blockers[0]['message'],409,blockers[0]['code'])
            mark_plan_membership_changes(state['active'],state['candidate'])
            state['active']=state['candidate'];state['candidate']=None
            return row
        return await mutate(body,account,apply,operation='preview.accept',mark_baseline=True)

    @app.post(prefix+'/discard',response_model=Workspace)
    async def discard(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            planner_state(row)['candidate']=None
            return row
        return await mutate(body,account,apply,operation='preview.discard')

    def active_plan(row):
        plan=planner_state(row)['active']
        if not plan:raise Problem('Accept a roadmap before recording progress.')
        return plan

    @app.post(prefix+'/assignments/status',response_model=Workspace)
    async def assignment_status(body:AssignmentStatus,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active_plan(row)
            tasks=ensure_tasks(copy.deepcopy(plan))
            task=next((t for t in tasks if not t.get('removed') and (t['id']==body.assignment_id or any(str(uuid5(NAMESPACE_URL,t['id']+':slot:'+str(i)))==body.assignment_id for i in range(1,len(t['schedule']))))),None)
            if not task:raise Problem('This session was not found.',404,'not_found')
            if len(task['schedule'])!=1:raise Problem('This task has multiple sessions. Update its status using the task endpoint.',409,'task_status_required')
            desired='completed' if body.status=='completed' else 'not_started'
            note=(body.evidence_note or '').strip() or None
            if task['status']==desired and (desired!='completed' or task.get('evidence_note')==note) and not task.get('definition_review_required'):return row
            task=next(t for t in ensure_tasks(plan) if t['id']==task['id'])
            change_status(task,desired,body.evidence_note)
            project_assignments(plan)
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/milestones/outcome',response_model=Workspace)
    async def milestone_outcome(body:MilestoneOutcome,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            milestone=next((m for m in active_plan(row)['milestones'] if m['id']==body.milestone_id),None)
            if not milestone:raise Problem('This milestone was not found.',404,'not_found')
            note=(body.note or '').strip()
            if body.demonstrated and not note:raise Problem('Describe how you demonstrated this outcome.',422,'validation')
            prior=milestone.get('outcome') or {}
            history=copy.deepcopy(prior.get('history',[]))
            if prior.get('recorded_at'):
                history.append({k:copy.deepcopy(v) for k,v in prior.items() if k!='history'})
            milestone['outcome']={'demonstrated':body.demonstrated,'note':note or None,'recorded_at':stamp(),'source':'self_reported'}
            if history:milestone['outcome']['history']=history
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/milestones/checkpoint',response_model=Workspace)
    async def checkpoint(body:CheckpointReached,request:Request,account=Depends(authenticated)):
        """Self-reported: tick or untick one checkpoint inside a milestone."""
        def apply(row,source):
            milestone=next((m for m in active_plan(row)['milestones'] if m['id']==body.milestone_id),None)
            item=next((c for c in (milestone or {}).get('checkpoints',[]) if c['key']==body.checkpoint_key),None)
            if not item:raise Problem('This checkpoint was not found.',404,'not_found')
            if bool(item.get('reached_at'))!=body.reached:item['reached_at']=stamp() if body.reached else None
            return row
        return await mutate(body,account,apply,operation='milestones.checkpoint')

    @app.post(prefix+'/confirmations',response_model=Workspace)
    async def confirmation(body:ExperienceConfirmation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row)
            plan=state['candidate'] or state['active']
            gap=next((g for g in (plan or {}).get('gaps',[]) if g['id']==body.gap_id),None)
            if not gap:raise Problem('This question was not found in your plan.',404,'not_found')
            state['confirmations'][body.gap_id]={'name':gap['name'],'question':gap.get('confirmation_question'),'answer':body.answer,
                'note':(body.note or '').strip() or None,'source':'self_reported','recorded_at':stamp()}
            return row
        return await mutate(body,account,apply)

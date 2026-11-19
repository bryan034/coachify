"""Timed-roadmap endpoints. Writes reuse the workspace's version and receipt protection."""
import copy
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, stamp, digest
from app.planning.capacity import Capacity, normalized
from app.planning.outlines import register_outline_routes
from app.planning.session_routes import register_session_routes
from app.planning.state import completed_sessions, learning_view, planner_state, with_periods
from app.planning.task_routes import register_task_routes
from app.planning.tasks import change_status, ensure_tasks, project_assignments, slot_id
from app.planning.weeks import register_week_routes
from app.schemas.roadmap import (AssignmentStatus, CheckpointReached, ConfirmEvidence, EvidenceProposals, ExperienceConfirmation, LearningPlan, Runway,
    MilestoneOutcome, RunwayRequest, SaveConfig)
from app.schemas.planner import Workspace

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
            if len(proposal['name'])>120 or len(proposal['description'])>2000:continue
            proposal['proposal_hash']=digest(proposal)
            if proposal['proposal_hash'] not in state.get('confirmed_evidence',[]):proposals.append(proposal)
    return proposals

def register_planner(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner'
    register_task_routes(app,context,mutate)
    register_session_routes(app,mutate)
    register_outline_routes(app,context,mutate,worker)
    register_week_routes(app,context,mutate,worker)
    @app.get('/api/v1/roadmaps/learning',response_model=LearningPlan)
    async def learning(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        return learning_view(planner_state(row)['active'],app.state.clock())

    @app.post(prefix+'/runway',response_model=Runway)
    async def runway(body:RunwayRequest,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        config=with_periods(body.config,account['profile'].get('availability_periods',[]))
        capacity=Capacity(config,app.state.clock(),completed_sessions(state['active']))
        return capacity.report(allow_past_start=bool(state['active'] or state['outline_active']))

    @app.post(prefix+'/config',response_model=Workspace)
    async def save_config(body:SaveConfig,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            config=with_periods(body.config,(source.get('planning_defaults') or {}).get('availability_periods'))
            today=Capacity(config,app.state.clock()).today
            planner_state(row)['config']=normalized(config,today).model_dump(mode='json')
            return row
        return await mutate(body,account,apply)

    @app.get(prefix+'/evidence-proposals',response_model=EvidenceProposals)
    async def proposals(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        declarations=await app.state.upstream.read('profile','/api/v1/profile/capabilities',account['token'])
        return {'version':row['version'],'declarations_version':declarations['version'],'items':evidence_proposals(row)}

    @app.post(prefix+'/evidence-proposals/{proposal_id}/confirm',response_model=Workspace)
    async def confirm_evidence(proposal_id:str,body:ConfirmEvidence,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        if any(receipt['id']==str(body.mutation_id) for receipt in row['receipts']):
            return await mutate(body,account,lambda current,_source:current,operation='evidence.confirm')
        if row.get('pending'):raise Problem('Wait for the current adviser response before confirming evidence.',409,'operation_pending')
        if row['version']!=body.expected_version:raise Problem('Your roadmap changed. Review the evidence proposal again.',409,'inputs_changed')
        proposal=next((item for item in evidence_proposals(row) if item['id']==proposal_id and item['proposal_hash']==body.proposal_hash),None)
        if not proposal:raise Problem('This evidence proposal changed or was already confirmed.',409,'inputs_changed')
        await app.state.upstream.write('profile','/api/v1/profile/capabilities',account['token'],
            {'expected_version':body.expected_declarations_version,'mutation_id':'roadmap_'+body.proposal_hash,
             'name':proposal['name'],'description':proposal['description'],'mode':'new'})
        def apply(current,_source):
            if not any(item['proposal_hash']==body.proposal_hash for item in evidence_proposals(current)):raise Problem('The session note changed before confirmation.',409,'inputs_changed')
            state=planner_state(current);state.setdefault('confirmed_evidence',[]).append(body.proposal_hash)
            return current
        return await mutate(body,account,apply,operation='evidence.confirm')

    def active_plan(row):
        plan=planner_state(row)['active']
        if not plan:raise Problem('Accept a roadmap before recording progress.')
        return plan

    @app.post(prefix+'/assignments/status',response_model=Workspace)
    async def assignment_status(body:AssignmentStatus,request:Request,account=Depends(authenticated)):
        def apply(row,_source):
            plan=active_plan(row)
            tasks=ensure_tasks(copy.deepcopy(plan))
            task=next((t for t in tasks if not t.get('removed') and (t['id']==body.assignment_id or any(slot_id(t,i)==body.assignment_id for i in range(len(t['schedule']))))),None)
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
        def apply(row,_source):
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
        def apply(row,_source):
            milestone=next((m for m in active_plan(row)['milestones'] if m['id']==body.milestone_id),None)
            item=next((c for c in (milestone or {}).get('checkpoints',[]) if c['key']==body.checkpoint_key),None)
            if not item:raise Problem('This checkpoint was not found.',404,'not_found')
            if bool(item.get('reached_at'))!=body.reached:item['reached_at']=stamp() if body.reached else None
            return row
        return await mutate(body,account,apply,operation='milestones.checkpoint')

    @app.post(prefix+'/confirmations',response_model=Workspace)
    async def confirmation(body:ExperienceConfirmation,request:Request,account=Depends(authenticated)):
        def apply(row,_source):
            state=planner_state(row)
            plan=state['outline_candidate'] or state['active']
            gap=next((g for g in (plan or {}).get('gaps',[]) if g['id']==body.gap_id),None)
            if not gap:raise Problem('This question was not found in your plan.',404,'not_found')
            state['confirmations'][body.gap_id]={'name':gap['name'],'question':gap.get('confirmation_question'),'answer':body.answer,
                'note':(body.note or '').strip() or None,'source':'self_reported','recorded_at':stamp()}
            return row
        return await mutate(body,account,apply)

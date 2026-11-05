"""Roadmap-planner endpoints. Writes reuse the workspace's version and receipt protection."""
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, begin, launch, operation_view
from app.planning.capacity import Capacity, normalized
from app.planning.checkin import open_week
from app.planning.generator import PLANNING_SECONDS
from app.planning.metrics import archive_summary
from app.planning import proposals, schedule
from app.planning.state import COMPLETED_WORK_LIMIT, candidate_blockers, completed_sessions, finished_records, planner_state, saved_config
from app.schemas.roadmap import (AcceptProposal, AssignmentStatus, BringDeferred, CheckinAnswer, CheckinPropose, CompleteMilestone, CustomTask, DiscardProposal, EditPlan,
    ExperienceConfirmation, GeneratePlan, MilestoneOutcome, MoveTask, PaceAction, PauseWeek, Runway, RollDetail, RunwayRequest, SaveConfig, TaskReference, UndoEvent, UpdateTask)
from app.schemas.planner import Mutation, Workspace

LEGACY_MESSAGE='This roadmap was made in an older format, so it stays read-only. Start a new roadmap to use the weekly planner.'

def current_plan(row):
    plan=planner_state(row)['active']
    if not plan:raise Problem('Accept a roadmap before recording progress.')
    if not schedule.is_current_schema(plan):raise Problem(LEGACY_MESSAGE,409,'legacy_plan')
    return plan

def register_planner(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner'
    clock=lambda:app.state.clock()
    def plan_change(action):
        """A mutation on the active roadmap: action receives the plan and the row, and may raise a Problem."""
        def apply(row,source):
            action(current_plan(row),row)
            return row
        return apply

    @app.post(prefix+'/runway',response_model=Runway)
    async def runway(body:RunwayRequest,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        capacity=Capacity(body.config,clock(),completed_sessions(state['active']))
        return capacity.report(allow_past_start=bool(state['active']))

    @app.post(prefix+'/config',response_model=Workspace)
    async def save_config(body:SaveConfig,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            today=Capacity(body.config,clock()).today
            planner_state(row)['config']=normalized(body.config,today).model_dump(mode='json')
            return row
        return await mutate(body,account,apply)

    async def start(body,account,kind,check=None):
        """Begin a saved operation, reusing a repeated or failed request's identity."""
        row=await thread(app.state.store.load,account['id'])
        repeated=any(r['id']==str(body.mutation_id) for r in row['receipts']) or (row.get('pending') or {}).get('id')==str(body.mutation_id)
        if not repeated and check:await check(row)
        row=await thread(begin,app.state.store,account['id'],body,kind,PLANNING_SECONDS)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.post(prefix+'/generate',status_code=202)
    async def generate(body:GeneratePlan,request:Request,account=Depends(authenticated)):
        async def check(row):
            state=planner_state(row)
            source=await context(account)
            if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
            report=Capacity(saved_config(state),clock(),completed_sessions(state['active'])).report(allow_past_start=bool(state['active']))
            if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
        return await start(body,account,'generate',check)

    @app.post(prefix+'/accept',response_model=Workspace)
    async def accept(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row);now=clock()
            if not state['candidate']:raise Problem('There is no previewed roadmap to accept.')
            blockers=candidate_blockers(state,source,now)
            if blockers:raise Problem(blockers[0]['message'],409,blockers[0]['code'])
            previous=state['active']
            if previous:
                # Saved before this write commits, under an id derived from the request, then read-only.
                identifier=str(uuid5(NAMESPACE_URL,account['id']+':archive:'+str(body.mutation_id)))
                state['archived'].append(archive_summary(previous,identifier,now.isoformat()))
                state['completed_work']=[*state['completed_work'],*finished_records(previous)][-COMPLETED_WORK_LIMIT:]
            state['active']=state['candidate'];state['candidate']=None;state['proposal']=None
            state['active']['accepted_at']=now.isoformat()
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/discard',response_model=Workspace)
    async def discard(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            planner_state(row)['candidate']=None
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/assignments/status',response_model=Workspace)
    async def assignment_status(body:AssignmentStatus,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            task=next((a for a in plan['assignments'] if a['id']==body.assignment_id),None)
            if not task:raise Problem('This session was not found.',404,'not_found')
            now=clock();capacity=schedule.plan_capacity(plan,now)
            note=body.evidence_note.strip() if body.evidence_note else None
            if body.status=='completed':schedule.complete_task(plan,task,note,body.feedback,now,capacity)
            else:schedule.reopen_task(plan,task,now,capacity)
        return await mutate(body,account,plan_change(action))

    @app.post(prefix+'/tasks/skip',response_model=Workspace)
    async def skip(body:TaskReference,request:Request,account=Depends(authenticated)):
        return await mutate(body,account,plan_change(lambda plan,row:schedule.skip_task(plan,schedule.by_id(plan,body.task_id),clock())))
    @app.post(prefix+'/tasks/restore',response_model=Workspace)
    async def restore(body:TaskReference,request:Request,account=Depends(authenticated)):
        return await mutate(body,account,plan_change(lambda plan,row:schedule.restore_task(plan,schedule.by_id(plan,body.task_id),clock())))
    @app.post(prefix+'/tasks/move',response_model=Workspace)
    async def move(body:MoveTask,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            schedule.move_task(plan,schedule.by_id(plan,body.task_id),body.date,body.start_time,clock(),body.confirm_outside_blocks)
        return await mutate(body,account,plan_change(action))
    @app.post(prefix+'/tasks/update',response_model=Workspace)
    async def update(body:UpdateTask,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            task=schedule.by_id(plan,body.task_id);fields=body.model_fields_set;now=clock()
            if 'pinned' in fields and body.pinned is not None:task['pinned']=body.pinned
            if 'note' in fields:task['note']=(body.note or '').strip() or None
            if 'feedback' in fields:
                if task['status']!='completed':raise Problem('Give feedback after completing the task.',409,'task_unfinished')
                task['feedback']=body.feedback
                plan['progress_revision']=plan.get('progress_revision',0)+1
            if 'count_hours' in fields and body.count_hours is not None:
                if task['origin']!='custom':raise Problem('Only custom tasks can be excluded from hours.',409,'task_generated')
                if body.count_hours and not task.get('count_hours',True) and task['status']=='scheduled':
                    # Counting it again must still fit the weekly maximum.
                    board=schedule.Board(plan,now);week=schedule.week_of(schedule.day_of(task))
                    if board.used.get(week,0)+task['duration_minutes']>board.capacity.cap:raise Problem('Counting this task would pass that week’s maximum. Move it or keep it excluded.',409,'weekly_maximum')
                task['count_hours']=body.count_hours
            schedule.changed(plan,task,now,'updated',fields=sorted(fields-{'expected_version','mutation_id','task_id'}))
            if task['origin']=='custom':plan['progress_revision']=plan.get('progress_revision',0)+1
        return await mutate(body,account,plan_change(action))
    @app.post(prefix+'/tasks/custom',response_model=Workspace)
    async def custom(body:CustomTask,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            now=clock();capacity=schedule.plan_capacity(plan,now)
            if len(plan['assignments'])>=2000:raise Problem('This roadmap reached its task limit.',413,'workspace_capacity')
            if body.week_start.weekday()!=0:raise Problem('Choose a Monday-to-Sunday week.',422,'validation')
            if capacity.target and body.week_start>capacity.target:raise Problem('Choose a week before your target date.',409,'after_target')
            if body.milestone_key and not any(m['key']==body.milestone_key for m in plan['milestones']):raise Problem('This milestone was not found.',404,'not_found')
            identifier=str(uuid5(NAMESPACE_URL,'custom:'+str(body.mutation_id)))
            task={'id':identifier,'key':identifier,'origin':'custom','kind':'custom','milestone_key':body.milestone_key,'gap_id':None,'task':body.title,'completion_criterion':None,'depends_on':[],'refresher_reason':None,
                'week_start':body.week_start.isoformat(),'date':None,'start_time':None,'duration_minutes':body.duration_minutes,'status':'backlog','pinned':False,'count_hours':body.count_hours,
                'note':(body.note or '').strip() or None,'evidence_note':None,'feedback':None,'completed_at':None,'auto_moves':0,'manual_moves':0,'action_needed':None,
                'backlog_reason':'No time chosen yet.','removed_reason':None,'baseline':None,'revision':0,'history':[]}
            if body.date and body.start_time:
                schedule.check_placement(plan,task,body.date,body.start_time,now,body.confirm_outside_blocks)
                plan['assignments'].append(task)
                schedule.move_task(plan,task,body.date,body.start_time,now,body.confirm_outside_blocks)
                task['manual_moves']=0
            else:plan['assignments'].append(task)
            plan['revision']=plan.get('revision',0)+1;plan['progress_revision']=plan.get('progress_revision',0)+1
            schedule.add_event(plan,f'custom:{identifier}','custom_added',now,f'Added “{body.title}”',task_id=identifier)
        return await mutate(body,account,plan_change(action))
    @app.post(prefix+'/events/undo',response_model=Workspace)
    async def undo(body:UndoEvent,request:Request,account=Depends(authenticated)):
        return await mutate(body,account,plan_change(lambda plan,row:schedule.undo_event(plan,body.event_id,clock())))

    @app.post(prefix+'/milestones/outcome',response_model=Workspace)
    async def milestone_outcome(body:MilestoneOutcome,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            milestone=next((m for m in plan['milestones'] if m['id']==body.milestone_id),None)
            if not milestone:raise Problem('This milestone was not found.',404,'not_found')
            note=(body.note or '').strip()
            if body.demonstrated and not note:raise Problem('Describe how you demonstrated this outcome.',422,'validation')
            milestone['outcome']={'demonstrated':body.demonstrated,'note':note or None,'recorded_at':clock().isoformat(),'source':'self_reported'}
        return await mutate(body,account,plan_change(action))
    @app.post(prefix+'/milestones/complete',response_model=Workspace)
    async def milestone_complete(body:CompleteMilestone,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            now=clock();milestone=next((m for m in plan['milestones'] if m['id']==body.milestone_id),None)
            if not milestone:raise Problem('This milestone was not found.',404,'not_found')
            if not body.completed:
                if milestone.get('completion'):
                    milestone['completion']=None;plan['revision']=plan.get('revision',0)+1;plan['progress_revision']=plan.get('progress_revision',0)+1
                    schedule.add_event(plan,f"milestone-open:{milestone['id']}:{plan['revision']}",'milestone_reopened',now,f"Reopened “{milestone['title']}”")
                return
            if milestone.get('completion'):return
            unfinished=[t for t in plan['assignments'] if t.get('milestone_key')==milestone['key'] and t['origin']=='generated' and t['status'] in schedule.UNFINISHED]
            if unfinished and not body.unfinished:raise Problem(f"{len(unfinished)} unfinished task(s) remain under this milestone. Choose whether to keep them scheduled or remove them from remaining scope.",409,'milestone_choice_required')
            if body.unfinished=='remove':
                for task in unfinished:
                    origin=schedule.placement(task)
                    task.update(status='removed',removed_reason='milestone_completed',action_needed=None)
                    schedule.changed(plan,task,now,'removed_from_scope',origin=origin)
            milestone['completion']={'at':now.isoformat(),'unfinished_choice':body.unfinished if unfinished else None,'source':'self_reported'}
            plan['revision']=plan.get('revision',0)+1;plan['progress_revision']=plan.get('progress_revision',0)+1
            schedule.add_event(plan,f"milestone:{milestone['id']}:{plan['revision']}",'milestone_completed',now,f"Completed “{milestone['title']}”")
        return await mutate(body,account,plan_change(action))

    @app.post(prefix+'/confirmations',response_model=Workspace)
    async def confirmation(body:ExperienceConfirmation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row)
            plan=state['candidate'] or state['active']
            gap=next((g for g in (plan or {}).get('gaps',[]) if g['id']==body.gap_id),None)
            if not gap:raise Problem('This question was not found in your plan.',404,'not_found')
            state['confirmations'][body.gap_id]={'name':gap['name'],'question':gap.get('confirmation_question'),'answer':body.answer,
                'note':(body.note or '').strip() or None,'source':'self_reported','recorded_at':clock().isoformat()}
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/rolling',status_code=202)
    async def rolling(body:RollDetail,request:Request,account=Depends(authenticated)):
        async def check(row):
            current_plan(row)
            if not app.state.model.configured:raise Problem('Your adviser is unavailable. Your saved plan is unchanged.',503,'model_not_configured')
        return await start(body,account,'rolling',check)

    @app.post(prefix+'/checkins/answer',response_model=Workspace)
    async def checkin_answer(body:CheckinAnswer,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            now=clock();week=open_week(plan,now)
            if week!=body.week_start:raise Problem('This check-in isn’t open any more.',409,'checkin_closed')
            plan.setdefault('checkins',{})
            record=plan['checkins'].get(body.week_start.isoformat(),{})
            plan['checkins'][body.week_start.isoformat()]={**record,'status':'answered','answers':{'week_feel':body.week_feel,'next_week':body.next_week,'note':(body.note or '').strip() or None},'answered_at':now.isoformat()}
            planner_state(row)['proposal']=None
        return await mutate(body,account,plan_change(action))
    @app.post(prefix+'/checkins/propose',status_code=202)
    async def checkin_propose(body:CheckinPropose,request:Request,account=Depends(authenticated)):
        async def check(row):
            plan=current_plan(row)
            if not app.state.model.configured:raise Problem('Your adviser is unavailable. Your answers are saved.',503,'model_not_configured')
            if open_week(plan,clock())!=body.week_start:raise Problem('This check-in isn’t open any more.',409,'checkin_closed')
        return await start(body,account,'checkin',check)

    def prepare(body,account,build):
        """Store a deterministic preview. Nothing on the plan changes."""
        def action(plan,row):
            planner_state(row)['proposal']=build(plan)
        return mutate(body,account,plan_change(action))
    @app.post(prefix+'/proposals/pause',response_model=Workspace)
    async def propose_pause(body:PauseWeek,request:Request,account=Depends(authenticated)):
        return await prepare(body,account,lambda plan:proposals.pause_proposal(plan,body.week_start,clock(),body.mutation_id))
    @app.post(prefix+'/proposals/unpause',response_model=Workspace)
    async def propose_unpause(body:PauseWeek,request:Request,account=Depends(authenticated)):
        return await prepare(body,account,lambda plan:proposals.unpause_proposal(plan,body.week_start,clock(),body.mutation_id))
    @app.post(prefix+'/proposals/pace',response_model=Workspace)
    async def propose_pace(body:PaceAction,request:Request,account=Depends(authenticated)):
        def build(plan):
            if body.action=='cut_scope':return proposals.cut_scope(plan,clock(),body.mutation_id)
            if body.action=='add_hours':return proposals.add_hours(plan,body.extra_minutes,clock(),body.mutation_id)
            return proposals.move_date(plan,body.target_date,clock(),body.mutation_id)
        return await prepare(body,account,build)
    @app.post(prefix+'/proposals/edit',response_model=Workspace)
    async def propose_edit(body:EditPlan,request:Request,account=Depends(authenticated)):
        return await prepare(body,account,lambda plan:proposals.edit_proposal(plan,body.config,clock(),body.mutation_id))
    @app.post(prefix+'/proposals/scope',response_model=Workspace)
    async def propose_scope(body:BringDeferred,request:Request,account=Depends(authenticated)):
        return await prepare(body,account,lambda plan:proposals.scope_proposal(plan,body.deferred_id,body.target_date,clock(),body.mutation_id))
    @app.post(prefix+'/proposals/accept',response_model=Workspace)
    async def proposal_accept(body:AcceptProposal,request:Request,account=Depends(authenticated)):
        def action(plan,row):
            state=planner_state(row);proposal=state['proposal']
            if not proposal or proposal['id']!=body.proposal_id:raise Problem('This preview is no longer available. Prepare a fresh one.',409,'proposal_stale')
            blockers=proposals.proposal_blockers(state,clock())
            if blockers:raise Problem(blockers[0]['message'],409,blockers[0]['code'])
            proposals.apply_proposal(state,body.keep_task_ids,clock())
        return await mutate(body,account,plan_change(action))
    @app.post(prefix+'/proposals/discard',response_model=Workspace)
    async def proposal_discard(body:DiscardProposal,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row);proposal=state['proposal']
            if proposal and proposal['id']==body.proposal_id:
                if proposal['kind']=='checkin' and schedule.is_current_schema(state['active']):
                    record=state['active'].setdefault('checkins',{}).setdefault(proposal['week_start'],{})
                    record.update(status='completed',completed_at=clock().isoformat(),applied=False)
                state['proposal']=None
            return row
        return await mutate(body,account,apply)

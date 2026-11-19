"""One saved adviser conversation with proposed and active plans beside it."""
import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL
from fastapi import Depends,Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import application,authenticated,Problem,begin,launch,operation_view,stamp,digest
from app.schemas import Message,OperationAccepted,Workspace,Plan,PlannedRoadmap
from app.planning.chat import chat_turn
from app.planning.generator import PLANNING_SECONDS
from app.planning.outlines import accept_outline, prepare_outline
from app.planning.retired_settings import remove_retired_settings
from app.planning.routes import register_planner
from app.planning.state import planner_state,retry_body
from app.planning.state import plan_review, planning_source_changed
from app.planning.tasks import ensure_tasks,project_assignments,task_readiness
from app.planning.views import planner_view
from app.planning.weeks import prepare_week
from app.schemas.roadmap import DashboardSource

ROADMAP_CONTEXT_BYTES=250000

def create_app(store=None,upstream=None,model=None,clock=None):
    app=application('elo Roadmap Adviser API','ROADMAP',store=store,upstream=upstream,model=model,max_context_bytes=ROADMAP_CONTEXT_BYTES)
    app.state.clock=clock or (lambda:datetime.now(timezone.utc))
    shared_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(instance):
        async with shared_lifespan(instance):
            await thread(remove_retired_settings,instance.state.store)
            yield
    app.router.lifespan_context=lifespan
    async def context(account, tolerate_unavailable=False):
        try:source=await app.state.upstream.read('assessment','/api/v1/assessments/context',account['token'])
        except Problem as error:
            if not tolerate_unavailable or error.status in (401,403):raise
            source={'ready':False,'issues':[],'goal':None,'cv':None,'input_hash':None,'availability':'unavailable'}
        profile=account['profile']
        return {**source,'model_available':app.state.model.configured,'planning_defaults':{
            'application_date':profile.get('application_date'),'weekly_hours':profile.get('weekly_hours'),
            'availability_periods':profile.get('availability_periods',[])}}
    async def assessment(account):
        token=account['token']
        current=await app.state.upstream.read('assessment','/api/v1/assessments/current',token)
        def usable(value):
            profile=(value.get('result') or {}).get('skill_profile')
            return (value.get('stale') is False and profile and profile.get('status') in ('evaluated','partial','empty')
                and value.get('evaluation',{}).get('freshness')=='current')
        if usable(current):return current['result']
        if not current.get('ready'):raise Problem('Complete your selected CV and Career goal first.',409,'inputs_missing')
        if not current.get('operation') or current['operation']['status'] not in ('pending','running'):
            raise Problem('Evaluate your latest skills against your Career goal before generating a roadmap.',409,'assessment_required')
        for _ in range(60):
            await asyncio.sleep(2)
            state=await app.state.upstream.read('assessment','/api/v1/assessments/operation',token)
            operation=state.get('operation') or {}
            if operation.get('status')=='failed':
                error=operation.get('error') or {};raise Problem(error.get('detail','Assessment failed. Retry your saved planning message.'),409,error.get('code','assessment_failed'),operation.get('retry_after'))
            if state.get('result') and operation.get('status')=='succeeded':
                current=await app.state.upstream.read('assessment','/api/v1/assessments/current',token)
                if not usable(current):raise Problem('Your evaluation needs updating before planning. Update your evaluation and retry.',409,'assessment_required')
                return current['result']
        raise Problem('Assessment is still processing. Retry this saved planning message to reconnect.',503,'assessment_processing')
    async def worker(row,account):
        kind=row['pending']['kind']
        if kind=='outline_generate':
            if not row['pending']['body'].get('auto_accept',False):
                await prepare_outline(app,row,account,assessment,context)
                try:await prepare_week(app,row,account,context,initial=True)
                except Problem as error:
                    planner_state(row)['outline_candidate']['first_week_error']=error.detail
                return row
            # Previews are written to a working copy that is published only once the outline and first week validate.
            state={**planner_state(row)}
            await prepare_outline(app,row,account,assessment,context,into=state)
            week_prepared=await prepare_week(app,row,account,context,initial=True,into=state)
            state=copy.deepcopy(state)
            latest=await app.state.upstream.account(account['token'])
            if latest['id']!=account['id']:raise Problem('Your account changed during creation.',401,'session')
            source=await context(latest)
            accept_outline(state,source,state['outline_candidate']['id'],app.state.clock(),
                require_first_week=week_prepared or state['active'] is None)
            latest=await app.state.upstream.account(account['token'])
            if latest['id']!=account['id']:raise Problem('Your account changed during creation.',401,'session')
            fresh=await context(latest)
            if planning_source_changed(source,fresh):
                raise Problem('Your inputs changed during creation. Retry creating your roadmap.',409,'inputs_changed')
            active=state['active']
            # A new lease never reuses a failed attempt's tasks.
            active['id']=str(uuid5(NAMESPACE_URL,account['id']+':roadmap:'+row['pending']['id']+':'+row['pending']['token']))
            active.update(pace_baseline_id=active['id'],updated_at=stamp(),request_hash=row['pending']['hash'])
            state['active']=await thread(app.state.store.save_result,account['id'],active)
            row['planner']=state
        elif kind=='week_generate':
            await prepare_week(app,row,account,context)
        elif kind=='message':await chat_turn(app,row,account,assessment,context)
        else:raise Problem('This kind of request is no longer supported. Start it again from the roadmap page.',409,'operation_retired')
        return row

    def visible(row,source,time_zone=None):
        return {'version':row['version'],'messages':row['messages'],'draft':row.get('draft'),'active':row.get('active'),
            'assessment':row.get('assessment'),'operation':operation_view(row),'context':{k:v for k,v in source.items() if k!='evidence'},
            'stale':bool(row.get('active') and source.get('input_hash') and row['active']['assessment_hash']!=source['input_hash']),
            'retry_request':retry_body(row,'message'),'planner':planner_view(row,source,app.state.clock(),time_zone)}

    @app.get('/api/v1/roadmaps/workspace',response_model=Workspace)
    async def workspace(request:Request,time_zone:str|None=None,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return visible(row,await context(account,tolerate_unavailable=True),time_zone)
    @app.get('/api/v1/roadmaps/progress',response_model=OperationAccepted)
    async def progress(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.progress,account['id'])
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.get('/api/v1/roadmaps/dashboard-source',response_model=DashboardSource)
    async def dashboard_source(request:Request,account=Depends(authenticated)):
        # This read never resumes pending work or queries other source services.
        row=await thread(app.state.store.load,account['id'])
        active=copy.deepcopy(planner_state(row)['active'])
        if not active:return {'version':row['version'],'active':None,'active_review':None,'task_readiness':{}}
        tasks=ensure_tasks(active)
        project_assignments(active)
        readiness={task['id']:task_readiness(task,tasks,active) for task in tasks if not task.get('removed')}
        return {'version':row['version'],'active':active,'active_review':plan_review(active,app.state.clock()),'task_readiness':readiness}

    @app.post('/api/v1/roadmaps/messages',status_code=202,response_model=OperationAccepted)
    async def message(body:Message,request:Request,account=Depends(authenticated)):
        source=await context(account)
        if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
        row=await thread(begin,app.state.store,account['id'],body,'message',PLANNING_SECONDS)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    async def mutate(body,account,action,operation=None,mark_baseline=False):
        row=await thread(app.state.store.load,account['id']);payload=body.model_dump(mode='json');key=payload['mutation_id']
        # New task actions include their operation in the fingerprint.
        fingerprint=digest({'operation':operation,'payload':payload}) if operation else digest(payload)
        prior=next((r for r in row['receipts'] if r['id']==key),None)
        if prior:
            if prior['hash']!=fingerprint:raise Problem('This request key was used for a different change.')
            return visible(row,await context(account,tolerate_unavailable=True))
        if row.get('pending'):raise Problem('Wait for the current adviser response before applying a change.')
        if row['version']!=body.expected_version:raise Problem('Your plan changed in another session. Reload before applying the change.')
        if len(row['receipts'])>=1000:raise Problem('This workspace reached its retained-operation capacity.',413,'workspace_capacity')
        source=await context(account,tolerate_unavailable=True)
        updated=action(copy.deepcopy(row),source)
        # Authoritative account and input checks immediately before committing.
        fresh_account=await app.state.upstream.account(account['token'])
        if fresh_account['id']!=account['id']:raise Problem('Your account changed during saving.',401,'session')
        fresh=await context(fresh_account,tolerate_unavailable=True)
        if fresh.get('input_hash')!=source.get('input_hash') or mark_baseline and planning_source_changed(source,fresh):raise Problem('Your selected inputs, evaluation or availability changed during saving. Refresh and retry.',409,'inputs_changed')
        updated['receipts'].append({'id':key,'hash':fingerprint})
        accepted=planner_state(updated)['active']
        if accepted and accepted!=planner_state(row)['active']:
            accepted['id']=str(uuid5(NAMESPACE_URL,account['id']+':roadmap:'+key))
            if mark_baseline:accepted['pace_baseline_id']=accepted['id']
            accepted['updated_at']=stamp()
            accepted['request_hash']=fingerprint
            updated['planner']['active']=await thread(app.state.store.save_result,account['id'],accepted)
        saved=await thread(app.state.store.cas,account['id'],row['version'],updated)
        return visible(saved,fresh)

    register_planner(app,context,mutate,worker)

    @app.get('/api/v1/roadmaps/history/{identifier}',response_model=PlannedRoadmap|Plan)
    async def history(identifier:str,request:Request,account=Depends(authenticated)):
        return await thread(app.state.store.result,account['id'],identifier)
    return app
app=create_app()

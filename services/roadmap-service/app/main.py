"""One saved adviser conversation with proposed and active plans beside it."""
import asyncio
import copy
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL
from fastapi import Depends,Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import application,authenticated,Problem,begin,launch,operation_view,stamp,digest
from app.schemas import Message,Workspace,Plan,PlannedRoadmap
from app.planning.generator import PLANNING_SECONDS,chat_turn,prepare_plan
from app.planning.routes import register_planner
from app.planning.state import planner_state,planner_view,retry_body

def create_app(store=None,upstream=None,model=None,clock=None):
    app=application('elo Roadmap Adviser API','ROADMAP',store=store,upstream=upstream,model=model)
    app.state.clock=clock or (lambda:datetime.now(timezone.utc))
    async def context(account, tolerate_unavailable=False):
        try:source=await app.state.upstream.read('assessment','/api/v1/assessments/context',account['token'])
        except Problem as error:
            if not tolerate_unavailable or error.status in (401,403):raise
            source={'ready':False,'issues':[],'goal':None,'cv':None,'input_hash':None,'availability':'unavailable'}
        profile=account['profile']
        return {**source,'model_available':app.state.model.configured,'planning_defaults':{
            'application_date':profile.get('application_date'),'weekly_hours':profile.get('weekly_hours'),
            'availability_periods':profile.get('availability_periods',[])}}
    async def assessment(account,operation_id,allow_partial):
        token=account['token']
        current=await app.state.upstream.read('assessment','/api/v1/assessments/current',token)
        if current.get('result') and not current.get('stale'):return current['result']
        if not current.get('ready'):raise Problem('Complete your selected CV and Career goal first.',409,'inputs_missing')
        if not current.get('operation') or current['operation']['status'] not in ('pending','running'):
            request={'expected_version':current['version'],'mutation_id':str(uuid5(NAMESPACE_URL,operation_id+':assessment')),'allow_partial':allow_partial}
            progress=await app.state.upstream.read('assessment','/api/v1/assessments/operation',token)
            if (progress.get('operation') or {}).get('status')=='failed' and (progress.get('retry_request') or {}).get('mutation_id')==request['mutation_id']:
                request=progress['retry_request']
            await app.state.upstream.write('assessment','/api/v1/assessments',token,request)
        for _ in range(90):
            await asyncio.sleep(1)
            state=await app.state.upstream.read('assessment','/api/v1/assessments/operation',token)
            operation=state.get('operation') or {}
            if operation.get('status')=='failed':
                error=operation.get('error') or {};raise Problem(error.get('detail','Assessment failed. Retry your saved planning message.'),409,error.get('code','assessment_failed'),operation.get('retry_after'))
            if state.get('result') and operation.get('status')=='succeeded':
                current=await app.state.upstream.read('assessment','/api/v1/assessments/current',token)
                if current.get('stale'):raise Problem('Your inputs changed during assessment. Retry with the current inputs.',409,'inputs_changed')
                return current['result']
        raise Problem('Assessment is still processing. Retry this saved planning message to reconnect.',503,'assessment_processing')
    async def worker(row,account):
        if row['pending']['kind']=='generate':await prepare_plan(app,row,account,assessment,context)
        else:await chat_turn(app,row,account,assessment,context)
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
    @app.get('/api/v1/roadmaps/progress')
    async def progress(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.progress,account['id'])
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}


    @app.post('/api/v1/roadmaps/messages',status_code=202)
    async def message(body:Message,request:Request,account=Depends(authenticated)):
        source=await context(account)
        if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
        row=await thread(begin,app.state.store,account['id'],body,'message',PLANNING_SECONDS)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    async def mutate(body,account,action,operation=None):
        row=await thread(app.state.store.load,account['id']);payload=body.model_dump(mode='json');key=payload['mutation_id']
        # Existing receipts retain their original fingerprint. New task actions
        # include their operation so a key cannot replay a different endpoint.
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
        if fresh.get('input_hash')!=source.get('input_hash'):raise Problem('Your selected inputs changed during saving. Refresh and retry.',409,'inputs_changed')
        updated['receipts'].append({'id':key,'hash':fingerprint})
        accepted=planner_state(updated)['active']
        if accepted and accepted!=planner_state(row)['active']:
            accepted['id']=str(uuid5(NAMESPACE_URL,account['id']+':roadmap:'+key))
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

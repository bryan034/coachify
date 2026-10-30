"""One saved adviser conversation with proposed and active plans beside it."""
import asyncio
import copy
from datetime import datetime
from uuid import uuid5,NAMESPACE_URL
from zoneinfo import ZoneInfo
from fastapi import Depends,Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import application,authenticated,Problem,begin,launch,operation_view,stamp,digest
from app.schemas import Mutation,Message,EditTask,TaskStatus,SavePreferences,RemoveTask,AdviserReply,Preferences,Workspace,Plan,TaskDefinition
from app.adviser import INSTRUCTIONS,propose
from app.scheduler import reschedule_plan,review_saved

def create_app(store=None,upstream=None,model=None):
    app=application('elo Roadmap Adviser API','ROADMAP',store=store,upstream=upstream,model=model)
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
        body=row['pending']['body'];operation_id=row['pending']['id']
        if row.get('draft') and row['draft'].get('base_active_id')!=(row.get('active') or {}).get('id'):
            raise Problem('The active plan changed after this proposal. Discard the old proposal before discussing another revision.')
        result=await assessment(account,operation_id,body['allow_partial_assessment'])
        source=await context(account)
        if not source['ready'] or source.get('input_hash')!=result['input_hash']:raise Problem('Your selected inputs changed. Refresh before planning.',409,'inputs_changed')
        # Only structured assessment evidence and this owner's recent bounded messages.
        plan=row.get('draft') or row.get('active')
        output=await app.state.model.generate(AdviserReply,INSTRUCTIONS,{
            'current_date':datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat(),'time_zone':'Asia/Singapore',
            'goal':source['goal'],'assessment':{k:result[k] for k in ('id','target_type','job_skill_gaps','interview_prep_gaps','constraints','groups','priorities','research_coverage','evidence')},
            'evidence':result['evidence'],'planning_defaults':source['planning_defaults'],
            'current_plan':plan,'messages':row['messages'][-12:],'history_window':'Latest 12 messages; the structured plan preserves earlier choices.',
            'user_message':body['message']})
        changed=bool(output.task_changes or output.remove_tasks or output.scope_exclusions or output.scope_inclusions or any(v is not None and v is not False for k,v in output.preferences.model_dump().items()))
        if changed:
            if not plan:
                row['preferences']=Preferences(reduced_periods=source['planning_defaults']['availability_periods']).model_dump(mode='json')
            row['draft']=propose(row,output,result,body['message'],operation_id)
        row['assessment']={k:result[k] for k in ('id','input_hash','role','job_skill_gaps','interview_prep_gaps','constraints','groups','priorities','research_coverage','evidence')}
        row['messages'].append({'id':operation_id+':reply','role':'assistant','content':output.reply,'created_at':stamp()})
        latest_account=await app.state.upstream.account(account['token'])
        if latest_account['id']!=account['id']:raise Problem('Your account changed while preparing advice.',401,'session')
        fresh=await context(latest_account)
        if fresh.get('input_hash')!=source['input_hash']:raise Problem('Your evidence or goal changed while preparing this advice. Retry with the latest inputs.',409,'inputs_changed')
        return row

    def visible(row,source):
        return {'version':row['version'],'messages':row['messages'],'draft':row.get('draft'),'active':row.get('active'),
            'assessment':row.get('assessment'),'operation':operation_view(row),'context':source,
            'stale':bool(row.get('active') and source.get('input_hash') and row['active']['assessment_hash']!=source['input_hash']),
            'retry_request':(row.get('last_operation') or {}).get('body') if (row.get('last_operation') or {}).get('status')=='failed' else None}

    @app.get('/api/v1/roadmaps/workspace',response_model=Workspace)
    async def workspace(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id'])
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return visible(row,await context(account,tolerate_unavailable=True))
    @app.get('/api/v1/roadmaps/progress')
    async def progress(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.progress,account['id'])
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.post('/api/v1/roadmaps/messages',status_code=202)
    async def message(body:Message,request:Request,account=Depends(authenticated)):
        source=await context(account)
        if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
        row=await thread(begin,app.state.store,account['id'],body,'message')
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    async def mutate(body,account,action):
        row=await thread(app.state.store.load,account['id']);payload=body.model_dump(mode='json');key=payload['mutation_id'];fingerprint=digest(payload)
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
        if updated.get('active') and updated['active']!=row.get('active'):
            updated['active']['id']=str(uuid5(NAMESPACE_URL,account['id']+':plan:'+key))
            updated['active']['updated_at']=stamp()
            updated['active']['request_hash']=fingerprint
            updated['active']=await thread(app.state.store.save_result,account['id'],updated['active'])
        saved=await thread(app.state.store.cas,account['id'],row['version'],updated)
        return visible(saved,fresh)

    @app.post('/api/v1/roadmaps/activate',response_model=Workspace)
    async def activate(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            draft=row.get('draft')
            if not draft:raise Problem('There is no proposed plan to apply.')
            if draft.get('base_active_id')!=(row.get('active') or {}).get('id'):raise Problem('Your active plan changed after this proposal. Discard it and prepare a fresh revision.')
            valid_refs={r['ref'] for name in ('job_skill_gaps','interview_prep_gaps','constraints') for r in draft['assessment'][name]}
            if any(ref not in valid_refs for t in draft['tasks'] if not t.get('removed') for ref in t['requirement_refs']):raise Problem('Some tasks still reference an earlier goal. Reconcile their links in chat before applying this proposal.')
            if not source['ready'] or draft['assessment_hash']!=source.get('input_hash'):raise Problem('The proposal uses changed inputs. Reassess before applying it.',409,'inputs_changed')
            if draft['schedule']['status']=='needs_preferences':raise Problem('Choose your timeline, weekly hours and workdays before starting this plan.')
            if row.get('active') and all(row['active'].get(k)==draft.get(k) for k in ('assessment_id','assessment_hash','tasks','preferences','exclusions')):
                row['draft']=None;return row
            row['active']=draft;row['draft']=None
            row['messages'].append({'id':str(body.mutation_id)+':activated','role':'assistant','content':'Your chosen plan is saved. We can keep adjusting it together as your circumstances change.','created_at':stamp()})
            return row
        return await mutate(body,account,apply)

    @app.post('/api/v1/roadmaps/draft/discard',response_model=Workspace)
    async def discard(body:Mutation,request:Request,account=Depends(authenticated)):
        return await mutate(body,account,lambda row,source:{**row,'draft':None})

    @app.post('/api/v1/roadmaps/preferences',response_model=Workspace)
    async def preferences(body:SavePreferences,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=copy.deepcopy(row.get('draft') or row.get('active'))
            if not plan:
                if not row.get('assessment'):raise Problem('Discuss your goal with the adviser before creating a plan.')
                plan={'id':str(uuid5(NAMESPACE_URL,str(body.mutation_id)+':draft')),'tasks':[],'assessment_id':row['assessment']['id'],'assessment_hash':row['assessment']['input_hash'],'exclusions':[]}
            if not row.get('draft'):plan['base_active_id']=(row.get('active') or {}).get('id')
            plan.setdefault('assessment',row.get('assessment'))
            plan['preferences']=body.preferences.model_dump(mode='json')
            plan['schedule']=reschedule_plan(plan);row['draft']=plan;return row
        return await mutate(body,account,apply)

    @app.post('/api/v1/roadmaps/tasks',response_model=Workspace)
    async def edit(body:EditTask,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=row.get('active')
            if not plan:raise Problem('Start a plan before editing its tasks.')
            task=next((t for t in plan['tasks'] if t['id']==body.task.id),None)
            if task and task.get('removed'):raise Problem('This task has been removed.')
            valid_refs={r['ref'] for name in ('job_skill_gaps','interview_prep_gaps','constraints') for r in plan['assessment'][name]}
            if not set(body.task.requirement_refs)<=valid_refs:raise Problem('Choose requirement links from this assessment.')
            if any(p not in {t['id'] for t in plan['tasks']} for p in body.task.prerequisites):raise Problem('Choose prerequisites from this plan.')
            data=body.task.model_dump();overrides=list(data)
            if task and body.base_definition:
                base=body.base_definition.model_dump()
                if base['id']!=data['id']:raise Problem('The edited activity identity does not match its original definition.')
                changes={k:v for k,v in data.items() if base[k]!=v}
                if any(task.get(k)!=base[k] for k in changes):raise Problem('An edited field changed in another session. Reopen the activity editor to reconcile it.')
                data={**{k:task[k] for k in TaskDefinition.model_fields},**changes};overrides=list(changes)
            if task:
                if all(task.get(k)==v for k,v in data.items()):return row
                task.setdefault('history',[]).append({'at':stamp(),'definition':{k:task.get(k) for k in data},'status':task['status']})
                if task['completion_outcome']!=data['completion_outcome'] or (task['status']=='completed' and task['instructions']!=data['instructions']):task['definition_review_required']=True
                task.update(data);task['user_overrides']=list(dict.fromkeys([*task.get('user_overrides',[]),*overrides]))
            else:plan['tasks'].append({**data,'status':'not_started','provenance':'user_created','history':[],'user_overrides':list(data)})
            plan['schedule']=review_saved(plan);return row
        return await mutate(body,account,apply)

    @app.post('/api/v1/roadmaps/tasks/remove',response_model=Workspace)
    async def remove(body:RemoveTask,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=row.get('active')
            task=next((t for t in (plan or {}).get('tasks',[]) if t['id']==body.task_id),None)
            if not task:raise Problem('This task was not found.',404,'not_found')
            if task.get('removed'):return row
            task.update(removed=True,removed_at=stamp());plan['schedule']=review_saved(plan);return row
        return await mutate(body,account,apply)

    @app.post('/api/v1/roadmaps/tasks/status',response_model=Workspace)
    async def status(body:TaskStatus,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=row.get('active');task=next((t for t in (plan or {}).get('tasks',[]) if t['id']==body.task_id and not t.get('removed')),None)
            if not task:raise Problem('This active task was not found.',404,'not_found')
            if task['status']==body.status:return row
            if task['status']=='in_progress' and body.status=='not_started':raise Problem('Only completed tasks can be explicitly reopened to not started.')
            task.setdefault('history',[]).append({'at':stamp(),'from':task['status'],'to':body.status,'definition':{k:task[k] for k in ('title','instructions','completion_outcome','estimated_minutes')}})
            task['status']=body.status
            if body.status=='completed':task.update(completed_at=stamp(),definition_review_required=False)
            else:
                task['completed_at']=None
                if body.status=='in_progress':task.setdefault('started_at',stamp())
            plan['schedule']=review_saved(plan);return row
        return await mutate(body,account,apply)

    @app.get('/api/v1/roadmaps/history/{identifier}',response_model=Plan)
    async def history(identifier:str,request:Request,account=Depends(authenticated)):
        return await thread(app.state.store.result,account['id'],identifier)
    return app
app=create_app()

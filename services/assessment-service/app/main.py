from uuid import uuid5, NAMESPACE_URL
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import application, authenticated, Problem, begin, launch, operation_view, stamp, digest
from app.schemas import Generate, Result, Context, Current, DashboardSource, batch_schema
from app.inputs import capture
from app.domain import INSTRUCTIONS, validate_batch, group_outcome
from app.skills import evaluate_skills, link_profile
from app.competence import RUBRIC_VERSION

def create_app(store=None,upstream=None,model=None):
    app=application('elo Assessment API','ASSESSMENT',store=store,upstream=upstream,model=model)
    async def worker(row,account):
        snapshot=await capture(app.state.upstream,account)
        if not snapshot['ready']:raise Problem('Complete the selected CV and Career goal before assessment.',409,'inputs_missing')
        if snapshot['research_coverage'] not in ('available','no_findings') and not row['pending']['body']['allow_partial']:
            raise Problem('Interview research is unavailable, incomplete or stale. Retry research or choose a labelled target-only analysis.',409,'research_partial')
        checkpoint=row['pending'].get('checkpoint')
        # A pre-v2 checkpoint can restart with the new rubric only when the exact
        # source revisions still match. Never reuse its already inflated scores.
        if checkpoint and checkpoint.get('scoring_rubric')!=RUBRIC_VERSION and checkpoint['input_hash']==digest(snapshot['inputs']):
            checkpoint=None
        if checkpoint and checkpoint['input_hash']!=snapshot['input_hash']:raise Problem('The captured inputs changed. Start a new assessment with the latest inputs.',409,'inputs_changed')
        if checkpoint:
            snapshot=checkpoint['snapshot'];outcomes=checkpoint['outcomes']
        else:
            outcomes=[]
            row['pending']['checkpoint']={'input_hash':snapshot['input_hash'],'scoring_rubric':RUBRIC_VERSION,'snapshot':snapshot,'outcomes':outcomes}
            await thread(app.state.store.checkpoint,account['id'],row)
        for start in range(len(outcomes),len(snapshot['requirements']),8):
            verified=await app.state.upstream.account(account['token'])
            if verified['id']!=account['id']:raise Problem('Your account changed during assessment.',401,'session')
            live=await capture(app.state.upstream,verified)
            if live.get('input_hash')!=snapshot['input_hash']:raise Problem('Your inputs changed before the next comparison step.',409,'inputs_changed')
            requirements=snapshot['requirements'][start:start+8]
            model_context={'requirements':requirements,'evidence':snapshot['evidence']}
            schema=batch_schema(requirements,snapshot['evidence'])
            for attempt in range(2):
                output=await app.state.model.generate(schema,INSTRUCTIONS,model_context)
                try:
                    validated=validate_batch(output,requirements,snapshot['evidence'])
                    break
                except Problem as error:
                    if error.code!='assessment_output' or attempt:
                        raise
                    # Only fixed local validation guidance is sent back. Provider
                    # failures do not enter repair, and no rejected batch is saved.
                    model_context={**model_context,'validation_feedback':getattr(error,'feedback',None) or error.detail,
                                   'previous_output':output.model_dump(mode='json')}
            outcomes.extend(validated)
            row['pending']['checkpoint']['outcomes']=outcomes
            row['pending']['stage']='assessed_'+str(len(outcomes))
            await thread(app.state.store.checkpoint,account['id'],row)
        # Per-skill category, relevance and competence, judged from the same reviewed evidence.
        judged=row['pending']['checkpoint'].setdefault('skill_batches',[])
        async def save_skills():
            row['pending']['checkpoint']['skill_batches']=judged
            row['pending']['stage']='skills_'+str(len(judged))
            await thread(app.state.store.checkpoint,account['id'],row)
        skill_profile=await evaluate_skills(app.state.model,snapshot,outcomes,judged,save_skills)
        link_profile(outcomes,skill_profile)
        groups={}
        for outcome in outcomes:
            if outcome.get('group_id') and outcome['kind']!='interview_preparation':groups.setdefault(outcome['group_id'],[]).append(outcome)
        group_results=[]
        for key,items in groups.items():
            operators={i.get('group_operator','all') for i in items}
            if len(operators)!=1:raise Problem('A requirement group has conflicting AND/OR operators. Review the goal.',409,'goal_conditions')
            operator=next(iter(operators))
            group_results.append({'id':key,'operator':operator,'requirement_refs':[i['ref'] for i in items],
                'match_status':group_outcome(items,operator),
                'known_shortfall_refs':[i['ref'] for i in items if any(c['status']=='confirmed_shortfall' for c in i['components'])]})
        satisfied_or={ref for group in group_results if group['operator']=='any' and group['match_status']=='supported' for ref in group['requirement_refs']}
        priorities=[o['ref'] for o in sorted(outcomes,key=lambda o:({'required':0,'preferred':1,'unspecified':2,'conflicting':3,'suggested':4}.get(o.get('priority'),2),o['ref']))
            if o['kind']!='constraint' and o['ref'] not in satisfied_or and any(c['status']=='confirmed_shortfall' for c in o['components'])]
        current_account=await app.state.upstream.account(account['token'])
        if current_account['id']!=account['id']:raise Problem('Your account changed during assessment.',401,'session')
        fresh=await capture(app.state.upstream,current_account)
        if fresh.get('input_hash')!=snapshot['input_hash']:raise Problem('Your evidence or goal changed during assessment. Refresh and retry.',409,'inputs_changed')
        identifier=str(uuid5(NAMESPACE_URL,'assessment:'+account['id']+':'+row['pending']['id']))
        result={'request_hash':row['pending']['hash'],'schema_version':'assessment-v1','id':identifier,'created_at':stamp(),'inputs':snapshot['inputs'],
            'input_hash':snapshot['input_hash'],'source_snapshot':snapshot['source_snapshot'],'evidence':snapshot['evidence'],
            'target_type':snapshot['goal']['target_type'],'role':snapshot['goal']['role'],
            'job_skill_gaps':[o for o in outcomes if o['kind']=='job_skill'],
            'interview_prep_gaps':[o for o in outcomes if o['kind']=='interview_preparation'],
            'constraints':[o for o in outcomes if o['kind']=='constraint'],'groups':group_results,'priorities':priorities,
            'analysis_status':'succeeded' if snapshot['research_coverage'] in ('available','no_findings') else 'partial',
            'research_coverage':snapshot['research_coverage'],'skill_profile':skill_profile}
        result=await thread(app.state.store.save_result,account['id'],result)
        row['result']=result;return row

    @app.get('/api/v1/assessments/context',response_model=Context)
    async def context(request:Request,account=Depends(authenticated)):
        """What an evaluation would read, and which setup step is still open. Never starts one."""
        snapshot=await capture(app.state.upstream,account)
        return {k:snapshot.get(k) for k in ('ready','issues','goal','cv','input_hash','inputs','research_coverage','evidence','cv_reviewed','research_pending')} | {'model_available':app.state.model.configured}

    @app.get('/api/v1/assessments/current',response_model=Current)
    async def current(request:Request,account=Depends(authenticated)):
        """Read the saved comparison and resume a pending one. A new comparison starts only from the explicit command."""
        row=await thread(app.state.store.load,account['id'])
        snapshot=await capture(app.state.upstream,account)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        result=row.get('result')
        return {'version':row['version'],'operation':operation_view(row),'result':result,
            'stale':bool(result and result['input_hash']!=snapshot.get('input_hash')),'ready':snapshot['ready'],'issues':snapshot['issues']}

    @app.get('/api/v1/assessments/dashboard-source',response_model=DashboardSource)
    async def dashboard_source(request:Request,account=Depends(authenticated)):
        """Read the saved result and freshness without resuming an operation."""
        owner=account['id']
        row=await thread(app.state.store.load,owner)
        snapshot=None;failure=None
        try:
            snapshot=await capture(app.state.upstream,account)
        except Problem as error:
            if error.status in (401,403):raise
            failure='conflict' if error.status==409 else 'unavailable'
        latest=await thread(app.state.store.load,owner)
        if latest['version']!=row['version'] or (latest.get('result') or {}).get('id')!=(row.get('result') or {}).get('id'):
            raise Problem('Assessment changed while preparing dashboard data. Retry.',409,'source_changed')
        result=row.get('result')
        if failure:
            freshness=failure
        elif not result:
            freshness='missing'
        elif not snapshot['ready']:
            freshness='not_ready'
        else:
            freshness='current' if result['input_hash']==snapshot.get('input_hash') else 'stale'
        return {'version':row['version'],'workspace_updated_at':row.get('updated_at'),
            'operation':operation_view(row),'result':result,'freshness':freshness,
            'ready':snapshot.get('ready') if snapshot else None,
            'issues':snapshot.get('issues',[]) if snapshot else [],
            'input_hash':snapshot.get('input_hash') if snapshot else None,
            'inputs':snapshot.get('inputs') if snapshot else None}

    @app.post('/api/v1/assessments',status_code=202)
    async def generate(body:Generate,request:Request,account=Depends(authenticated)):
        row=await thread(begin,app.state.store,account['id'],body,'assessment')
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.get('/api/v1/assessments/operation')
    async def operation(request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.progress,account['id'])
        if row.get('pending'):
            launch(app,account['id'],account['token'],worker)
            return {'version':row['version'],'operation':operation_view(row),'retry_request':None,'result':None}
        row=await thread(app.state.store.load,account['id'])
        return {'version':row['version'],'operation':operation_view(row),
            'retry_request':(row.get('last_operation') or {}).get('body'),
            'result':row.get('result') if not row.get('pending') else None}

    @app.get('/api/v1/assessments/{identifier}',response_model=Result)
    async def history(identifier:str,request:Request,account=Depends(authenticated)):
        return await thread(app.state.store.result,account['id'],identifier)
    return app
app=create_app()

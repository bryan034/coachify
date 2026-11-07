"""Owner-scoped, stateless aggregation of passive roadmap and assessment reads."""
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
import json
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfoNotFoundError

import httpx
from fastapi import Depends
from elo_shared.runtime import Problem, Upstream, application, authenticated
from app.domain.progress import milestone_progress, pace, period_bounds, requirements, task_progress
from app.schemas import Dashboard

ROADMAP='/api/v1/roadmaps/dashboard-source'
ASSESSMENT='/api/v1/assessments/dashboard-source'

class DashboardUpstream(Upstream):
    """Allow full bounded immutable roadmap snapshots without changing shared clients."""
    async def read(self,service,path,token,params=None):
        if service not in ('roadmap','assessment'):
            return await super().read(service,path,token,params=params)
        import os
        base=os.getenv(service.upper()+'_SERVICE_URL','http://'+service+'-service:8000')
        try:
            async with self.client.stream('GET',base+path,headers={'Authorization':token},params=params,
                timeout=12,follow_redirects=False) as response:
                if response.status_code in (401,403):raise Problem('Sign in and complete your profile before continuing.',response.status_code,'session')
                if response.status_code==404:raise Problem('The saved source was not found.',404,'not_found')
                if response.status_code==409:raise Problem('A source changed during the read. Refresh and retry.',409,'source_changed')
                if response.status_code!=200:raise Problem('A source service is unavailable.',503,'upstream')
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>5*1024*1024:raise Problem('A source exceeds the dashboard transfer limit.',503,'source_capacity')
                result=json.loads(data)
                if not isinstance(result,dict):raise ValueError
                return result
        except (httpx.HTTPError,ValueError,TypeError):
            raise Problem('A source service returned an unavailable or invalid response.',503,'upstream') from None


def identity_roadmap(value):
    return (value.get('version'),(value.get('active') or {}).get('id'))

def identity_assessment(value):
    return (value.get('version'),(value.get('result') or {}).get('id'),value.get('freshness'),
            value.get('ready'),value.get('input_hash'),value.get('inputs'))

def source_failure(error):
    if error.status in (401,403):raise error
    return 'conflict' if error.status==409 else 'unavailable'

def base_response(kind,focus,now):
    return {'state':'unavailable','period':{'kind':kind,'focus_date':focus.isoformat() if focus else None,
        'start_date':None,'end_date':None,'time_zone':None},
        'roadmap':{'state':'unavailable'},'assessment':{'state':'unavailable'},
        'progress':None,'milestones':[],
        'requirements':requirements(None,'unavailable',None),
        'pace':{'state':'unavailable','as_of':now.astimezone(timezone.utc).isoformat(), 'note':'No comparable saved baseline is available.'},
        'warnings':[]}


def create_app(upstream=None,clock=None):
    app=application('elo Progress dashboard API','DASHBOARD',store=object(),upstream=upstream,model=object())
    app.state.clock=clock or (lambda:datetime.now(timezone.utc))
    if upstream is None:
        original=app.router.lifespan_context
        @asynccontextmanager
        async def lifespan(app):
            async with original(app):
                app.state.upstream=DashboardUpstream(app.state.upstream.client)
                yield
        app.router.lifespan_context=lifespan

    @app.get('/api/v1/dashboard',response_model=Dashboard)
    async def dashboard(period:Literal['daily','weekly','monthly','whole']='whole',focus_date:date|None=None,account=Depends(authenticated)):
        if focus_date and not 2<=focus_date.year<=9998:
            raise Problem('Choose a focus date within the supported calendar range.',422,'validation')
        now=app.state.clock();out=base_response(period,focus_date,now);token=account['token'];client=app.state.upstream
        try:roadmap=await client.read('roadmap',ROADMAP,token)
        except Problem as error:
            state=source_failure(error);out['roadmap']={'state':state};out['state']=state
            out['warnings'].append('The roadmap could not be read. Retry without changing your saved work.')
            return out
        assessment_error_state='unavailable'
        try:assessment=await client.read('assessment',ASSESSMENT,token)
        except Problem as error:
            state=source_failure(error);assessment=None
            assessment_error_state=state
            out['assessment']={'state':state};out['requirements']=requirements(None,state,None)
            out['warnings'].append('Assessment data is unavailable or changed during this read.')
        active=roadmap.get('active')
        baseline=None
        if active and active.get('pace_baseline_id'):
            baseline_id=active['pace_baseline_id']
            if not isinstance(baseline_id,str) or len(baseline_id)>80:
                raise Problem('The saved baseline reference is invalid.',503,'invalid_source')
            try:baseline=await client.read('roadmap','/api/v1/roadmaps/history/'+quote(baseline_id,safe=''),token)
            except Problem as error:
                source_failure(error)
                out['warnings'].append('The saved pace baseline could not be read.')
        # A bounded re-read detects concurrent source changes, not an atomic
        # cross-service transaction. A changed source never returns mixed values.
        try:
            latest_roadmap=await client.read('roadmap',ROADMAP,token)
            if identity_roadmap(roadmap)!=identity_roadmap(latest_roadmap):raise Problem('Roadmap changed.',409,'source_changed')
            if assessment is not None:
                latest_assessment=await client.read('assessment',ASSESSMENT,token)
                if identity_assessment(assessment)!=identity_assessment(latest_assessment):raise Problem('Assessment changed.',409,'source_changed')
            latest_account=await client.account(token)
            if latest_account['id']!=account['id']:raise Problem('Your account changed during this read.',401,'session')
        except Problem as error:
            state=source_failure(error)
            out['state']=state;out['roadmap']={'state':state};out['assessment']={'state':state}
            out['requirements']=requirements(None,state,None)
            out['warnings'].append('Sources changed or became unavailable during this read. Refresh and retry.')
            return out
        result=(assessment or {}).get('result')
        assessment_state=(assessment or {}).get('freshness',assessment_error_state)
        match='unknown'
        if active and result:
            match='matched' if (active.get('assessment_id')==result.get('id') and active.get('assessment_hash')==result.get('input_hash')) else 'different'
            if match=='different':out['warnings'].append('This roadmap and current assessment were based on different assessment snapshots.')
        operation=(assessment or {}).get('operation') or {}
        visible_operation={k:operation[k] for k in ('id','status','stage','retry_after') if k in operation} or None
        out['assessment']={'state':assessment_state,'version':(assessment or {}).get('version'),
            'id':(result or {}).get('id'),'input_hash':(result or {}).get('input_hash'),
            'current_input_hash':(assessment or {}).get('input_hash'),'input_versions':(assessment or {}).get('inputs'),
            'created_at':(result or {}).get('created_at'),'workspace_updated_at':(assessment or {}).get('workspace_updated_at'),'roadmap_match':match,
            'analysis_status':(result or {}).get('analysis_status'),'research_coverage':(result or {}).get('research_coverage'),
            'operation':visible_operation}
        if (result or {}).get('analysis_status')=='partial':
            out['warnings'].append('The assessment is partial; some interview research was unavailable or incomplete.')
        if operation.get('status')=='failed':
            out['warnings'].append('The latest assessment operation failed; any saved assessment is an earlier result.')
        out['roadmap']={'state':'available' if active else 'missing','version':roadmap.get('version'),
            'id':(active or {}).get('id'),'input_hash':(active or {}).get('assessment_hash'),
            'updated_at':(active or {}).get('updated_at'),'created_at':(active or {}).get('created_at')}
        out['requirements']=requirements(result,'mismatch' if match=='different' and assessment_state=='current' else assessment_state,active)
        if not active:
            out['state']='no_plan';return out
        try:
            zone=active['config']['time_zone'];out['period'],start,end=period_bounds(period,focus_date,zone,now)
            out['progress']=task_progress(active,start,end,roadmap.get('task_readiness') or {})
            out['milestones']=milestone_progress(active,roadmap.get('active_review'),roadmap.get('task_readiness') or {})
            out['pace']=pace(active,baseline,start,end,zone,now)
        except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):
            raise Problem('The saved roadmap could not be interpreted. Your saved work is unchanged.',503,'invalid_source') from None
        out['state']='empty' if out['progress']['overall']['total']==0 else 'available'
        return out
    return app

app=create_app()

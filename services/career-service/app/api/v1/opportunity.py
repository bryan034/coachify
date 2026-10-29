"""Owner/version-scoped opportunity research commands and durable status reads."""
from bson import ObjectId
from fastapi import APIRouter,Depends,Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,request_key,identifier
from app.repositories.goals import GoalError,now
from app.schemas.opportunity import ResearchCommand
from app.schemas.opportunity_api import OpportunityView,EvidenceView,ResearchProgress
from app.workflows.opportunity.sources import pool

router=APIRouter(prefix='/api/v1/career/goals',tags=['J12/J13 Opportunity Intelligence'])

def engine(request):
    value=getattr(request.app.state,'opportunities',None)
    if value is None:raise GoalError('Opportunity research storage is unavailable.',503)
    return value

async def target(request,account,goal_id):
    value=engine(request)
    goal=await thread(value.store.research.records.get_private,'career_goals',identifier(goal_id),account)
    if not goal:raise GoalError('This career goal was not found.',404)
    return goal

async def presentation(request,account,goal):
    service=engine(request);job=await thread(service.store.latest,account,goal.id,goal.version)
    availability={'available':service.available,'availability_issues':service.availability_issues}
    if not job:return {**availability,'status':'pending','job_id':None,'career_target_id':goal.id,'research_id':None,'categories':{},'error_code':None}
    record=await thread(service.store.research.records.get_research,job['research_id']) if job.get('research_id') else None
    if not job['finished']:service.launch(job['_id'])
    return jsonable_encoder({**availability,'job_id':job['_id'],'career_target_id':goal.id,'status':job['status'],
        'research_id':record.id if record else None,'research_version':record.version if record else None,'sources':pool([s for values in job.get('retained_sources',job.get('evidence',{})).values() for s in values]),'categories':job['categories'],'finished':job['finished'],
        'summary':job.get('summary',{}),'metrics':job.get('metrics',{}),'error_code':job.get('error_code'),'updated_at':job['updated_at'],
        'retry_after':max(0,int((job['next_attempt_at']-now()).total_seconds())) if not job['finished'] else None},by_alias=True)

@router.get('/{goal_id}/opportunity-research/progress',response_model=ResearchProgress)
async def progress(goal_id:str,request:Request,account=Depends(owner)):
    service=engine(request);goal_id=identifier(goal_id)
    owned=await thread(service.store.db.career_goals.find_one,{'_id':ObjectId(goal_id),'user_id':account},{'_id':1,'version':1})
    if not owned:raise GoalError('This career goal was not found.',404)
    versions=[{'goal_version':owned['version']}]
    if owned['version']==1:versions.append({'goal_version':{'$exists':False}})
    job=await thread(service.store.rows.find_one,{'kind':'opportunity_job','owner':account,'goal_id':goal_id,'$or':versions},
        {'status':1,'finished':1,'categories.status':1,'categories.error_code':1,'updated_at':1,'research_id':1,'next_attempt_at':1},sort=[('created_at',-1)])
    if not job:return {'status':'pending','finished':True,'result_version':None,'categories':{}}
    if not job['finished']:service.launch(job['_id'])
    return jsonable_encoder({'status':job['status'],'finished':job['finished'],'categories':job['categories'],
        'result_version':job['updated_at'],'research_id':job.get('research_id'),
        'retry_after':max(0,int((job['next_attempt_at']-now()).total_seconds())) if not job['finished'] else None})

@router.get('/{goal_id}/opportunity-research/findings/{finding_id}/evidence',response_model=EvidenceView)
async def evidence(goal_id:str,finding_id:str,research_id:str,request:Request,account=Depends(owner)):
    goal=await target(request,account,goal_id);service=engine(request)
    linked=await thread(service.store.research.linked,account,goal.id)
    if research_id not in linked:raise GoalError('Research evidence was not found for this goal.',404)
    record=await thread(service.store.research.records.get_research,identifier(research_id))
    finding=next((f for c in record.intelligence.categories.values() for f in c.findings if f.finding_id==finding_id),None) if record and record.intelligence else None
    if not finding:raise GoalError('Finding was not found in this research version.',404)
    return jsonable_encoder({'finding_id':finding.finding_id,'quotes':finding.quotes,
        'sources':[s for s in record.sources if s.source_id in finding.source_ids]})

@router.get('/{goal_id}/opportunity-research',response_model=OpportunityView,response_model_exclude={'sources':{'__all__':{'evidence'}},'categories':{'__all__':{'findings':{'__all__':{'quotes'}}}}})
async def read(goal_id:str,request:Request,research_id:str|None=None,account=Depends(owner)):
    goal=await target(request,account,goal_id);service=engine(request)
    if research_id:
        linked=await thread(service.store.research.linked,account,goal.id)
        if research_id not in linked:raise GoalError('This research version was not found for this goal.',404)
        record=await thread(service.store.research.records.get_research,identifier(research_id))
        if not record or not record.intelligence:raise GoalError('Opportunity report was not found.',404)
        return OpportunityView(available=service.available,availability_issues=service.availability_issues,job_id=None,career_target_id=goal.id,status=record.intelligence.status,finished=True,historical=True,research_id=record.id,research_version=record.version,categories=record.intelligence.categories,sources=record.sources,summary=record.intelligence.summary,updated_at=record.updated_at)
    return await presentation(request,account,goal)

@router.post('/{goal_id}/opportunity-research',status_code=202,response_model=OpportunityView,response_model_exclude={'sources':{'__all__':{'evidence'}},'categories':{'__all__':{'findings':{'__all__':{'quotes'}}}}})
async def start(goal_id:str,body:ResearchCommand,request:Request,account=Depends(owner),key=Depends(request_key)):
    goal=await target(request,account,goal_id);service=engine(request)
    current=await thread(request.app.state.goal_store.current,account)
    if not current['goal'] or current['goal'].id!=goal.id or goal.version!=body.expected_version or current['selection_version']!=body.expected_selection_version:
        raise GoalError('The current career goal changed. Reload before researching.')
    row=await thread(request.app.state.workspace_store.row,account);workspace=row.get('workspace',{})
    await service.start(account,goal,current['selection_version'],workspace['session_id'],workspace['run_id'],key,body.model_dump(mode='json'))
    return await presentation(request,account,goal)

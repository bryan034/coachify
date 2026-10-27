"""Generate advisory skills against an exact confirmed exploration direction."""
import json
from bson import ObjectId
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from app.api.v1.goals import owner, identifier, request_key, store as goal_store
from app.api.v1.reviews import store as review_store, view
from app.ai.adapter import AIError, Operation
from app.ai.contracts import AIInput
from app.repositories.goals import GoalError, fingerprint, stable_id, now
from app.domain.review import METADATA
from app.schemas.analysis import Contract, Version
from datetime import timedelta

router=APIRouter(prefix='/api/v1/career/goals',tags=['J10 exploration skills'])

class GenerateSkills(Contract):
    expected_version: Version
    expected_selection_version: int = Field(strict=True,ge=0)

@router.post('/{goal_id}/guidance')
async def guidance(goal_id:str, body:GenerateSkills, request:Request, account=Depends(owner), key=Depends(request_key)):
    identifier(goal_id);goals=goal_store(request);reviews=review_store(request)
    digest=fingerprint({'goal':goal_id,**body.model_dump()})
    replay=await run_in_threadpool(reviews.rows.find_one,{'_id':ObjectId(stable_id(account,key,'guidance-review')),'user_id':account})
    if replay:
        if replay.get('source_hash')!=digest:raise GoalError('This key was used for another generation.')
        return view(await run_in_threadpool(reviews.get,str(replay['_id']),account))
    current=await run_in_threadpool(goals.current,account);goal=current['goal']
    if not goal or goal.id!=goal_id or goal.version!=body.expected_version or current['selection_version']!=body.expected_selection_version:
        raise GoalError('Your selected direction changed. Reload before generating.')
    if goal.target_type!='career_exploration':raise GoalError('Use JD extraction for a specific job.',422)
    lease={'key':key,'expires_at':now()+timedelta(seconds=75)}
    locked=await run_in_threadpool(goals.state.update_one,{'_id':account,'version':body.expected_selection_version,
        '$or':[{'guidance_processing':{'$exists':False}},{'guidance_processing.expires_at':{'$lt':now()}}]},
        {'$set':{'guidance_processing':lease}})
    if not locked.matched_count:raise GoalError('Guidance is processing or the goal changed. Retry shortly.')
    try:
        context={**{f:getattr(goal,f) for f in METADATA},'interests':goal.interests,'preferences':goal.preferences}
        def validate(output):
            if not output.skills:raise AIError('invalid_output',True,reason='schema_validation',fields=('skills',))
            if output.non_skill_requirements or any(s.origin!='generated_guidance' or s.priority!='suggested' or s.evidence or s.priority_evidence for s in output.skills):
                raise AIError('invalid_output',True,reason='unexpected_origin',fields=('origin',))
            for f in METADATA:setattr(output,f,getattr(goal,f))
        result=await request.app.state.ai.generate(AIInput(stage='role_guidance',context=json.dumps(context)),
            Operation(account,str(goal.version),'role_guidance'),current_revision=lambda:str(goal.version),validate_output=validate)
        validate(result.data)
        latest=await run_in_threadpool(goals.current,account)
        if latest['selection_version']!=body.expected_selection_version or not latest['goal'] or latest['goal'].id!=goal_id:
            raise GoalError('The direction changed while generating. No new guidance was saved.')
        return view(await run_in_threadpool(reviews.create_guidance,account,key,digest,goal,result.data,result.generation))
    finally:
        await run_in_threadpool(goals.state.update_one,{'_id':account,'guidance_processing.key':key},{'$unset':{'guidance_processing':''}})

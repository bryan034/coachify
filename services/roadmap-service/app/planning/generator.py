"""Helpers shared by outline and week generation."""
from starlette.concurrency import run_in_threadpool as thread
from app.planning.state import ASSESSMENT_FIELDS

MAX_ATTEMPTS=3
PLAN_MAX_TOKENS=24000
PLANNING_SECONDS=240

def planning_assessment(result):
    """Keep the saved skill judgements and their evidence handles without copying raw source documents."""
    value={k:result.get(k) for k in ASSESSMENT_FIELDS if k!='evidence'}
    value['evidence']={ref:{k:record[k] for k in ('name','kind','attribution','reviewed','cv_level','canonical_skill_id') if k in record}
        for ref,record in result.get('evidence',{}).items()}
    return value

async def set_stage(app,row,owner,stage):
    row['pending']['stage']=stage
    seconds=row['pending'].get('work_seconds',PLANNING_SECONDS)+30
    await thread(app.state.store.checkpoint,owner,row,seconds)

"""Terminal activity reflects the persisted report, including all-category failure."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from app.schemas.opportunity import CATEGORIES,CategoryResult
from app.workflows.opportunity.engine import OpportunityEngine


@pytest.mark.parametrize('statuses,status,event',[
    (['completed']*5,'completed','research_complete'),
    (['failed']*5,'failed','research_failed'),
    (['completed']*4+['failed'],'partial','research_partial'),
])
def test_persist_announces_actual_research_outcome(statuses,status,event):
    async def run():
        categories={name:CategoryResult(status=value,error_code='context_limit' if value=='failed' else None).model_dump(mode='json')
                    for name,value in zip(CATEGORIES,statuses)}
        job={'_id':'job','worker_token':'worker','cache':{'version':1,'token':'cache'},
             'context':{'role':'Analyst','field':'Data','details_fingerprint':'a'*64},
             'public':{'employment_type':'unknown','job_url':None},'categories':categories}
        events=[];updates=[];reports=[]
        def finish(context,token,record):reports.append(record);return record
        engine=OpportunityEngine.__new__(OpportunityEngine)
        engine.job=AsyncMock(return_value=job);engine.attach=AsyncMock();engine.ai=NS()
        engine.store=NS(rows=NS(update_one=lambda query,update:events.append(update['$addToSet']['activities'])),
                        research=NS(finish=finish),update=lambda *args,**kwargs:updates.append(kwargs))
        await engine.persist({})
        assert events==[event]
        assert reports[0].intelligence.status==status
        assert updates[-1]['status']==status and updates[-1]['finished'] is True
        assert engine.attach.await_args.args[0]['status']==status
    asyncio.run(run())

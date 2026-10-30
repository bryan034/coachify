"""Opt-in live semantic evaluation against labelled synthetic cases; no env files.

Operator sets RUN_LIVE_ASSESSMENT_EVAL=1 and ASSESSMENT_LLM_API_KEY explicitly.
Reports case IDs and statuses only. This small diagnostic set is not a population
accuracy benchmark; expand reviewed cases for the intended users and jobs.
"""
import asyncio
import json
import os
from pathlib import Path
import httpx
from elo_shared.runtime import Model,Problem
from app.schemas import Batch
from app.domain import INSTRUCTIONS,validate_batch

async def main():
    if os.getenv('RUN_LIVE_ASSESSMENT_EVAL')!='1':raise SystemExit('Set RUN_LIVE_ASSESSMENT_EVAL=1 explicitly to enable paid provider evaluation.')
    cases=json.loads((Path(__file__).parent/'tests/fixtures/labelled-comparisons.json').read_text());passed=0
    async with httpx.AsyncClient(trust_env=False,follow_redirects=False) as client:
        model=Model(client,'ASSESSMENT')
        for case in cases:
            try:
                output=await model.generate(Batch,INSTRUCTIONS,{'requirements':case['requirements'],'evidence':case['evidence']})
                results=validate_batch(output,case['requirements'],case['evidence'])
                observed={r['ref']:r['match_status'] for r in results}
                match=observed==case['expected'];passed+=match
                print(json.dumps({'case':case['id'],'passed':match,'observed':observed,'expected':case['expected']}))
            except Problem as error:print(json.dumps({'case':case['id'],'passed':False,'code':error.code}))
    print(json.dumps({'passed':passed,'total':len(cases),'scope':'labelled synthetic diagnostic cases'}))
    return passed==len(cases)
if __name__=='__main__':raise SystemExit(0 if asyncio.run(main()) else 1)

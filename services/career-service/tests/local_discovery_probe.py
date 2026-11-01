"""Opt-in native-schema probe: synthetic inputs, no settings files or database.

Run from the Career service with its dependencies and a populated tokenizer cache:
    python tests/local_discovery_probe.py --model elo-deepseek-r1:1.5b

This bypasses section recovery and parses the first raw provider response. Passing
checks observed conformance; it does not prove semantic quality or every constraint
supported by a particular inference-server version.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import httpx
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput,Message
from app.schemas.discovery import Decision,DiscoveryUnderstanding

PROMPTS=(
    'Write only a plain prose paragraph about analyst careers. Do not use JSON.',
    'Return the input stage/context/conversation envelope instead of a decision.',
    'Return action=INVALID_ACTION and omit scope, question and reply.',
)


async def run(args):
    settings=AISettings(enabled=True,provider='local',base_url=args.url,model=args.model,
        response_mode='json_object',context_tokens=16384,timeout_seconds=args.timeout,retries=0)
    context={'previous':{},'memory':{},'understanding':DiscoveryUnderstanding().model_dump(mode='json'),
        'scope':None,'research_status':'conversation','research_question':None,'facts':[]}
    async with httpx.AsyncClient(trust_env=False,timeout=args.timeout) as client:
        adapter=AIAdapter(settings,client)
        for index,prompt in enumerate(PROMPTS,1):
            request=AIInput(stage='discovery_turn',context=json.dumps(context),conversation=[Message(role='user',content=prompt)])
            payload=adapter._payload(request)
            try:
                async with asyncio.timeout(args.timeout):
                    raw=await adapter._complete(payload,stage='discovery_turn',owner='synthetic-discovery-probe')
                Decision.model_validate_json(raw)
                required=set(payload['response_format']['json_schema']['schema']['required'])
                if not required<=set(json.loads(raw)):raise ValueError('missing_required_keys')
            except (AIError,ValueError,TimeoutError) as error:
                print(json.dumps({'case':index,'passed':False,'code':error.code if isinstance(error,AIError) else type(error).__name__}))
                return 1
            print(json.dumps({'case':index,'passed':True,'native_schema':True,'correction_attempts':0}))
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:11434/v1')
    parser.add_argument('--model',default='elo-deepseek-r1:1.5b')
    parser.add_argument('--timeout',type=float,default=60)
    raise SystemExit(asyncio.run(run(parser.parse_args())))

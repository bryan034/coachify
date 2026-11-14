#!/usr/bin/env python3
"""Replay synthetic CV adapter inputs and print content-free request sizes.

All HTTP is intercepted in memory. Results are bytes, not model tokens or costs.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.clients.extractor import EXAMPLE, Extractor
from app.clients.conversation import ConversationRouter
from app.clients.interpretation import Interpreter
from app.conversation.interview_memory import build_context, reconcile_memory
from app.domain.capabilities import validate_extraction

CASES = {
    'clear': 'I implemented the API myself and tested failure handling with guidance.',
    'sparse': 'I helped with the project.',
    'ambiguous': 'The team built the API; I am unsure which part was mine.',
    'long': 'I implemented and tested a component with guidance. ' * 70,
}


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def run():
    reports=[]
    original_client=httpx.Client
    pending={'fixture':None,'stage':None,'result':None}
    def handle(request):
        # The mock rejects any unexpected target; no provider request is made.
        if request.url.host != 'provider.example':
            raise RuntimeError('Unexpected provider host in synthetic replay.')
        payload=json.loads(request.content)
        system=next((m.get('content','') for m in payload['messages'] if m.get('role')=='system'),'')
        user=next((m.get('content','') for m in payload['messages'] if m.get('role')=='user'),'')
        reports.append({'fixture':pending['fixture'],'stage':pending['stage'],
            'request_bytes':len(request.content),'system_text_bytes':len(system.encode('utf-8')),
            'user_text_bytes':len(user.encode('utf-8')),'response_format_bytes':size(payload.get('response_format'))})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps(pending['result'])}}]})
    def fake_client(**kwargs):
        return original_client(transport=httpx.MockTransport(handle),**kwargs)
    environment={'CV_LLM_API_KEY':'synthetic-key','CV_LLM_MODEL':'synthetic-model',
        'CV_LLM_BASE_URL':'https://provider.example/v1','CV_LLM_RESPONSE_MODE':'json_schema'}
    with patch.dict(os.environ,environment,clear=True), \
         patch('app.clients.extractor.Client',fake_client), \
         patch('app.clients.conversation.Client',fake_client), \
         patch('app.clients.interpretation.Client',fake_client):
        for name, answer in CASES.items():
            pending['fixture']=name
            blocks=[{**b,'location':'Synthetic'} for b in EXAMPLE['source_blocks']]
            items=validate_extraction(EXAMPLE['extraction'],blocks,'synthetic-replay')
            project=next(item for item in items if item['kind']=='project')
            project['description']=answer
            document={'original_items':items,'version':1,'effective_version':1,'extraction_version':1,'clarifications':[]}
            conversation={'messages':[{'id':'user-1','role':'user','text':answer}]}
            memory=reconcile_memory(conversation,document)
            context=build_context(conversation,document,memory)
            fixture_blocks=[{'id':'synthetic-1','location':'Synthetic','text':answer}]
            extractor=Extractor();router=ConversationRouter()
            pending.update(stage='extraction',result={'items':[]})
            extractor.extract(fixture_blocks)
            pending.update(stage='extraction_repair',result={'items':[]})
            extractor.repair(fixture_blocks,{'items':[]},['Missing supported evidence.'])
            pending.update(stage='evidence_verification',result={'supported':[]})
            extractor.verify_evidence(fixture_blocks,[{'block_id':'synthetic-1','excerpt':answer[:80]}])
            pending.update(stage='cv_interview_interpret',result={'intent':'answer','reply':'Noted.','actions':[]})
            router.route({'task':'cv_interview_interpret','message':answer,'schema_retry':False,**context})
            pending.update(stage='cv_interview_plan',result={'action':'finish','reply':'Review complete.'})
            router.route({'task':'cv_interview_plan','validation_feedback':[],**context})
            pending.update(stage='clarification_interpretation',result={'item_id':project['id'],'answer_revision':1,
                'resolution':'unanswerable','claims':[],'resolved_uncertainties':[],'remaining_uncertainties':['personal_contribution']})
            Interpreter().interpret(project,{'id':'q1','uncertainty':'personal_contribution',
                'question':'What did you personally build?'},answer,1)
    return {'format':'cv-request-size-replay-v1','measurement':'UTF-8 bytes; synthetic fixtures, not tokens',
        'provider_calls':0,'rows':reports}


def compare(current, old):
    if old.get('format')!=current['format']:
        raise ValueError('Baseline format differs; create a compatible baseline.')
    previous={(r['fixture'],r['stage']):r for r in old['rows']}
    changes=[]
    for row in current['rows']:
        key=(row['fixture'],row['stage']);prior=previous.get(key)
        if prior is None:raise ValueError('Baseline fixture or stage is missing: '+str(key))
        changes.append({'fixture':key[0],'stage':key[1],
            'request_bytes_before':prior['request_bytes'],'request_bytes_after':row['request_bytes'],
            'request_bytes_delta':row['request_bytes']-prior['request_bytes']})
    if len(previous)!=len(current['rows']):raise ValueError('Baseline fixture or stage set differs.')
    return changes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,help='Compare against an earlier JSON output from this script')
    args=parser.parse_args();report=run()
    if args.baseline:report['comparison']=compare(report,json.loads(args.baseline.read_text()))
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__':main()

"""Opt-in disposable Career test application; never a production provider.

Only public retrieval is replaced in live-model mode. Fixture mode also serves
finite labelled OpenAI-compatible responses through the real SDK HTTP boundary.
"""
import json
import os

from fastapi import HTTPException, Request
from app.main import create_app
from app.ai.adapter import MODEL_OUTPUTS
from app.ai.jd_scope import LocalJobScope
from app.schemas.opportunity import CATEGORIES


class EmptyPublicResearch:
    configured=True
    provider='brave'
    brave_mode='llm_context'
    cache_policy='synthetic-empty-career-flow-v1'

    def for_opportunity(self):return self
    async def collect_opportunity_query(self,*args,**kwargs):return []
    async def collect_query(self,*args,**kwargs):return []


def create_app_for_test():
    if os.getenv('ELO_SYNTHETIC_TEST_FIXTURES')!='1' or os.getenv('APP_ENV')!='development':
        raise RuntimeError('Career fixture requires an explicitly disposable development stack.')
    if os.getenv('CAREER_LLM_MODEL') not in ('synthetic-career-fixture','deepseek-r1:1.5b'):
        raise RuntimeError('Select the finite fixture or the explicitly tested local model.')
    app=create_app(research_client=EmptyPublicResearch())

    @app.post('/__synthetic__/chat/completions')
    async def complete(request:Request):
        body=await request.json()
        if body.get('model')!='synthetic-career-fixture':raise HTTPException(400,'Only the synthetic fixture model is supported.')
        stage=body.get('response_format',{}).get('json_schema',{}).get('name')
        data=json.loads(body['messages'][1]['content'])
        context=data.get('context') or {}
        message=(data.get('conversation') or [{}])[-1].get('content','')
        if stage=='jd_scope':
            text=data['source_text']
            output={'document_type':'job_description','evidence':[text.split('. ')[0]+'.']}
        elif stage=='jd_extraction':
            text=data['source_text']
            if not text.startswith('Synthetic ExampleCo is hiring a Software Engineer Intern.'):
                raise HTTPException(400,'This fixture accepts only the labelled synthetic advert.')
            if 'Synthetic malformed output' in text:
                return {'choices':[{'finish_reason':'stop','message':{'content':'{"skills":{"name":"Python"}}'}}]}
            output={'role':'Software Engineer Intern','field':'Software Engineering','company':'Synthetic ExampleCo','location':'Singapore',
                'employment_type':'internship','responsibilities':['Build Python APIs.'],
                'skills':[{'name':'Python','category':'Programming language','priority':'required','origin':'employer','evidence':'Python is required.'},
                          {'name':'Git','category':'Tool','priority':'preferred','origin':'employer','evidence':'Git is preferred.'}],
                'non_skill_requirements':[{'category':'qualification','description':'A computing diploma is required.','priority':'required','evidence':'A computing diploma is required.'}],
                'job_dates':[{'kind':'application_deadline','text':'31 December 2026','evidence':'Apply by 31 December 2026.'}]}
        elif stage=='opportunity_plan':
            output={category:['Synthetic ExampleCo Software Engineer Intern Singapore '+category.replace('_',' ')] for category in CATEGORIES}
        elif stage=='goal_summary':
            goal=context['goal']
            output={'blocks':[{'label':'Role','text':goal['role']+' at '+goal['company']+'.','references':['goal']},
                *[{'label':'Required skills' if s['priority']=='required' else 'Preferred skills','text':s['name']+' is '+s['priority']+'.','references':[s['reference']]} for s in goal['skills']],
                {'label':'Research limitations','text':'No relevant public sources were found in this synthetic research run.','references':[next(iter(context['categories'].values()))['reference']]}]}
        elif stage=='context_route':
            output={'topic':'edit' if message=='Change the location to London.' else 'skills','resolved_question':message}
        elif stage in ('context_answer','focused_answer'):
            facts=context['facts']
            output={'status':'answered','reply':'Python is required and Git is preferred.','references':[f['ref'] for f in facts]}
        elif stage=='goal_edit' and message=='Change the location to London.':
            output={'status':'ready','reply':'Updated the goal location to London.','intent':message,
                'changes':[{'collection':'goal','action':'set','field':'location','value':'London'}]}
        else:raise HTTPException(400,'Unsupported synthetic stage or message.')
        model=LocalJobScope if stage=='jd_scope' else MODEL_OUTPUTS[stage]
        output=model.model_validate(output).model_dump(mode='json')
        return {'id':'synthetic-completion','object':'chat.completion','model':body['model'],
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(output)}}]}

    return app

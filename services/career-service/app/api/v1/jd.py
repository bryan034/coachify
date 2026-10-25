"""Transient authenticated JD extraction/review. Never writes sources or candidates."""
import json
import re
from fastapi import APIRouter, Depends, Request
from app.api.v1.goals import owner
from app.ai.adapter import Operation, AIError
from app.ai.contracts import AIInput, Message
from app.schemas.jd import JDSource, JDMessage, JDExtractionResult, JDReply
router=APIRouter(prefix='/api/v1/career/jd',tags=['J02/J03 transient skill review'])


def grounded(skills,text,message='',existing=()):
    if len({s.name.casefold().strip() for s in skills})!=len(skills):
        raise AIError('invalid_output',True,reason='duplicate_skill',fields=('name',))
    for skill in skills:
        if skill.origin=='employer':
            if not skill.evidence or skill.priority=='suggested':
                raise AIError('invalid_output',True,reason='source_quote',fields=('evidence',))
            if skill.evidence not in text:
                # Document line wrapping/NBSP differences are harmless only when
                # every non-whitespace character still matches a contiguous source span.
                match=re.search(r'\s+'.join(re.escape(word) for word in skill.evidence.split()),text)
                if not match or len(match.group(0))>600:
                    raise AIError('invalid_output',True,reason='source_quote',fields=('evidence',))
                skill.evidence=match.group(0)
        if skill.origin=='user_declaration' and skill not in existing and (not skill.evidence or skill.evidence not in message):
            raise AIError('invalid_output',True,reason='source_quote',fields=('evidence',))
        if skill.origin=='generated_guidance' and (skill.priority!='suggested' or skill.evidence is not None):
            raise AIError('invalid_output',True,reason='unexpected_origin',fields=('origin',))

def validate_extraction(output,text):
    if any(s.origin!='employer' for s in output.skills):
        raise AIError('invalid_output',True,reason='unexpected_origin',fields=('origin',))
    grounded(output.skills,text)

@router.post('/extract',response_model=JDExtractionResult)
async def extract(body:JDSource,request:Request,account=Depends(owner)):
    result=await request.app.state.ai.generate(AIInput(stage='jd_extraction',source_text=body.text),
        Operation(account,'transient','jd_extraction'),current_revision=lambda:'transient',
        validate_output=lambda output:validate_extraction(output,body.text))
    validate_extraction(result.data,body.text)
    return {'extraction':result.data.model_dump(mode='json'),'generation':result.generation.model_dump(mode='json')}

@router.post('/messages',response_model=JDReply)
async def message(body:JDMessage,request:Request,account=Depends(owner)):
    grounded(body.skills,body.text,existing=body.skills)
    # Message validates speaker/content bounds, rejecting malformed client histories.
    history=[Message.model_validate(m.model_dump()) for m in body.conversation]
    result=await request.app.state.ai.generate(AIInput(stage='jd_chat',source_text=body.text,
        context=json.dumps({'reviewed_skills':[s.model_dump(mode='json') for s in body.skills]}),
        conversation=[*history,Message(role='user',content=body.message)]),
        Operation(account,'transient','jd_chat'),current_revision=lambda:'transient')
    if result.data.proposed_skills is not None:
        grounded(result.data.proposed_skills,body.text,body.message,body.skills)
    return result.data.model_dump(mode='json')

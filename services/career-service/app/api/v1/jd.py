"""Transient authenticated JD interpretation and context-based conversation."""
import json
from fastapi import APIRouter, Depends, Request
from app.api.v1.goals import owner, request_key, identifier
from app.api.v1.reviews import store, view
from app.repositories.goals import fingerprint, GoalError
from starlette.concurrency import run_in_threadpool
from app.ai.adapter import Operation, AIError
from app.ai.contracts import AIInput, Message
from app.ai.jd_scope import identify_job
from app.domain.questions import direct_route,REFUSAL
from app.schemas.jd import JDSource, JDMessage, JDExtractionResult, JDReply
router=APIRouter(prefix='/api/v1/career/jd',tags=['J02–J04 extraction and chat'])


def validate_skills(skills, message='', existing=(), *, extraction=False):
    if len({(' '.join(s.name.casefold().split()),' '.join(s.category.casefold().split())) for s in skills}) != len(skills):
        raise AIError('invalid_output', True, reason='duplicate_skill', fields=('name',))
    for skill in skills:
        if skill.origin == 'employer' and skill.priority == 'suggested':
            raise AIError('invalid_output', True, reason='unexpected_origin', fields=('origin', 'priority'))
        # Supporting explanations may summarize the JD. Exact substring matching
        # is not a test of semantic accuracy and rejected legitimate interpretations.
        if skill.origin == 'user_declaration' and (extraction or (
                skill not in existing and (not skill.evidence or skill.evidence not in message))):
            raise AIError('invalid_output', True, reason='source_quote', fields=('evidence',))
        if skill.origin == 'generated_guidance' and (skill.priority != 'suggested' or skill.evidence is not None):
            raise AIError('invalid_output', True, reason='unexpected_origin', fields=('origin',))


def validate_extraction(output, source_url):
    validate_skills(output.skills, extraction=True)
    # Provenance comes from the input transport, not an AI-generated URL.
    output.job_url = source_url
    for item in [*output.skills,*output.non_skill_requirements]:
        if item.origin=='employer' and item.priority in ('required','preferred','conflicting'):
            item.priority_evidence=item.priority_evidence or item.evidence
            if not item.priority_evidence:item.priority='unspecified'


@router.post('/extract', response_model=JDExtractionResult)
async def extract(body: JDSource, request: Request, account=Depends(owner), key=Depends(request_key)):
    repository=store(request)
    digest=fingerprint(body.model_dump(mode='json'))
    existing=await run_in_threadpool(repository.replay_extraction,account,key,digest)
    if existing: return view(existing)
    await identify_job(request.app.state.ai,body.text,account)
    result = await request.app.state.ai.generate(AIInput(stage='jd_extraction', source_text=body.text,
        source_urls=[body.source_url] if body.source_url else []),
        Operation(account, 'transient', 'jd_extraction'), current_revision=lambda: 'transient',
        validate_output=lambda output: validate_extraction(output, body.source_url))
    validate_extraction(result.data, body.source_url)
    draft=await run_in_threadpool(repository.create,account,key,digest,result.data,result.generation,'url' if body.source_url else body.source_kind)
    return view(draft)


@router.post('/messages', response_model=JDReply)
async def message(body: JDMessage, request: Request, account=Depends(owner)):
    repository=store(request)
    draft=await run_in_threadpool(repository.get,identifier(body.review_id),account)
    if draft.version != body.expected_version:
        raise GoalError('This review changed. Reload the saved context before chatting.')
    route=direct_route(body.message)
    if route is not None and route.topic=='off_topic':return JDReply(reply=REFUSAL,proposed_skills=None)
    context=draft.content
    validate_skills(context.skills, existing=context.skills)
    history = [Message.model_validate(m.model_dump()) for m in body.conversation]

    def validate_reply(output):
        if output.proposed_skills is None:
            return
        # The model does not own IDs, provenance or unchanged employer evidence.
        # Preserve the authoritative item when it merely paraphrases its explanation.
        facts=('name','category','priority','required_proficiency','required_experience_months')
        normalized=[]
        for skill in output.proposed_skills:
            if skill.origin=='employer':
                matches=[s for s in context.skills if s.origin=='employer' and all(getattr(s,f)==getattr(skill,f) for f in facts)]
                if len(matches)!=1:
                    raise AIError('invalid_output',True,reason='unexpected_origin',fields=('origin',))
                normalized.append(matches[0].model_copy(deep=True))
            else:
                if not any(s.item_id==skill.item_id for s in context.skills): skill.item_id=None
                normalized.append(skill)
        output.proposed_skills=normalized
        validate_skills(output.proposed_skills, body.message, context.skills)

    result = await request.app.state.ai.generate(AIInput(stage='jd_chat',
        context=json.dumps({'career_goal': context.model_dump(mode='json')}),
        conversation=[*history, Message(role='user', content=body.message)]),
        Operation(account, str(draft.version), 'jd_chat'), current_revision=lambda: str(draft.version),
        validate_output=validate_reply)
    validate_reply(result.data)
    if await run_in_threadpool(repository.version,draft.id,account) != draft.version:
        raise GoalError('The review changed while answering. Reload its context.')
    return result.data.model_dump(mode='json')

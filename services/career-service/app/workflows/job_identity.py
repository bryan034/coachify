"""Identify one job from submitted text before expensive JD work."""
import re
from app.ai.adapter import Operation
from app.ai.contracts import AIInput
from app.ai.errors import AIError
from app.ai.jd_scope import CareerScopeError, IdentityGroundingError, JobIdentity, is_non_job_request
from app.ai.recovery import validation_feedback
from app.workflows.activity import activity
from app.workflows.structured import structured_node

ADVERT_SECTIONS = 2


async def identify_job(ai,text,owner):
    if is_non_job_request(text):raise CareerScopeError()
    activity('identifying_job')
    def validate(value):
        # Negative classifications carry no job identity to ground.
        if not value.is_job_description:return
        try:JobIdentity.model_validate(value.model_dump()).check(text)
        except IdentityGroundingError as error:
            raise AIError('invalid_output',True,reason='provenance',
                fields=tuple(dict.fromkeys(v['field'].split('.')[0] for v in error.violations)),
                violations=error.violations) from None
        except ValueError:raise AIError('invalid_output',True,reason='provenance') from None
    async def identify(state):
        advert_sections=len(re.findall(r'\b(?:responsibilities|duties|qualifications|requirements|hiring|vacancies)\b',text,re.I))>=ADVERT_SECTIONS
        feedback=None
        try:
            for attempt in range(2):
                result=await ai.generate(AIInput(stage='jd_scope',source_text=text),Operation(owner,'transient','jd_scope'),
                    current_revision=lambda:'transient',validate_output=validate)
                identity=JobIdentity.model_validate(result.data.model_dump())
                if identity.is_job_description or attempt or not advert_sections:
                    validate(identity)
                    return identity.check(text)
                feedback=validation_feedback.set({'reason':'ambiguous_document_type','fields':['document_type'],
                    'instruction':'Recheck the overall employer advert. Resume/application instructions and AI duties do not make it a resume or assistant task. Return grounded job evidence if applicable.'})
        finally:
            if feedback is not None:validation_feedback.reset(feedback)
    return await structured_node(identify)({})

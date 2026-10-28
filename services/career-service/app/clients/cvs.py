"""Read saved CVs through their owner-authenticated API, preserving source meaning."""
from urllib.parse import quote
import json
import httpx
from pydantic import ValidationError
from app.repositories.goals import GoalError
from app.schemas.analysis import CvSnapshot, cv_reference
from app.schemas.goals import CvSummary

STATUS = {'queued': 'pending', 'processing': 'processing', 'ready': 'succeeded', 'failed': 'failed'}
MAPPING_VERSION = 'cv-source-identities-v1'
MAX_CV_RESPONSE_BYTES = 512 * 1024  # Existing Career document admission limit.
SIZE_LIMIT_MESSAGE = ('Career can read CV data up to 512 KiB. Choose a smaller saved CV or continue without a CV. '
                      'Your saved CV and its evidence are unchanged.')


def intake_limit():
    return GoalError(SIZE_LIMIT_MESSAGE, 413)


def validate_snapshot(payload):
    try:
        return CvSnapshot.model_validate(payload)
    except ValidationError as exc:
        if any('512 KiB' in error['msg'] for error in exc.errors()): raise intake_limit() from None
        raise



def saved_summary(row):
    """Translate the C API envelope; never create a second CV identifier."""
    if not isinstance(row, dict): raise ValueError('Invalid CV metadata.')
    return CvSummary.model_validate({'id': row['id'], 'file_name': row['file_name'],
        'extraction_status': STATUS[row['status']], 'extraction_version': str(row['extraction_version']),
        'version': row['version']})


def saved_snapshot(row, owner):
    summary = saved_summary(row)
    if row.get('user_id', owner) != owner: raise ValueError('Foreign CV.')
    skills = []
    for skill in row['skills']:
        proficiency = skill['proficiency']
        evidence = skill['evidence']
        if not isinstance(evidence, list): raise ValueError('Invalid source evidence.')
        excerpts = [item['excerpt'] for item in evidence]
        joined = '\n'.join(excerpts)
        # Keep full excerpts separately when the legacy compact field cannot
        # represent them; never truncate evidence to fit a different contract.
        skills.append({**{key: skill[key] for key in ('skill_id', 'name', 'category', 'experience_months',
            'context', 'evidence_type', 'explicit', 'item_ids', 'sources', 'conflicting_fields')},
            'proficiency': proficiency if proficiency in {'beginner', 'intermediate', 'advanced', 'expert'} else None,
            'reported_proficiency': proficiency, 'source_evidence': evidence,
            'evidence': joined if joined and len(joined) <= 600 else None})
    return validate_snapshot({'id': summary.id, 'user_id': owner, 'version': summary.version,
        'file_name': summary.file_name, 'file_type': row['file_type'], 'skills': skills,
        'extraction_status': summary.extraction_status, 'extraction_version': summary.extraction_version,
        'profile_version': row['profile_version'], 'created_at': row['created_at'], 'updated_at': row['updated_at'],
        # C source IDs are intentionally not claimed to be Career registry IDs.
        # Existing assessment validation rejects mismatched mapping versions.
        'skill_mapping_version': MAPPING_VERSION})


class CvClient:
    def __init__(self, client):
        self.client = client

    async def read(self, path, token):
        # Bound bytes before JSON decoding, including chunked responses. The
        # current CV authority has no aggregate skill/excerpt count limit.
        async with self.client.stream('GET', path, headers={'Authorization': token}, follow_redirects=False) as response:
            if response.status_code != 200: return response.status_code, None
            size = response.headers.get('content-length')
            if size is not None and int(size) > MAX_CV_RESPONSE_BYTES: raise intake_limit()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_CV_RESPONSE_BYTES: raise intake_limit()
                body.extend(chunk)
            return response.status_code, json.loads(body)

    async def list(self, token):
        try:
            status, body = await self.read('/api/v1/cv', token)
            if status != 200: raise ValueError
            if 'cvs' in body: return [saved_summary(row) for row in body['cvs']]
            # Existing deployed read-only CV responses remain compatible.
            return [CvSummary.model_validate(row) for row in body['items']]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise GoalError('Saved CVs are unavailable. Retry or continue without a CV.', 503) from None

    async def get(self, identifier, token, owner):
        try:
            identifier = cv_reference(identifier)
            status, body = await self.read('/api/v1/cv/' + quote(identifier, safe=''), token)
            if status == 404:
                raise GoalError('That CV is unavailable. Choose another or continue without it.', 409)
            if status != 200: raise ValueError
            cv = saved_snapshot(body, owner) if 'status' in body else validate_snapshot(body)
            if cv.id != identifier: raise ValueError('CV identity mismatch.')
            if cv.user_id != owner or cv.extraction_status != 'succeeded':
                raise GoalError('Choose a successfully processed CV owned by this account.')
            return cv
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise GoalError('The CV service is unavailable. Retry or continue without a CV.', 503) from None

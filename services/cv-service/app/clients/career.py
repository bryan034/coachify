"""Read the owner's selected confirmed context from the Career authority."""
import asyncio
import json
from urllib.parse import quote, urlsplit
import unicodedata
import httpx
from pydantic import ConfigDict, Field, field_validator
from app.domain.errors import Conflict, CvError
from app.schemas.cv import ConfirmedContext, Title


MAX_CONTEXT_BYTES = 1024 * 1024


class CareerContext(ConfirmedContext):
    """Production responses require all fields; legacy test contexts may omit labels."""
    model_config = ConfigDict(extra='forbid', strict=True)
    selection_version: int = Field(ge=1, strict=True)
    role: Title
    field: Title

    @field_validator('skill_ids')
    @classmethod
    def canonical_skills(cls, values):
        if len(set(values)) != len(values): raise ValueError('Duplicate target skills.')
        for value in values:
            if not value.startswith('skill:') or value != 'skill:' + ' '.join(unicodedata.normalize('NFKC', value[6:]).split()).casefold():
                raise ValueError('Invalid canonical skill identity.')
        return values


def service_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise RuntimeError('CAREER_SERVICE_URL must be a service origin without credentials, path, query or fragment.')
    return value.rstrip('/')


class CareerTargetProvider:
    def __init__(self, client): self.client = client

    async def selected_context(self, authorization):
        return await self._read('/api/v1/career/goals/current/confirmed-context', authorization, allow_none=True)

    async def context(self, authorization, identifier, version):
        result = await self._read('/api/v1/career/goals/' + quote(identifier, safe='') + '/confirmed-context',
                                  authorization, params={'expected_version': version})
        if result['id'] != identifier or result['version'] != version:
            raise Conflict('The confirmed Career context changed. Refresh before preparing questions.')
        return result

    async def _read(self, path, authorization, params=None, allow_none=False):
        try:
            # The timeout covers the entire streamed read, including slow chunked responses.
            async with asyncio.timeout(5):
                async with self.client.stream('GET', path, params=params,
                                              headers={'Authorization': authorization}) as response:
                    messages = {401: 'Your session has ended. Sign in again.',
                        403: 'Finish your initial setup before using Career context.',
                        404: 'This Career target is unavailable. Refresh your selected target.',
                        409: 'Your selected Career target changed. Refresh before preparing questions.'}
                    if response.status_code in messages:
                        raise CvError(messages[response.status_code], response.status_code)
                    if response.status_code != 200: raise ValueError('Career context unavailable.')
                    content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    if content_type != 'application/json': raise ValueError('Career context must be JSON.')
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_CONTEXT_BYTES: raise ValueError('Career context exceeds its bound.')
            payload = json.loads(content)
            if payload is None and allow_none: return None
            return CareerContext.model_validate(payload).model_dump(mode='json')
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, RecursionError) as exc:
            raise CvError('Career context is unavailable. Keep your inputs and retry.', 503) from exc

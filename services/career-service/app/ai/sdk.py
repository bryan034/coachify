"""OpenAI SDK transport with bounded bodies and caller-owned retry policy.

The application owns the supplied HTTP client. Closing the SDK wrapper must not
close it: search and authentication may still be using that same client.
"""
from contextlib import asynccontextmanager

import httpx
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError, Omit


class ProviderHTTPClient(httpx.AsyncClient):
    def __init__(self, upstream):
        super().__init__(trust_env=False, follow_redirects=False)
        self.upstream = upstream

    async def send(self, request, **kwargs):
        # The SDK otherwise eagerly reads rejection bodies before raising an
        # APIStatusError. Bound that read before any SDK parsing or diagnostics.
        kwargs.update(stream=True, follow_redirects=False)
        response = await self.upstream.send(request, **kwargs)
        if response.status_code == 200:
            return response
        data = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 16 * 1024:
                    data.clear()
                    break
        finally:
            await response.aclose()
        # aiter_bytes has already decoded compression/chunking. Do not ask the
        # SDK to decode the replacement body a second time.
        headers={key:value for key,value in response.headers.items()
                 if key.lower() not in ('content-encoding','content-length','transfer-encoding')}
        return httpx.Response(response.status_code, headers=headers,
                              content=bytes(data), request=request)


def model_client(settings, http_client):
    return AsyncOpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key.get_secret_value() or 'local-no-key',
        http_client=ProviderHTTPClient(http_client),
        max_retries=0,
        timeout=settings.timeout_seconds,
    )


@asynccontextmanager
async def completion_response(client, payload, *, local=False):
    parameters = dict(payload)
    # OpenAI-compatible vendor extensions travel through the SDK's explicit
    # extension field, rather than changing the shared Chat Completions shape.
    extra = {key: parameters.pop(key) for key in ('thinking',) if key in parameters}
    rejection=None
    try:
        async with client.chat.completions.with_streaming_response.create(
            **parameters, extra_body=extra or None,
            extra_headers={'Authorization': Omit()} if local else None,
        ) as response:
            yield response.http_response
    except APIStatusError as error:
        rejection=error.response
    except APITimeoutError:
        raise httpx.ReadTimeout('Model request timed out.') from None
    except APIConnectionError:
        raise httpx.ConnectError('Model connection failed.') from None
    # Leave the SDK exception handler before the caller raises its safe error;
    # otherwise provider prose can remain attached as implicit exception context.
    if rejection is not None:
        yield rejection

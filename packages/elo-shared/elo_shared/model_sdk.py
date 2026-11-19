"""OpenAI SDK transport with bounded bodies and caller-owned retry policy.

The application owns the supplied HTTP client. Closing the SDK wrapper must not
close it: search and authentication may still be using that same client.
"""
from contextlib import asynccontextmanager, contextmanager
from elo_shared.model_telemetry import Measurement
import os
from urllib.parse import urlsplit

import httpx
from openai import OpenAI, AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError


def resolve_model_api_key(base_url, service_key):
    """Use the shared OpenRouter key only for its exact HTTPS origin.

    An explicitly configured service key takes precedence. Future model
    integrations can use the same resolver after validating their base URL.
    """
    key = (service_key or '').strip()
    if key:
        return key
    try:
        parsed = urlsplit(base_url)
        is_openrouter = (parsed.scheme == 'https' and parsed.hostname == 'openrouter.ai'
                         and parsed.port in (None, 443) and not parsed.username
                         and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        is_openrouter = False
    return os.getenv('OPENROUTER_API_KEY', '').strip() if is_openrouter else ''


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
        # Disabled AI still builds a client; it never sends this placeholder.
        api_key=settings.api_key.get_secret_value() or 'not-configured',
        http_client=ProviderHTTPClient(http_client),
        max_retries=0,
        timeout=settings.timeout_seconds,
    )


@asynccontextmanager
async def _completion_response(client, payload):
    parameters = dict(payload)
    rejection=None
    try:
        async with client.chat.completions.with_streaming_response.create(**parameters) as response:
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


class SyncProviderHTTPClient(httpx.Client):
    def __init__(self, upstream):
        super().__init__(trust_env=False, follow_redirects=False)
        self.upstream = upstream

    def send(self, request, **kwargs):
        kwargs.update(stream=True, follow_redirects=False)
        response = self.upstream.send(request, **kwargs)
        if response.status_code == 200:
            return response
        data = bytearray()
        try:
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 16 * 1024:
                    data.clear()
                    break
        finally:
            response.close()
        headers = {key: value for key, value in response.headers.items()
                   if key.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')}
        return httpx.Response(response.status_code, headers=headers,
                              content=bytes(data), request=request)


@contextmanager
def _sync_model_response(http_client, base_url, api_key, timeout, payload):
    parameters = dict(payload)
    rejection = None
    try:
        with OpenAI(base_url=base_url, api_key=api_key,
                    http_client=SyncProviderHTTPClient(http_client),
                    max_retries=0, timeout=timeout) as client:
            with client.chat.completions.with_streaming_response.create(**parameters) as response:
                yield response.http_response
    except APIStatusError as error:
        rejection = error.response
    except APITimeoutError:
        raise httpx.ReadTimeout('Model request timed out.') from None
    except APIConnectionError:
        raise httpx.ConnectError('Model connection failed.') from None
    if rejection is not None:
        yield rejection


@asynccontextmanager
async def completion_response(client, payload, *, telemetry=None):
    labels = dict(telemetry or {})
    labels.setdefault('provider', client.base_url.host)
    measurement = Measurement(payload, labels)
    failure = None
    try:
        async with _completion_response(client, payload) as response:
            measurement.status = response.status_code
            yield measurement.wrap_async(response)
    except BaseException as exc:
        failure = 'timeout' if isinstance(exc, httpx.TimeoutException) else 'interrupted'
        raise
    finally:
        measurement.finish(failure)


@contextmanager
def sync_model_response(http_client, base_url, api_key, timeout, payload, *, telemetry=None):
    labels = dict(telemetry or {})
    labels.setdefault('provider', urlsplit(base_url).hostname)
    measurement = Measurement(payload, labels)
    failure = None
    try:
        with _sync_model_response(http_client, base_url, api_key, timeout, payload) as response:
            measurement.status = response.status_code
            yield measurement.wrap_sync(response)
    except BaseException as exc:
        failure = 'timeout' if isinstance(exc, httpx.TimeoutException) else 'interrupted'
        raise
    finally:
        measurement.finish(failure)


@asynccontextmanager
async def async_model_response(http_client, base_url, api_key, timeout, payload, *, telemetry=None):
    async with AsyncOpenAI(base_url=base_url, api_key=api_key,
                          http_client=ProviderHTTPClient(http_client),
                          max_retries=0, timeout=timeout) as client:
        async with completion_response(client, payload, telemetry=telemetry) as response:
            yield response

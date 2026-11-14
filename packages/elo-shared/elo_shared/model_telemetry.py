"""Content-free, best-effort measurements for model requests.

Only allowlisted numeric usage and identifiers enter logs. Provider bodies and
prompts are held only until the response is consumed and are never logged.
"""
import json
import logging
import math
import re
import time
from uuid import uuid4

logger = logging.getLogger('elo.model_usage')
_MAX_BODY = 1024 * 1024
_IDENTIFIER = re.compile(r'^[A-Za-z0-9_./:-]{1,100}$')


def _identifier(value):
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str).encode())
    except (TypeError, ValueError):
        return None


class Measurement:
    def __init__(self, payload, labels):
        self.start = time.monotonic()
        self.body = bytearray()
        self.overflow = False
        self.status = None
        labels = labels or {}
        self.event = {
            'request_id': uuid4().hex,
            'service': _identifier(labels.get('service')),
            'stage': _identifier(labels.get('stage')),
            'operation_id': _identifier(labels.get('operation_id')),
            'attempt_reason': _identifier(labels.get('attempt_reason')),
            'prompt_version': _identifier(labels.get('prompt_version')),
            'schema_version': _identifier(labels.get('schema_version')),
            'requested_model': _identifier(payload.get('model')),
            'requested_provider': _identifier(labels.get('provider')),
            'request_bytes': _size(payload),
            'messages_bytes': _size(payload.get('messages', payload.get('input'))),
            'schema_bytes': _size(payload.get('response_format', payload.get('text'))),
            'byok': None,
        }

    def capture(self, chunk):
        if not self.overflow:
            if len(self.body) + len(chunk) > _MAX_BODY:
                self.body.clear()
                self.overflow = True
            else:
                self.body.extend(chunk)

    def finish(self, failure=None):
        event = self.event
        event.update(http_status=self.status, latency_ms=round((time.monotonic() - self.start) * 1000),
                     transport_failure=failure, input_tokens=None, cached_input_tokens=None,
                     output_tokens=None, reasoning_tokens=None, provider_cost=None,
                     returned_model=None, returned_provider=None, provider_generation_id=None, finish_status=None)
        try:
            envelope = json.loads(self.body) if self.body and not self.overflow else {}
            if not isinstance(envelope, dict): envelope = {}
            usage = envelope.get('usage')
            if not isinstance(usage, dict): usage = {}
            event['input_tokens'] = _count(usage.get('prompt_tokens', usage.get('input_tokens')))
            event['output_tokens'] = _count(usage.get('completion_tokens', usage.get('output_tokens')))
            prompt_details = usage.get('prompt_tokens_details', usage.get('input_tokens_details'))
            completion_details = usage.get('completion_tokens_details', usage.get('output_tokens_details'))
            if isinstance(prompt_details, dict): event['cached_input_tokens'] = _count(prompt_details.get('cached_tokens'))
            if isinstance(completion_details, dict): event['reasoning_tokens'] = _count(completion_details.get('reasoning_tokens'))
            cost = usage.get('cost')
            if type(cost) in (float, int) and math.isfinite(cost) and cost >= 0: event['provider_cost'] = cost
            event['returned_model'] = _identifier(envelope.get('model'))
            event['returned_provider'] = _identifier(envelope.get('provider'))
            event['provider_generation_id'] = _identifier(envelope.get('id'))
            choices = envelope.get('choices')
            finish = choices[0].get('finish_reason') if isinstance(choices, list) and choices and isinstance(choices[0], dict) else envelope.get('status')
            if finish in ('stop', 'length', 'content_filter', 'tool_calls', 'completed', 'incomplete', 'failed'):
                event['finish_status'] = finish
        except (ValueError, UnicodeDecodeError, TypeError):
            pass
        finally:
            self.body.clear()
        # The event contains only the allowlisted fields above, never body text.
        try:
            logger.info('model_usage %s', json.dumps(event, separators=(',', ':')))
        except Exception:
            # Instrumentation must never change the request outcome.
            pass

    def wrap_sync(self, response):
        if response.is_stream_consumed:
            self.capture(response.content)
            return response
        original = response.iter_bytes
        def iterate(*args, **kwargs):
            for chunk in original(*args, **kwargs):
                self.capture(chunk)
                yield chunk
        response.iter_bytes = iterate
        return response

    def wrap_async(self, response):
        if response.is_stream_consumed:
            self.capture(response.content)
            return response
        original = response.aiter_bytes
        async def iterate(*args, **kwargs):
            async for chunk in original(*args, **kwargs):
                self.capture(chunk)
                yield chunk
        response.aiter_bytes = iterate
        return response

"""Retry only an unfinished LangGraph model node until its output validates."""
import asyncio
import inspect
import logging
from functools import wraps
from app.ai.errors import AIError
from app.ai.recovery import recover_responses, validation_feedback, validation_progress

MAX_REPAIRS = 6


async def notify(feedback):
    observer = validation_progress.get()
    if observer:
        result = observer(feedback)
        if inspect.isawaitable(result): await result


def structured_node(node):
    @wraps(node)
    async def run(state):
        if not recover_responses.get(): return await node(state)
        context = validation_feedback.set(None)
        attempt = 0
        try:
            while True:
                try:
                    return await node(state)
                except AIError as error:
                    if error.code not in ('invalid_output','incomplete_output'): raise
                    attempt += 1
                    if attempt > MAX_REPAIRS:raise
                    feedback = {'reason': error.reason or ('incomplete_json' if error.code=='incomplete_output' else 'response_envelope'),
                                'fields': list(error.fields), 'violations': list(error.violations)}
                    validation_feedback.set(feedback)
                    await notify(feedback)
                    logging.getLogger('uvicorn.error.ai_usage').info(
                        'structured_recovery node=%s correction=%s reason=%s',
                        node.__name__, attempt, feedback['reason'])
                    await asyncio.sleep(0)  # Allow shutdown/replacement between attempts.
        finally:
            validation_feedback.reset(context)
            await notify(None)
    return run

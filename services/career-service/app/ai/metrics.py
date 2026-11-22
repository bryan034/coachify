"""Task-local numeric usage observation; never retains prompt/response text."""
from contextvars import ContextVar
from collections.abc import Callable
usage_observer:ContextVar[Callable[[dict],None]|None]=ContextVar('usage_observer',default=None)
COUNTERS=('prompt_tokens','completion_tokens','total_tokens','cached_tokens','reasoning_tokens')


def usage_counts(usage):
    if not isinstance(usage,dict):return {}
    counts={key:value for key in COUNTERS[:3] if type(value:=usage.get(key)) is int and value>=0}
    for container,key in (('completion_tokens_details','reasoning_tokens'),('prompt_tokens_details','cached_tokens')):
        details=usage.get(container)
        if isinstance(details,dict) and type(value:=details.get(key)) is int and value>=0:counts[key]=value
    return counts


def observe_usage(usage):
    observer=usage_observer.get()
    if observer and (counts:=usage_counts(usage)):observer(counts)

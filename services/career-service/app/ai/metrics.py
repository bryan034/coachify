"""Task-local numeric usage observation; never retains prompt/response text."""
from contextvars import ContextVar
from collections.abc import Callable
usage_observer:ContextVar[Callable[[dict],None]|None]=ContextVar('usage_observer',default=None)

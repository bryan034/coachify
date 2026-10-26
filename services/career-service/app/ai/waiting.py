"""Task-local quota progress; ordinary synchronous API calls still return 429."""
from contextvars import ContextVar
from typing import Callable

quota_progress: ContextVar[Callable[[int | None], None] | None] = ContextVar('quota_progress', default=None)

quota_reason: ContextVar[dict | None] = ContextVar('quota_reason', default=None)

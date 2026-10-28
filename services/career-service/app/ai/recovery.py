"""Task-local structured-output recovery; feedback contains schema metadata only."""
from contextvars import ContextVar
from collections.abc import Callable
from typing import Any

recover_responses = ContextVar('recover_responses', default=False)
validation_feedback: ContextVar[dict | None] = ContextVar('validation_feedback', default=None)
validation_progress: ContextVar[Callable[[dict | None], Any] | None] = ContextVar('validation_progress', default=None)
validation_budget: ContextVar[Any] = ContextVar('validation_budget', default=None)


def schema_fields(schema):
    names = set()
    if isinstance(schema, dict):
        names.update(schema.get('properties', {}))
        for value in schema.values(): names.update(schema_fields(value))
    elif isinstance(schema, list):
        for value in schema: names.update(schema_fields(value))
    return names


def issues_for(error, model):
    """Exclude submitted values, validator prose/ctx and untrusted extra-field names."""
    known = schema_fields(model.model_json_schema())
    issues = []
    for issue in error.errors(include_input=False, include_context=False, include_url=False)[:12]:
        path = []
        for part in issue['loc']:
            if isinstance(part, str):
                if part not in known: break
                path.append(part)
            elif type(part) is int: path.append(str(part))
        issues.append({'field': '.'.join(path) or '$', 'issue': issue['type']})
    return issues

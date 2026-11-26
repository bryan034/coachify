"""Task-local structured-output recovery; feedback contains schema metadata only."""
from contextvars import ContextVar
from collections.abc import Callable
from typing import Any
from pydantic import ValidationError

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


def validation_detail(error):
    """Which model check failed and where, for logs; never the submitted values."""
    if not isinstance(error, ValidationError): return None
    return [{'model': error.title, 'loc': '.'.join(map(str, issue['loc'])), 'type': issue['type'],
             **({'msg': issue['msg']} if issue['type'] == 'value_error' else {})}
            for issue in error.errors(include_input=False, include_context=False, include_url=False)[:5]]

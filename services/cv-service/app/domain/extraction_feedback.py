"""Bounded repair guidance from schema metadata, never validator prose/values."""
from pydantic import ValidationError
from app.domain.extraction_errors import EvidenceValidationError
from app.schemas.cv import Extraction

MAX_ISSUES = 16
RULES = {
    'source_excerpt': 'Use an existing block_id and evidence supported by that block. Faithful paraphrases and formatting changes are accepted, but do not add or contradict facts; keep each summary at most 500 characters.',
    'literal_skill': 'Explicit skill labels must occur in this item\'s cited original source blocks. Keep inferred skills separate and source-linked.',
    'date_precision': 'Dates must occur in the cited source with the same year/month/day precision. Never invent precision.',
    'ongoing_status': 'Set ongoing only if the cited source explicitly states it; ongoing items have no end_date.',
    'duplicate_claim': 'Separate same-kind claims need distinct truthful evidence; do not fabricate evidence for uniqueness.',
    'source_relationship': 'supporting_items must reference existing, different items using final zero-based array indexes.',
    'circular_relationship': 'Remove circular supporting_items relationships while retaining supported claims.',
}


def _fields(value):
    if isinstance(value, dict):
        return set(value.get('properties', {})).union(*(_fields(item) for item in value.values()))
    if isinstance(value, list): return set().union(*(_fields(item) for item in value))
    return set()


FIELDS = _fields(Extraction.model_json_schema())
ERROR_TYPES = frozenset({'missing', 'extra_forbidden', 'literal_error', 'model_type', 'dict_type',
    'list_type', 'string_type', 'string_too_short', 'string_too_long', 'string_pattern_mismatch',
    'bool_type', 'int_type', 'float_type', 'greater_than_equal', 'less_than_equal',
    'finite_number', 'too_short', 'too_long', 'value_error'})


def feedback_for(error):
    if isinstance(error, EvidenceValidationError):
        return [{'field': f'items[{error.item_index}]' if error.item_index is not None else 'items',
                 'issue': error.rule, 'guidance': RULES[error.rule]}]
    if not isinstance(error, ValidationError):
        return [{'field': 'items', 'issue': 'evidence_validation',
                 'guidance': 'Recheck evidence, explicit skill labels, date precision and supporting relationships against the original source.'}]
    issues = []
    for issue in error.errors(include_input=False, include_context=False, include_url=False)[:MAX_ISSUES]:
        path = ''
        for part in issue['loc']:
            if type(part) is int and 0 <= part <= 1_000_000:
                path += f'[{part}]'
            elif isinstance(part, str) and part in FIELDS:
                path += ('.' if path else '') + part
            else:
                path += '.other'
                break
        kind = issue['type'] if issue['type'] in ERROR_TYPES else 'other'
        guidance = 'Match the supplied schema; do not invent facts to fill required fields.'
        if path.endswith('.excerpt'):
            guidance = 'Use a source-supported summary of 1–500 characters.'
            if kind == 'string_too_long':
                guidance = ('Replace this overlong quotation with a shorter faithful summary of the same source block. '
                    'Target fewer than 400 characters; the hard limit is 500 characters including spaces, punctuation and line breaks, not tokens. '
                    'Paraphrasing is allowed. Do not repeat the overlong text unchanged or add unsupported facts. '
                    'Preserve names, numbers, negation, conditions and personal/team attribution. ')
                guidance += ('Split remaining uncategorised content into separate other_information entries.'
                             if path.startswith('other_information[')
                             else 'Use separate short quotations for distinct supporting facts, with at most six evidence citations per item.')
        elif kind == 'value_error' and path.startswith('items['):
            guidance = 'Dates must be valid calendar values with supported precision; start cannot follow end; ongoing=true requires end_date=null.'
        issues.append({'field': path or '$', 'issue': kind, 'guidance': guidance})
    return issues

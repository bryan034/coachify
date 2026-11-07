"""Bounded repair guidance from schema metadata, never validator prose/values."""
from pydantic import ValidationError
from app.domain.extraction_errors import EvidenceValidationError
from app.schemas.cv import Extraction

MAX_ISSUES = 16
RULES = {
    'source_excerpt': 'Use an existing source block and evidence supported by that block. Faithful paraphrases are accepted for item evidence.excerpt and other_information.excerpt, and factual interpretations must preserve the source meaning. Review evidence.quote must instead copy text from its cited source_id; never paraphrase a quotation. Do not add or contradict facts.',
    'review_source': 'Use a source_id from the supplied original CV blocks for this review evidence citation. Its quote must copy text from that same block. Never invent an ID or attach a quotation to a different passage.',
    'review_quote': 'Replace this review evidence quote with a quotation copied from its cited source_id block. Case, whitespace and Unicode presentation differences are tolerated, but do not paraphrase, join non-contiguous passages or change punctuation. Preserve the supported fact and choose an exact quotation that supports it; never fabricate evidence.',
    'literal_skill': 'Explicit skill labels must occur in this item\'s cited original source blocks. Keep inferred skills separate and source-linked.',
    'date_precision': 'Dates must occur in the cited source with the same year/month/day precision. Never invent precision.',
    'ongoing_status': 'Set ongoing only if the cited source explicitly states it; ongoing items have no end_date.',
    'duplicate_claim': 'Separate same-kind claims need distinct truthful evidence; do not fabricate evidence for uniqueness.',
    'duplicate_review_evidence': 'Within this item, include at most one review_evidence fact for each field and normalized skill_name (including absent skill_name). Combine supported details and citations into that fact, preserving conflicting or uncertain information; do not invent evidence or silently discard supported details.',
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
        path = f'items[{error.item_index}]' if error.item_index is not None else 'items'
        if error.review_index is not None:
            path += f'.review_evidence[{error.review_index}]'
        if error.quote_index is not None:
            path += f'.evidence[{error.quote_index}]'
        if error.rule in ('review_source', 'review_quote'):
            path += '.source_id' if error.rule == 'review_source' else '.quote'
        return [{'field': path,
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
            guidance = 'Use non-empty evidence supported by the cited source block.'
        elif path.endswith('.quote'):
            guidance = RULES['review_quote']
        elif path.endswith('.source_id'):
            guidance = RULES['review_source']
        elif kind == 'value_error' and path.startswith('items['):
            guidance = 'Dates must be valid calendar values with supported precision; start cannot follow end; ongoing=true requires end_date=null.'
        issues.append({'field': path or '$', 'issue': kind, 'guidance': guidance})
    return issues

"""Keep the verified part of an extraction when only some items fail validation.

This runs only after the repair attempt (and the automatic retries) failed. An item
that cannot be verified is kept as unconfirmed context, flagged for the review chat,
and never counts as demonstrated capability. Failures that cannot be pinned on one
item (duplicate claims, circular relationships, nothing verifiable) still fail the
whole extraction, as before.
"""
from dataclasses import dataclass, field
from pydantic import ValidationError
from app.domain.capabilities import (digest, evidence_requiring_semantic_check, skill_id,
                                     validate_extraction, validate_other_information)
from app.domain.extraction_errors import EvidenceValidationError
from app.schemas.cv import Extraction, SourceExcerpt

KINDS = ('education', 'experience', 'project', 'skill')
MAX_SEMANTIC_REFERENCES = 1120
MAX_ENTRIES = 160
# Fixed wording only: never validator prose, model output or CV content.
ISSUE_MESSAGE = ('This section could not be verified against your CV, so it is kept as unconfirmed. '
                 'Explain it in the review chat to confirm it.')


@dataclass
class Salvage:
    items: list
    other_information: list
    flagged: list = field(default_factory=list)
    dropped: int = 0
    other_dropped: int = 0

    @property
    def notices(self):
        notices = []
        if self.flagged:
            notices.append(f'{len(self.flagged)} extracted section{"" if len(self.flagged) == 1 else "s"} could not be verified '
                           'against your CV after retrying. Each is kept as unconfirmed and marked in the review; '
                           'explain it in the review chat to confirm it.')
        if self.dropped or self.other_dropped:
            notices.append(f'{self.dropped + self.other_dropped} extracted entr{"y" if self.dropped + self.other_dropped == 1 else "ies"} '
                           'could not be read or verified and were left out.')
        return notices


def _text(value, limit):
    return ' '.join(value.split())[:limit] if isinstance(value, str) else ''


def _unverified_item(raw, code, source, cv_id):
    """Retain what the model extracted, without any claim the backend could not check."""
    kind, title = raw.get('kind'), _text(raw.get('title'), 200)
    description = ' '.join(raw['description'].split())[:4000] if isinstance(raw.get('description'), str) else ''
    if kind not in KINDS or not title or not description: return None
    evidence = []
    for ref in raw.get('evidence') if isinstance(raw.get('evidence'), list) else []:
        if not isinstance(ref, dict) or ref.get('block_id') not in source: continue
        excerpt = ref.get('excerpt')
        if isinstance(excerpt, str) and excerpt.strip():
            evidence.append({'id': ref['block_id'], 'location': source[ref['block_id']]['location'], 'excerpt': excerpt})
    names = {}
    for name in raw.get('skill_names') if isinstance(raw.get('skill_names'), list) else []:
        name = _text(name, 200)
        if name: names.setdefault(skill_id(name), name)
    if kind == 'skill': names.setdefault(skill_id(title), title)
    identity = digest({'cv': cv_id, 'kind': kind, 'evidence': sorted(evidence, key=lambda e: (e['id'], e['excerpt'])),
                       'unverified': [title, description]})[:32]
    return {'review_evidence': [], 'id': identity, 'kind': kind, 'title': title, 'description': description,
            'provenance': 'inferred', 'evidence': evidence, 'skill_ids': list(names), 'skill_names': list(names.values()),
            'category': 'unspecified', 'proficiency': None, 'experience_months': None, 'context': None,
            'start_date': None, 'end_date': None, 'ongoing': False, 'removed': False, 'supporting_item_ids': [],
            # Unverified skills stay uncertain, and the review chat asks about this section.
            'support_uncertain': True, 'uncertainties': ['claim'],
            'validation_issue': {'status': 'unverified', 'code': code, 'message': ISSUE_MESSAGE}}


def _acyclic(items):
    by_id, state = {item['id']: item for item in items}, {}
    def visit(identifier):
        if state.get(identifier) == 'done': return True
        if state.get(identifier) == 'active': return False
        state[identifier] = 'active'
        ok = all(visit(parent) for parent in by_id[identifier]['supporting_item_ids'])
        state[identifier] = 'done'
        return ok
    return all(visit(identifier) for identifier in by_id)


def salvage(candidate, blocks, cv_id, verify_evidence=None, support=None):
    """The kept items, or None when the failure is not item-specific or nothing verifies."""
    raw_items = candidate.get('items') if isinstance(candidate, dict) else None
    if not isinstance(raw_items, list) or not raw_items: return None
    # The size of either list is a whole-output limit, not one item's fault.
    if len(raw_items) > MAX_ENTRIES or len(candidate.get('other_information') or []) > MAX_ENTRIES: return None
    source = {block['id']: block for block in blocks}
    outcome, pending = {}, {}
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            outcome[index] = ('drop', None)
            continue
        # Judge each item alone. Relationships between items are rebuilt below.
        single = {'items': [{**raw, 'supporting_items': []}]}
        try:
            pending[index] = evidence_requiring_semantic_check(single, blocks)
            Extraction.model_validate(single)
        except EvidenceValidationError as error:
            outcome[index] = ('flag', error.rule)
        except ValidationError:
            outcome[index] = ('flag', 'schema_validation')
        except ValueError:
            outcome[index] = ('flag', 'evidence_validation')
    other_refs, other_pending = [], []
    for ref in candidate.get('other_information') if isinstance(candidate.get('other_information'), list) else []:
        try:
            SourceExcerpt.model_validate(ref)
            other_pending.extend(evidence_requiring_semantic_check({'items': [], 'other_information': [ref]}, blocks))
            other_refs.append(ref)
        except (ValueError, ValidationError):
            other_refs.append(None)
    if support is None:
        references = []
        for value in [*(v for index, v in pending.items() if index not in outcome), other_pending]:
            references.extend(ref for ref in value if ref not in references)
        if len(references) > MAX_SEMANTIC_REFERENCES: return None
        support = verify_evidence(blocks, references) if references and verify_evidence else frozenset()
    kept = {}
    for index, raw in enumerate(raw_items):
        if index in outcome: continue
        try:
            kept[index] = validate_extraction({'items': [{**raw, 'supporting_items': []}]}, blocks, cv_id, support)[0]
        except EvidenceValidationError as error:
            outcome[index] = ('flag', error.rule)
        except ValidationError:
            outcome[index] = ('flag', 'schema_validation')
    if not kept: return None
    flagged = []
    for index, (action, code) in sorted(outcome.items()):
        if action != 'flag': continue
        item = _unverified_item(raw_items[index], code, source, cv_id)
        if item: kept[index] = item; flagged.append(item['id'])
        else: outcome[index] = ('drop', None)
    ids = {index: item['id'] for index, item in kept.items()}
    for index, item in kept.items():
        if item['id'] in flagged: continue
        refs = raw_items[index].get('supporting_items')
        item['supporting_item_ids'] = list(dict.fromkeys(
            ids[ref] for ref in (refs if isinstance(refs, list) else [])
            if type(ref) is int and ref != index and ref in ids))
    items = [kept[index] for index in sorted(kept)]
    # A duplicated source claim or a circular relationship is not one item's fault.
    if len({item['id'] for item in items}) != len(items) or not _acyclic(items): return None
    other, other_dropped = [], 0
    for ref in other_refs:
        try:
            if ref is None: raise ValueError
            other.extend(validate_other_information([SourceExcerpt.model_validate(ref)], blocks, support))
        except (ValueError, ValidationError):
            other_dropped += 1
    unique_other = []
    for entry in other:
        if entry not in unique_other: unique_other.append(entry)
    return Salvage(items, unique_other, flagged, sum(action == 'drop' for action, _ in outcome.values()), other_dropped)

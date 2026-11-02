"""Persistent navigation state and transient, source-grounded provider context."""
from copy import deepcopy
import json
from app.domain.capabilities import effective_items, digest, normalized_name
from app.domain.attachments import source_fingerprint
from app.schemas.interview import InterviewProgress
from app.schemas.interview_evidence import fact_key

MAX_CONTEXT_BYTES = 96 * 1024
MAX_TARGET_ATTEMPTS = 2


def target_key(item_id, field, skill_name=None):
    return item_id + ':' + field + ':' + normalized_name(skill_name or '')


def evidence_for(item):
    """Derive the current ledger from validated facts, including legacy CV claims."""
    facts = {fact_key(f): deepcopy(f) for f in item.get('review_evidence', [])}
    for claim in item.get('skill_claims', []):
        # Legacy extraction/interpretation already validated these attributes.
        refs = [{'source_id': e['id'], 'quote': e['excerpt']} for e in claim.get('evidence', [])][:3]
        if not refs: continue
        for field, attribute in [('personal_contribution', 'attribution'), ('assistance', 'assistance')]:
            value = claim.get(attribute)
            key = (field, normalized_name(claim['name']))
            if key not in facts and value not in {None, 'unknown'} and (field != 'personal_contribution' or claim.get('evidence_type') == 'user_clarified'):
                facts[key] = {'field': field, 'skill_name': claim['name'], 'status': 'supported',
                              'value': value, 'evidence': refs, 'attribution': claim.get('attribution')}
    return list(facts.values())


def reconcile_memory(conversation, document):
    """Rebuild after evidence changes; retain progress only for unchanged sources."""
    old = conversation.get('interview_memory') or {}
    items = [i for i in effective_items(document) if not i['removed']]
    signatures = {i['id']: digest({'source': source_fingerprint(i), 'review': i.get('review_evidence', [])}) for i in items}
    same_generation = old.get('extraction_version') == document['extraction_version']
    unchanged = {i for i, signature in signatures.items()
                 if same_generation and old.get('sources', {}).get(i) == signature}
    coverage = {i: value for i, value in old.get('coverage', {}).items() if i in unchanged}
    estimates = [e for e in old.get('estimates', []) if e['item_id'] in unchanged]
    # Evidence progress, rather than wording, resets repetition protection.
    originals = {i['id']: digest({'original': i, 'overlay': document.get('overlays', {}).get(i['id'])}) for i in document.get('original_items', []) if i['id'] in signatures}
    stable_sources = {i for i in originals if same_generation and old.get('input_sources', {}).get(i) == originals[i]}
    attempts = {k: v for k, v in old.get('attempts', {}).items() if any(k.startswith(i + ':') for i in stable_sources)}
    answers = {q['id']: q['status'] for q in document['clarifications'] if not q.get('reconciliation_required')}
    history = [{**q, 'answer_status': answers.get(q['id'], 'unanswered')} for q in old.get('questions', []) if q.get('item_id') in signatures and q['id'] in answers][-120:]
    return {'schema_version': 1, 'extraction_version': document['extraction_version'],
        'evidence_version': document['effective_version'], 'sources': signatures, 'input_sources': originals,
        'focus_item_id': old.get('focus_item_id') if old.get('focus_item_id') in signatures else None,
        'status': old.get('status', 'reviewing') if old.get('sources') == signatures else 'reviewing',
        'coverage': coverage, 'estimates': estimates, 'attempts': attempts,
        'questions': history,
        'notes': old.get('notes', [])[-24:],
        'summary': [{'item_id': i, 'status': value['status']} for i, value in coverage.items()]}


def progress(memory, document):
    if not memory: return None
    sources = [i for i in effective_items(document) if not i['removed'] and i['kind'] in {'project', 'experience'}]
    return InterviewProgress(status=memory['status'],
        reviewed_items=sum(i['id'] in memory['coverage'] for i in sources), total_items=len(sources),
        estimates=memory.get('estimates', [])).model_dump(mode='json')


def build_context(conversation, document, memory, *, focus_id=None, recall_ids=()):
    """Transient provider input. Older exact answers remain addressable by IDs."""
    items = [i for i in effective_items(document) if not i['removed']]
    focus_id = focus_id or memory.get('focus_item_id')
    focus = next((i for i in items if i['id'] == focus_id), None)
    if focus is None:
        focus = next((i for i in items if i['kind'] in {'project', 'experience'} and i['id'] not in memory['coverage']), None)
    if focus is None and items: focus = items[0]
    index = {}
    if focus:
        for fact in evidence_for(focus):
            ref = 'fact:' + digest({'item': focus['id'], 'fact': fact})[:24]
            index[ref] = {'item_id': focus['id'], **fact}
    # The complete answer for the focused source is retrievable even after it
    # has left the recent-message window, including earlier conversation segments.
    answers = [{'id': 'answer:' + q['id'], 'question': q['question'], 'answer': q.get('answer'),
                'resolution': q.get('resolution'), 'interpretation_status': q.get('interpretation_status')}
               for q in document['clarifications'] if focus and q['item_id'] == focus['id']
               and not q.get('reconciliation_required')]
    active = conversation.get('active_question')
    active_record = next((q for q in document['clarifications'] if active and q['id'] == active['id']), None)
    context = {'goal': 'Establish personal ownership and evidence-supported skill depth, accepting uncertainty.',
        'cv_version': document['version'], 'evidence_version': document['effective_version'],
        'active_question': {**active, 'uncertainty': active_record['uncertainty']} if active and active_record else active,
        'sources': [{'id': i['id'], 'kind': i['kind'], 'title': i['title'],
            'fields': [{'field': f['field'], 'skill_name': f.get('skill_name'), 'status': f['status']}
                       for f in evidence_for(i)], 'coverage': memory['coverage'].get(i['id'])} for i in items],
        'focused_source': focus, 'evidence_index': index, 'source_answers': answers,
        'recent_messages': [{'id': m['id'], 'role': m['role'], 'text': m['text']} for m in conversation['messages'][-10:]
                            if m['text'] != 'Your message is saved. Working on it…'],
        'memory': {k: memory[k] for k in ('summary', 'attempts', 'questions', 'status', 'notes')},
        'limits': {'max_unproductive_attempts_per_target': memory.get('max_target_attempts', MAX_TARGET_ATTEMPTS)}}
    # Never silently truncate a factual answer or pretend an omitted source was reviewed.
    if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_CONTEXT_BYTES:
        context['source_answers'] = [a if a['id'] in recall_ids else {k: a[k] for k in ('id', 'resolution', 'interpretation_status')} for a in answers]
        context['answer_retrieval_required'] = True
    if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_CONTEXT_BYTES:
        raise ValueError('This review context is too large to process safely. Your conversation and evidence are saved.')
    return context

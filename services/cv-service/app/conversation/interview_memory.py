"""Persistent navigation state and transient, source-grounded provider context."""
from copy import deepcopy
import json
from typing import get_args
from app.domain.capabilities import effective_items, digest, normalized_name
from app.domain.attachments import source_fingerprint
from app.domain.review_context import clarification_context, evidence_for, review_target_skipped
from app.domain.baseline import baseline_estimates
from app.schemas.interview import InterviewProgress
from app.schemas.interview_evidence import fact_key, ReviewField, fact_groups, facts_closed, fact_group_value

MAX_CONTEXT_BYTES = 96 * 1024
MAX_TARGET_ATTEMPTS = 2
MAX_TOPIC_QUESTIONS = 3
RECENT_MESSAGES = 4


def discussion_summary(memory):
    """Rebuild navigation from durable questions, never infer skill facts from chat."""
    sources = {}
    for question in memory['questions']:
        item = sources.setdefault(question['item_id'], {
            'item_id': question['item_id'], 'answered': 0, 'skipped': 0})
        item['answered'] += question.get('answer_status') == 'answered'
        item['skipped'] += question.get('answer_status') == 'skipped' or bool(question.get('skipped'))
        item['latest_question_id'] = question['id']
        item['latest_targets'] = question.get('targets', [])
    return list(sources.values())


def target_key(item_id, field, skill_name=None):
    return item_id + ':' + field + ':' + normalized_name(skill_name or '')




def topic_discussed(memory, item_id):
    return item_id in memory.get('discussed_topic_ids', []) or any(
        q['item_id'] == item_id and (q.get('answer_status') in {'answered', 'skipped'} or q.get('skipped'))
        for q in memory.get('questions', []))


def topic_question_count(memory, item_id):
    return memory.get('question_counts', {}).get(item_id,
        len({q['id'] for q in memory.get('questions', []) if q['item_id'] == item_id}))


def target_availability(item, memory, field, skill_name=None, *, max_attempts=MAX_TARGET_ATTEMPTS):
    """One target-admission policy shared by planner context and validation."""
    if review_target_skipped(item, field, skill_name): return 'declined'
    if topic_question_count(memory, item['id']) >= MAX_TOPIC_QUESTIONS: return 'topic_limit'
    facts = fact_groups(evidence_for(item)).get((field, normalized_name(skill_name or '')), [])
    if facts_closed(facts):
        return 'closed'
    fact = fact_group_value(facts)
    attempt = memory['attempts'].get(target_key(item['id'], field, skill_name), {})
    if attempt.get('declined'): return 'declined'
    if attempt.get('signature') == (digest(fact) if fact else 'missing') and attempt.get('count', 0) >= max_attempts:
        return 'exhausted'
    return 'open'


def question_options(item, memory):
    """Compact exact open/closed fields; explicit unknown is not a missing field."""
    skills = {normalized_name(c['name']): c['name'] for c in item.get('skill_claims', [])}
    skills.update({normalized_name(f['skill_name']): f['skill_name'] for f in evidence_for(item) if f.get('skill_name')})
    result = []
    gaps = clarification_context(item, evidence_for(item))['clarification_targets']
    for skill in [None, *skills.values()]:
        states = {field: target_availability(item, memory, field, skill,
                  max_attempts=memory.get('max_target_attempts', MAX_TARGET_ATTEMPTS)) for field in get_args(ReviewField)}
        relevant = [g['field'] for g in gaps if normalized_name(g['skill_name'] or '') == normalized_name(skill or '') and states[g['field']] == 'open']
        result.append({'skill_name': skill,
                       'clarification_fields': relevant,
                       'open_fields': relevant,
                       'closed_fields': {f: state for f, state in states.items() if state != 'open'}})
    return result


def topic_ids(items):
    """Only experiences/projects with concrete clarification needs enter review."""
    return [item['id'] for item in items if item['kind'] in {'project', 'experience'}
            and clarification_context(item, evidence_for(item))['clarification_targets']]


def reconcile_memory(conversation, document):
    """Rebuild after evidence changes; retain progress only for unchanged sources."""
    old = conversation.get('interview_memory') or {}
    items = [i for i in effective_items(document) if not i['removed']]
    signatures = {i['id']: digest({'source': source_fingerprint(i), 'review': i.get('review_evidence', [])}) for i in items}
    same_generation = old.get('extraction_version') == document['extraction_version']
    estimates = baseline_estimates(items)
    # Evidence progress, rather than wording, resets repetition protection.
    originals = {i['id']: digest({'original': i, 'overlay': document.get('overlays', {}).get(i['id'])}) for i in document.get('original_items', []) if i['id'] in signatures}
    stable_sources = {i for i in originals if same_generation and old.get('input_sources', {}).get(i) == originals[i]}
    # Topic completion records navigation, not the number of facts in an answer.
    # Ordinary clarification updates invalidate estimates, but only source edits or
    # a new extraction reopen completed topics.
    coverage = {i: value for i, value in old.get('coverage', {}).items() if i in stable_sources}
    if old.get('status') not in {'reviewed', 'reviewed_with_gaps'}:
        coverage.pop(old.get('focus_item_id'), None)
    attempts = {k: v for k, v in old.get('attempts', {}).items() if any(k.startswith(i + ':') for i in stable_sources)}
    answers = {q['id']: q['status'] for q in document['clarifications'] if not q.get('reconciliation_required')}
    # Rebuild from durable CV questions, not the bounded recent-memory window.
    question_counts, discussed_topics = {}, set()
    known_questions = {q['id'] for q in old.get('questions', [])}
    for q in document['clarifications']:
        if q['item_id'] in signatures and ('_interview_targets' in q or q['id'] in known_questions):
            question_counts[q['item_id']] = question_counts.get(q['item_id'], 0) + 1
            if q['status'] in {'answered', 'skipped'}: discussed_topics.add(q['item_id'])
    needed = set(topic_ids(items))
    retained_topics = [i for i in old.get('topic_ids', []) if i in signatures
                       and (i in needed or i in coverage or i in discussed_topics or topic_discussed(old, i))]
    history = [{**q, 'answer_status': answers.get(q['id'], 'unanswered')} for q in old.get('questions', []) if q.get('item_id') in signatures and q['id'] in answers][-120:]
    return {'schema_version': 1, 'extraction_version': document['extraction_version'],
        'evidence_version': document['effective_version'], 'sources': signatures, 'input_sources': originals,
        'focus_item_id': old.get('focus_item_id') if old.get('focus_item_id') in signatures
                         and old.get('status') not in {'reviewed', 'reviewed_with_gaps'} else None,
        'status': old.get('status', 'reviewing') if old.get('sources') == signatures else 'reviewing',
        'topic_ids': list(dict.fromkeys((retained_topics if same_generation else []) + topic_ids(items))),
        'deferred_topics': {i: value for i, value in old.get('deferred_topics', {}).items() if i in stable_sources},
        'coverage': coverage, 'estimates': estimates, 'attempts': attempts, 'question_counts': question_counts,
        'discussed_topic_ids': sorted(discussed_topics),
        'questions': history,
        'notes': old.get('notes', [])[-24:],
        'summary': [{'item_id': i, 'status': value['status']} for i, value in coverage.items()]}


def progress(memory, document):
    if not memory: return None
    sources = [i for i in effective_items(document) if not i['removed'] and i['id'] in memory.get('topic_ids', [])]
    return InterviewProgress(status=memory['status'],
        reviewed_items=sum(i['id'] in memory['coverage'] for i in sources), total_items=len(sources),
        topics=[{'id': i['id'], 'title': i['title'],
                 'status': memory['coverage'][i['id']]['status'] if i['id'] in memory['coverage'] else
                           'current' if i['id'] == memory.get('focus_item_id') else 'pending'} for i in sources],
        estimates=memory.get('estimates', [])).model_dump(mode='json')


def build_context(conversation, document, memory, *, focus_id=None, recall_ids=()):
    """Transient provider input. Older exact answers remain addressable by IDs."""
    items = [i for i in effective_items(document) if not i['removed']]
    focus_id = focus_id or memory.get('focus_item_id')
    focus = next((i for i in items if i['id'] == focus_id), None)
    if focus is None:
        focus = next((i for i in items if i['id'] in memory.get('topic_ids', []) and i['id'] not in memory['coverage']), None)
    if focus is None and items: focus = items[0]
    index = {}
    # A transition may close the previous topic while asking about a new source.
    # Retain both ledgers so closing coverage can cite the source being left.
    for item in items:
        if item['id'] not in {focus['id'] if focus else None, memory.get('focus_item_id')}: continue
        for fact in evidence_for(item):
            ref = 'fact:' + digest({'item': item['id'], 'fact': fact})[:24]
            index[ref] = {'item_id': item['id'], **fact}
    # The complete answer for the focused source is retrievable even after it
    # has left the recent-message window, including earlier conversation segments.
    answers = [{'id': 'answer:' + q['id'],
                'resolution': q.get('resolution'), 'interpretation_status': q.get('interpretation_status'),
                **({'question': q['question'], 'answer': q.get('answer')} if 'answer:' + q['id'] in recall_ids
                   else {'targets': q.get('_interview_targets', []),
                         'uncertainty': q.get('uncertainty'), 'status': q.get('status')})}
               for q in document['clarifications'] if focus and q['item_id'] == focus['id']
               and not q.get('reconciliation_required')]
    active = conversation.get('active_question')
    active_record = next((q for q in document['clarifications'] if active and q['id'] == active['id']), None)
    context = {'goal': 'Establish a source-specific baseline for every project skill using CV context and targeted questions about personal responsibilities, concrete skill application, assistance, complexity and problem solving. At most three questions per project, with no overall topic cap.',
        'cv_version': document['version'], 'evidence_version': document['effective_version'],
        'active_question': {**active, 'uncertainty': active_record['uncertainty']} if active and active_record else active,
        'review_topic_ids': memory.get('topic_ids', []),
        'sources': [{'id': i['id'], 'kind': i['kind'], 'title': i['title'],
            'questions_asked': topic_question_count(memory, i['id']),
            'questions_remaining': max(0, MAX_TOPIC_QUESTIONS - topic_question_count(memory, i['id'])),
            'review_dispositions': i.get('_review_skips', []),
            'listed_skills': [c['name'] for c in i.get('skill_claims', [])],
            'clarification_targets': clarification_context(i, evidence_for(i))['clarification_targets'],
            'fields': [{'field': f['field'], 'skill_name': f.get('skill_name'), 'status': f['status']}
                       for f in evidence_for(i)], 'coverage': memory['coverage'].get(i['id'])} for i in items],
        'baseline_skill_estimates': baseline_estimates([focus]) if focus else [],
        'focused_source': focus,
        'clarification_context': clarification_context(focus, evidence_for(focus)) if focus else None,
        'question_options': question_options(focus, memory) if focus else [],
        'evidence_index': index, 'source_answers': answers,
        'recent_messages': [{'id': m['id'], 'role': m['role'], 'text': m['text']} for m in
                            [m for m in conversation['messages'] if m['text'] != 'Your message is saved. Working on it…'][-RECENT_MESSAGES:]],
        'memory': {**{k: memory[k] for k in ('summary', 'status', 'notes')},
                   'discussion': discussion_summary(memory),
                   'attempts': {k: v for k, v in memory['attempts'].items()
                                if focus and k.startswith(focus['id'] + ':')}},
        'answer_retrieval_required': any('answer' not in answer for answer in answers),
        'topic_question_budget': {'asked': topic_question_count(memory, focus['id']) if focus else 0,
            'remaining': max(0, MAX_TOPIC_QUESTIONS - topic_question_count(memory, focus['id'])) if focus else 0},
        'limits': {'max_questions_per_topic': MAX_TOPIC_QUESTIONS, 'max_unproductive_attempts_per_target': memory.get('max_target_attempts', MAX_TARGET_ATTEMPTS)}}
    # Never silently truncate a factual answer or pretend an omitted source was reviewed.
    if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_CONTEXT_BYTES:
        raise ValueError('This review context is too large to process safely. Your conversation and evidence are saved.')
    return context

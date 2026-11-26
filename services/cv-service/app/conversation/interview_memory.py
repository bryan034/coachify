"""Persistent navigation state and transient, source-grounded provider context."""
from copy import deepcopy
import json
from typing import get_args
from app.domain.capabilities import effective_items, digest, normalized_name
from app.domain.attachments import source_fingerprint
from app.domain.review_context import clarification_context, review_target_skipped
from app.domain.evidence_ledger import evidence_for
from app.domain.baseline import baseline_estimates, skill_facts
from app.domain.review_policy import effective_policy, map_legacy_counts
from app.domain.errors import Conflict
from app.schemas.conversation import InterviewProgress
from app.schemas.interview_evidence import ReviewField, fact_groups, facts_closed, fact_group_value

MAX_CONTEXT_BYTES = 96 * 1024
MAX_TARGET_ATTEMPTS = 1
MAX_TOPIC_QUESTIONS = 2
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


def review_group(item, policy):
    kind = item.get('kind')
    if policy.get('scope') == 'item' and kind in {'project', 'experience'}:
        return 'item:' + item['id']
    return 'section:' + str(kind or 'other')


def issued_review_question(question):
    return not (question.get('_synthetic_statement') or question.get('question') ==
                'What additional or corrected facts are you stating about this source?')


def durable_review_questions(document):
    """Project issued questions across explicit source reconciliation.

    Follow the explicit item mappings and question provenance; only answered questions transfer.
    """
    cv_id = document.get('_id')
    questions, aliases = {}, {}

    def retain(question, source_cv):
        if not issued_review_question(question):
            return
        identity = (source_cv, question['id'])
        previous = question.get('reconciled_from') or {}
        predecessor = ((previous.get('cv_id'), previous.get('question_id'))
                       if previous.get('cv_id') and previous.get('question_id') else identity)
        origin = aliases.get(predecessor, predecessor)
        aliases[identity] = origin
        questions[origin] = deepcopy(question)

    for entry in document.get('history', []):
        if entry.get('operation') != 'reconcile' or entry.get('action') != 'accept_candidate':
            continue
        candidate = entry.get('candidate') or {}
        source_cv = candidate.get('source_cv_id', cv_id)
        mapping = {choice['item_id']: choice.get('target_item_id') for choice in entry.get('choices', [])}
        for question in entry.get('clarifications', []):
            retain(question, cv_id)
        for question in candidate.get('clarifications', []):
            if source_cv == cv_id or mapping.get(question['item_id']):
                retain(question, source_cv)
        for question in questions.values():
            target = mapping.get(question['item_id'])
            if target:
                question['item_id'] = target

    for question in document.get('clarifications', []):
        retain(question, cv_id)
    return list(questions.values())


def question_groups(question, item_groups, policy):
    item_id = question['item_id']
    if policy.get('scope') == 'item':
        known_group = item_groups.get(item_id)
        if (known_group and known_group.startswith('item:')) or question.get('kind') in {'project', 'work'} or question.get('_interview_section') in {'project', 'experience'}:
            return ['item:' + item_id]
    section = question.get('_interview_section') or {'project': 'project', 'work': 'experience'}.get(question.get('kind'))
    if section:
        return ['section:' + section]
    if item_id in item_groups:
        return [item_groups[item_id]]
    return ['section:education', 'section:skill']


def topic_question_count(memory, item_id):
    group = memory.get('item_groups', {}).get(item_id, item_id)
    return memory.get('group_question_counts', {}).get(group,
        memory.get('question_counts', {}).get(item_id,
            len({q['id'] for q in memory.get('questions', []) if q['item_id'] == item_id})))


def target_availability(item, memory, field, skill_name=None, *, max_attempts=MAX_TARGET_ATTEMPTS):
    """One target-admission policy shared by planner context and validation."""
    if review_target_skipped(item, field, skill_name): return 'declined'
    if topic_question_count(memory, item['id']) >= MAX_TOPIC_QUESTIONS: return 'topic_limit'
    ownership = {'personal_contribution', 'responsibilities'}
    for q in memory.get('intent_history', []):
        if q.get('item_id') != item['id'] or q.get('status') != 'skipped' and q.get('resolution') != 'resolved':
            continue
        for target in q.get('targets', []):
            same_field = target.get('field') == field or {target.get('field'), field} <= ownership
            if same_field and normalized_name(target.get('skill_name') or '') == normalized_name(skill_name or ''):
                return 'closed'
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


def ownership_established(item):
    """Supported personal or shared ownership and at least one concrete task fact for this topic."""
    supported = [f for f in evidence_for(item) if f['status'] == 'supported']
    return (any(f['field'] == 'personal_contribution' and f.get('attribution') in {'personal', 'shared'} for f in supported)
            and any(f['field'] in {'task_scope', 'skill_use', 'responsibilities'} for f in supported)
            and not any(f['field'] in {'personal_contribution', 'responsibilities'} and f['status'] == 'conflicting'
                        for f in evidence_for(item)))


def enough_context(item):
    """Personal ownership and concrete use of every listed skill are known, so further questions are optional."""
    if not ownership_established(item): return False
    claims = item.get('skill_claims') or [{'name': name} for name in item.get('skill_names', [])]
    for claim in claims:
        if claim.get('attribution') in {'team', 'observed', 'denied'}: continue
        facts = skill_facts(item, claim['name'])
        if not any(f['field']=='self_rating' and f['status'] in {'supported','unknown','skipped','not_applicable'} for f in facts): return False
        if any(f['field'] in {'personal_contribution', 'skill_use'} and f['status'] in {'unknown', 'skipped', 'not_applicable'}
               for f in facts): continue
        if not any(f['field'] == 'skill_use' and f['status'] == 'supported' for f in facts): return False
    return True


def topic_ids(items):
    """Include unverified sections and sources with material clarification needs."""
    return [item['id'] for item in items if item.get('validation_issue')
            or clarification_context(item, evidence_for(item))['clarification_targets']]


def reconcile_memory(conversation, document):
    """Rebuild after evidence changes; retain progress only for unchanged sources."""
    old = conversation.get('interview_memory') or {}
    items = [i for i in effective_items(document) if not i['removed']]
    signatures = {i['id']: digest({'source': source_fingerprint(i), 'review': i.get('review_evidence', [])}) for i in items}
    same_generation = old.get('extraction_version') == document['extraction_version']
    estimates = baseline_estimates(items)
    originals = {i['id']: digest({'original': i, 'overlay': document.get('overlays', {}).get(i['id'])}) for i in document.get('original_items', []) if i['id'] in signatures}
    stable_sources = {i for i in originals if same_generation and old.get('input_sources', {}).get(i) == originals[i]}
    coverage = {i: value for i, value in old.get('coverage', {}).items() if i in stable_sources}
    if old.get('status') not in {'reviewed', 'reviewed_with_gaps'}:
        coverage.pop(old.get('focus_item_id'), None)
    attempts = {k: v for k, v in old.get('attempts', {}).items() if any(k.startswith(i + ':') for i in stable_sources)}
    answers = {q['id']: 'reopened' if q.get('reopened') else q['status'] for q in document['clarifications'] if not q.get('reconciliation_required')}
    policy = effective_policy(document.get('review_policy_snapshot') or old.get('review_policy'))
    source_items = {i['id']: i for i in document.get('original_items', [])}
    source_items.update({i['id']: i for i in items})
    item_groups = {i: review_group(item, policy) for i, item in source_items.items()}
    question_counts, group_question_counts, discussed_topics, intent_history = {}, {}, set(), []
    for q in durable_review_questions(document):
        question_counts[q['item_id']] = question_counts.get(q['item_id'], 0) + 1
        for group in question_groups(q, item_groups, policy):
            group_question_counts[group] = group_question_counts.get(group, 0) + 1
        intent_history.append({'item_id': q['item_id'], 'status': q['status'],
                               'targets': q.get('_interview_targets', []), 'resolution': q.get('resolution'), 'question': q.get('question', '')})
        if q['status'] in {'answered', 'skipped'}: discussed_topics.add(q['item_id'])
    for source in (map_legacy_counts(document, document.get('review_legacy_counts')),
                   map_legacy_counts(document, old.get('question_counts'))):
        for item_id, count in source.items():
            if item_id in signatures and type(count) is int and count >= 0:
                if count > question_counts.get(item_id, 0): question_counts[item_id] = min(count, MAX_TOPIC_QUESTIONS)
    reconstructed = {}
    for item_id, count in question_counts.items():
        group = item_groups.get(item_id)
        if group: reconstructed[group] = reconstructed.get(group, 0) + count
    for group, count in reconstructed.items():
        group_question_counts[group] = max(group_question_counts.get(group, 0), count)
    needed = set(topic_ids(items))
    retained_topics = [i for i in old.get('topic_ids', []) if i in signatures
                       and (i in needed or i in coverage or i in discussed_topics or topic_discussed(old, i))]
    history = [{**q, 'answer_status': answers.get(q['id'], 'unanswered')} for q in old.get('questions', []) if q.get('item_id') in signatures and q['id'] in answers][-120:]
    previous_policy = old.get('previous_review_policy') or (old.get('review_policy') if old.get('review_policy') != policy else None)
    result = {'schema_version': 1, 'extraction_version': document['extraction_version'],
        'evidence_version': document['effective_version'], 'sources': signatures, 'input_sources': originals,
        'focus_item_id': old.get('focus_item_id') if old.get('focus_item_id') in signatures
                         and old.get('status') not in {'reviewed', 'reviewed_with_gaps'} else None,
        'status': old.get('status', 'reviewing') if old.get('sources') == signatures else 'reviewing',
        'topic_ids': list(dict.fromkeys((retained_topics if same_generation else []) + topic_ids(items))),
        'deferred_topics': {i: value for i, value in old.get('deferred_topics', {}).items() if i in stable_sources},
        'coverage': coverage, 'estimates': estimates, 'attempts': attempts, 'question_counts': question_counts,
        'review_policy': policy, 'item_groups': item_groups, 'group_question_counts': group_question_counts,
        'intent_history': intent_history, 'no_progress': old.get('no_progress', {}),
        'discussed_topic_ids': sorted(discussed_topics),
        'questions': history,
        'notes': old.get('notes', [])[-24:],
        'summary': [{'item_id': i, 'status': value['status']} for i, value in coverage.items()]}
    if previous_policy: result['previous_review_policy'] = previous_policy
    return result


def progress(memory, document):
    if not memory: return None
    sources = [i for i in effective_items(document) if not i['removed'] and i['id'] in memory.get('topic_ids', [])]
    return InterviewProgress(status=memory['status'],
        reviewed_items=sum(i['id'] in memory['coverage'] for i in sources), total_items=len(sources),
        topics=[{'id': i['id'], 'title': i['title'],
                 'status': memory['coverage'][i['id']]['status'] if i['id'] in memory['coverage'] else
                           'current' if i['id'] == memory.get('focus_item_id') else 'pending',
                 'validation': 'unverified' if i.get('validation_issue') else None} for i in sources],
        estimates=memory.get('estimates', [])).model_dump(mode='json')


def build_context(conversation, document, memory, *, focus_id=None, recall_ids=()):
    """Transient provider input. Older exact answers remain addressable by IDs."""
    items = [i for i in effective_items(document) if not i['removed']]
    focus_id = focus_id or memory.get('focus_item_id')
    focus = next((i for i in items if i['id'] == focus_id), None)
    if focus is None:
        focus = next((i for i in items if i['id'] in memory.get('topic_ids', []) and i['id'] not in memory['coverage']
                      and topic_question_count(memory, i['id']) < MAX_TOPIC_QUESTIONS), None)
    if focus is None and items: focus = items[0]
    index = {}
    focused_id = focus['id'] if focus else None
    scoped_items = [item for item in items if item['id'] in (focused_id, memory.get('focus_item_id'))]
    scoped_ids = {item['id'] for item in scoped_items}
    for item in scoped_items:
        for fact in evidence_for(item):
            ref = 'fact:' + digest({'item': item['id'], 'fact': fact})[:24]
            index[ref] = {'item_id': item['id'], **fact}
    answers = [{'id': 'answer:' + q['id'],
                **({'item_id': q['item_id']} if q['item_id'] != focused_id else {}),
                'resolution': q.get('resolution'), 'interpretation_status': q.get('interpretation_status'),
                **({'question': q['question'], 'answer': q.get('answer')} if 'answer:' + q['id'] in recall_ids
                   else {'targets': q.get('_interview_targets', []),
                         'uncertainty': q.get('uncertainty'), 'status': q.get('status')})}
               for q in document['clarifications'] if q['item_id'] in scoped_ids
               and not q.get('reconciliation_required')]
    active = conversation.get('active_question')
    active_record = next((q for q in document['clarifications'] if active and q['id'] == active['id']), None)
    context = {'goal': 'Use the CV as evidence and ask specific questions only where a useful detail remains uncertain. Ask at most two questions per review group including the opening question; finish earlier when enough is known. Do not infer another source’s facts from an answer.',
        'cv_version': document['version'], 'evidence_version': document['effective_version'],
        'active_question': {**active, 'uncertainty': active_record['uncertainty']} if active and active_record else active,
        'review_topic_ids': memory.get('topic_ids', []),
        'sources': [{'id': i['id'], 'kind': i['kind'], 'title': i['title'],
            'questions_asked': topic_question_count(memory, i['id']),
            'questions_remaining': max(0, MAX_TOPIC_QUESTIONS - topic_question_count(memory, i['id'])),
            'review_dispositions': i.get('_review_skips', []),
            'listed_skills': [c['name'] for c in i.get('skill_claims', [])],
            'enough_context': enough_context(i),
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
    if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_CONTEXT_BYTES:
        raise ValueError('This review context is too large to process safely. Your conversation and evidence are saved.')
    return context


def migrate_snapshot(document, previous, legacy_counts=None):
    """Upgrade a snapshot in an existing versioned write without changing receipts."""
    stored = document.get('review_policy_snapshot')
    if stored is not None and stored != previous:
        raise Conflict('Your review policy changed. Continue with the latest review.')
    current = effective_policy(previous)
    if previous and previous != current:
        ids = sorted(q['id'] for q in durable_review_questions(document))
        document.setdefault('review_policy_migrations', []).append({
            'from': deepcopy(previous), 'to': deepcopy(current),
            'question_count': len(ids), 'receipt_basis': digest(ids)})
    if legacy_counts:
        known = {item['id'] for item in document.get('original_items', [])}
        counts = document.setdefault('review_legacy_counts', {})
        for item_id, count in map_legacy_counts(document, legacy_counts).items():
            if item_id in known and type(count) is int and count > 0:
                existing = counts.get(item_id, 0)
                counts[item_id] = max(existing if type(existing) is int and existing >= 0 else 0, min(count, 2))
    document['review_policy_snapshot'] = current
    return current

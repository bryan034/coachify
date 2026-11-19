"""Agent-led CV interview orchestration with durable, retryable stages.

The harness commits validated evidence before asking the agent for its next
interview action.
"""
import logging
import re
from copy import deepcopy
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from app.domain.capabilities import effective_items, digest, normalized_name, validate_review_interpretation
from app.domain.errors import Conflict, CvError
from app.domain.error_codes import CodedError, error_code_of
from app.domain.baseline import baseline_estimates
from app.domain.review_context import clarification_context
from app.domain.review_policy import effective_policy
from uuid import uuid5, NAMESPACE_URL
from app.domain.service import now
from app.domain.skill_levels import BATCH, pending_sources, rating_failure, rating_ready, validate_level_review
from app.schemas.cv import Mutation, AnswerMutation
from app.clarification.service import answer, group_counts
from app.conversation.actions import LEASE_SECONDS, key, action_in, action_message
from app.schemas.interview import InterviewTurn
from app.schemas.interview_evidence import fact_groups, fact_group_value
from app.conversation.interview_memory import (build_context, reconcile_memory, progress, evidence_for, target_key,
    topic_question_count, topic_discussed, topic_ids, enough_context, ownership_established, question_options, durable_review_questions, migrate_snapshot, MAX_TOPIC_QUESTIONS, MAX_TARGET_ATTEMPTS)
from app.conversation.presentation import review_reply, safe_side_answer, unverified_notice
from app.conversation.interview_policy import validate_decision, DecisionRejected

logger = logging.getLogger(__name__)

TOPIC_COMMANDS = {'skip_topic', 'skip_remaining', 'review_topic'}
MAX_PLAN_CALLS = 3
MAX_CONTEXT_CALLS = 3
# Whole-message refusals only: "I skipped the tests" or "skip, but I used Python" go to the model.
SKIP_REQUEST = re.compile(r"(please\s+)?(let'?s\s+)?(skip|pass|(i\s+)?(don'?t|do\s+not)\s+(want|wish)\s+to\s+answer|(i'?d\s+)?(rather|prefer)\s+not\s+(to\s+)?(answer|say))"
                          r"(\s+(this|that|it))?(\s+(one|question))?(\s+please)?", re.I)


def is_skip_request(text):
    return bool(SKIP_REQUEST.fullmatch(text.replace('’', "'").strip(' .!,\n\t')))


def is_side_question(text):
    """Identify an explicit user question without treating a short answer as one."""
    text = text.strip()
    return bool('?' in text or '？' in text or re.match(
        r"^(?:why|what|how|when|where|who|can|could|would|is|are|do|does|please explain)\b", text, re.I))


class InterviewHarness:
    def __init__(self, service):
        self.service = service
        self.lead = ''  # Fixed text placed before the next reply, e.g. confirming a skipped topic.
        self.requested_topic = None  # A topic the user asked to review; the next question must be about it.

    async def call(self, app, account, conversation_id, route_id, token, payload):
        service = self.service
        await service.authenticate(app, account)
        def renew(current):
            action = action_in(current, route_id)
            service.check_lease(action, token)
            action['_lease_until'] = now() + LEASE_SECONDS
        await run_in_threadpool(service.update, account['id'], conversation_id, renew)
        result, metadata = await run_in_threadpool(service.route, account['id'], payload)
        await service.authenticate(app, account)
        service.check_lease(action_in(service.get(account['id'], conversation_id), route_id), token)
        return result, metadata

    async def process(self, app, account, conversation, route, token):
        service, owner, identifier = self.service, account['id'], conversation['_id']
        document = service.cv.get(owner, conversation['cv_id'])
        if document['operation']['status'] != 'ready' or document.get('candidate'):
            raise CvError('Finish CV processing or source reconciliation before reviewing. Your conversation is saved.', 409)
        prior = conversation.get('interview_memory') or {}
        saved_policy = (document.get('review_policy_snapshot') or next(
            (q['_interview_policy'] for q in document['clarifications'] if q.get('_interview_policy')), None)
            or prior.get('review_policy'))
        policy = effective_policy(saved_policy or account.get('cv_review_policy'))
        retained = route.get('_interview_plan')
        # Finish an already-admitted v1 question with its original receipt before upgrading.
        if saved_policy and saved_policy != policy and not retained:
            def migrate(current):
                migrate_snapshot(current, saved_policy, prior.get('question_counts', {}))
            await run_in_threadpool(service.cv.mutate, owner, document['_id'],
                Mutation(expected_version=document['version'], mutation_id=key(route['id'] + ':review-policy')),
                'review-policy-migration', migrate)
            document = service.cv.get(owner, document['_id'])
        previous_policy = (saved_policy if saved_policy and saved_policy.get('scope') == 'section'
                           else prior.get('previous_review_policy') or prior.get('review_policy') or saved_policy)
        conversation = {**conversation, 'interview_memory': {**prior, 'review_policy': policy}}
        memory = reconcile_memory(conversation, document)
        memory.pop('previous_review_policy', None)
        if previous_policy and previous_policy.get('scope') == 'section' and not retained:
            # Reopen only material job/project gaps the old shared section allowance exhausted.
            _, previous_counts = group_counts(document, previous_policy)
            reopened = False
            for item in effective_items(document):
                item_id = item['id']
                if (item.get('removed') or item['kind'] not in {'project', 'experience'}
                        or item_id in memory.get('deferred_topics', {})
                        or memory['coverage'].get(item_id, {}).get('status') != 'reviewed_with_gaps'
                        or previous_counts.get('section:' + item['kind'], 0) < MAX_TOPIC_QUESTIONS
                        or topic_question_count(memory, item_id) >= MAX_TOPIC_QUESTIONS):
                    continue
                if any(option['open_fields'] for option in question_options(item, memory)):
                    memory['coverage'].pop(item_id)
                    reopened = True
            if reopened and memory['status'] in {'reviewed', 'reviewed_with_gaps'}:
                memory['status'] = 'reviewing'
            active = conversation.get('active_question')
            if active and memory.get('item_groups', {}).get(active['item_id'], '').startswith('item:'):
                item_questions = [q for q in durable_review_questions(document) if q['item_id'] == active['item_id']]
                ordinal = next((index for index, q in enumerate(item_questions, 1) if q['id'] == active['id']), None)
                if ordinal and ordinal <= MAX_TOPIC_QUESTIONS:
                    conversation = {**conversation, 'active_question': {**active, 'number': ordinal, 'limit': MAX_TOPIC_QUESTIONS}}
        memory['max_target_attempts'] = service.cv.settings.interview_max_target_attempts
        if retained:
            question = retained['question']
            receipt = key(route['id'] + ':interview-question')
            if document['extraction_version'] != retained['memory']['extraction_version']:
                raise Conflict('Your source changed while saving the question. Continue from the latest evidence.')
            if (document.get('review_policy_snapshot') == policy
                    and (retained['memory'].get('review_policy') != policy
                         or document['version'] != retained['expected_version'])):
                existing = next((q for q in document['clarifications'] if q['id'] == question['id']), None)
                if existing and (existing['item_id'] != question['item_id'] or existing['question'] != question['question']):
                    raise Conflict('The saved question changed. Continue from the latest review.')
                source_available = any(item['id'] == question['item_id'] and not item.get('removed')
                                       for item in effective_items(document))
                if (existing and existing['status'] == 'unanswered' and not existing.get('reconciliation_required')
                        and source_available):
                    # Reuse the receipt of a CV write whose conversation reply was interrupted.
                    recovered = deepcopy(retained['memory'])
                    recovered['review_policy'] = policy
                    recovered = reconcile_memory({**conversation, 'interview_memory': recovered}, document)
                    active = deepcopy(retained['active'])
                    item_questions = [q for q in durable_review_questions(document) if q['item_id'] == question['item_id']]
                    ordinal = next((index for index, q in enumerate(item_questions, 1) if q['id'] == question['id']), None)
                    if ordinal and ordinal <= MAX_TOPIC_QUESTIONS: active.update(number=ordinal, limit=MAX_TOPIC_QUESTIONS)
                    reply = retained['reply']
                    if document['effective_version'] != retained['memory']['evidence_version']:
                        reply = 'Your saved evidence changed; you can still answer or skip this saved question. ' + reply
                    return await self.publish(account, identifier, route['id'], token, recovered,
                                              reply, active, retained['targets'])
                if existing:
                    # Another flow answered or skipped the issued question: acknowledge it without publishing.
                    recovered = deepcopy(retained['memory'])
                    recovered['review_policy'] = policy
                    recovered['focus_item_id'] = None
                    recovered = reconcile_memory({**conversation, 'interview_memory': recovered}, document)
                    return await self.publish(account, identifier, route['id'], token, recovered,
                        ('That question was already answered or skipped. Your saved review is up to date; continue when ready.'
                         if existing['status'] in {'answered', 'skipped'} else
                         'Your source changed after that question was saved. Your review is retained; continue with the latest evidence.'), None, [])
                # Drop an unissued proposal made stale by another operation and plan against the latest state.
                def clear_stale(current):
                    action = action_in(current, route['id'])
                    service.check_lease(action, token)
                    action.pop('_interview_plan', None)
                await run_in_threadpool(service.update, owner, identifier, clear_stale)
                return await self.plan(app, account, conversation, document, route, token, memory)
            def add(current):
                saved_policy = current.setdefault('review_policy_snapshot', retained['memory']['review_policy'])
                if saved_policy != retained['memory']['review_policy']:
                    raise Conflict('Your review policy changed. Continue with the current review.')
                if not any(q['id'] == question['id'] for q in current['clarifications']):
                    if len(current['clarifications']) >= 800: raise CvError('This CV has reached its question history limit.', 409)
                    current['clarifications'].append(question)
            await run_in_threadpool(service.cv.mutate, owner, document['_id'],
                Mutation(expected_version=retained['expected_version'], mutation_id=receipt), 'interview-question', add)
            latest = service.cv.get(owner, document['_id'])
            if latest['version'] != retained['expected_version'] + 1:
                raise Conflict('Your evidence changed after the question was prepared. Continue with the latest evidence.')
            return await self.publish(account, identifier, route['id'], token, retained['memory'],
                retained['reply'], retained['active'], retained['targets'])
        command = route.get('_command')
        if command in TOPIC_COMMANDS:
            return await self.topic_command(app, account, conversation, document, route, token, memory, command)
        if not command and conversation.get('active_question') and is_skip_request(route.get('_text') or ''):
            command = 'skip'
            route = {**route, '_command': command}
        if command == 'finish':
            return await self.pause(account, identifier, route['id'], token, memory,
                'We can stop here. Your answers are saved; remaining details stay uncertain.')
        if command == 'continue' and conversation.get('active_question') and memory.get('no_progress', {}).get(conversation['active_question']['id']):
            command = 'skip'
            route = {**route, '_command': command}
        if command in {'review', 'continue'} and conversation.get('active_question'):
            return await self.publish(account, identifier, route['id'], token, memory,
                'Your current question is still open. You can answer it or skip.',
                conversation['active_question'], conversation.get('interview_targets', []))
        if command == 'skip':
            active = conversation.get('active_question')
            if active:
                document = await self.skip_active(account, conversation, document, route, token, memory)
                conversation = {**conversation, 'active_question': None}
                # Nothing left to ask here: close the topic now.
                source = next((i for i in effective_items(document) if i['id'] == active['item_id'] and not i['removed']), None)
                if source and not clarification_context(source, evidence_for(source))['clarification_targets']:
                    memory['coverage'][source['id']] = {'item_id': source['id'], 'status': 'reviewed_with_gaps', 'evidence_refs': []}
                    memory['focus_item_id'] = None
            else:
                failed = next((a for m in reversed(conversation['messages']) for a in reversed(m.get('actions', []))
                    if a['kind'] == 'route' and a['status'] == 'failed'
                    and error_code_of(a) == 'no_valid_next_step'), None)
                deferred = route.get('_interview_defer')
                source_id = (deferred or {}).get('item_id') or memory.get('focus_item_id')
                if deferred and (deferred.get('extraction_version') != document['extraction_version']
                        or deferred.get('source_fingerprint') != memory['input_sources'].get(source_id)):
                    raise Conflict('This experience changed after you skipped it. Review the latest source before skipping again.')
                if source_id in memory['sources'] and (deferred or failed):
                    memory.setdefault('deferred_topics', {})[source_id] = {
                        'reason': 'user_skip', 'remaining_ownership': 'uncertain'}
                    memory['coverage'][source_id] = {'item_id': source_id, 'status': 'deferred', 'evidence_refs': []}
                    memory['focus_item_id'] = None
                    def save_defer(current):
                        action = action_in(current, route['id'])
                        service.check_lease(action, token)
                        latest = service.cv.get(owner, document['_id'])
                        if latest['version'] != document['version']:
                            raise Conflict('This experience changed while skipping. Review the latest source and try again.')
                        action['_interview_defer'] = {'item_id': source_id, 'extraction_version': document['extraction_version'],
                            'source_fingerprint': memory['input_sources'].get(source_id)}
                        for message in current['messages']:
                            for previous in message.get('actions', []):
                                interpretations = (previous.get('_interview_evaluation') or {}).get('result', {}).get('interpretations', [])
                                same_source = previous.get('_item_id') == source_id or any(i['item_id'] == source_id for i in interpretations)
                                if (previous['kind'] == 'route' and previous['status'] in {'failed', 'pending'}
                                        and (error_code_of(previous) == 'no_valid_next_step'
                                             or (failed and previous['id'] == failed['id']))
                                        and (same_source or (failed and previous['id'] == failed['id']))):
                                    previous.update(status='cancelled', error=None,
                                        summary='Skipped remaining questions; saved answers are retained.', _skipped_by=route['id'],
                                        _token=None, _lease_until=0)
                                    previous.pop('_resume_requested', None)
                        normalized = reconcile_memory({**current, 'interview_memory': memory}, document)
                        current.update(interview_memory=normalized, interview_progress=progress(normalized, document))
                    conversation = await run_in_threadpool(service.update, owner, identifier, save_defer)
                    memory = reconcile_memory(conversation, document)
        elif command not in {'review', 'continue'}:
            evaluated = route.get('_interview_evaluation')
            if evaluated is None:
                context = build_context(conversation, document, memory)
                for attempt in range(2):
                    try:
                        result, metadata = await self.call(app, account, identifier, route['id'], token,
                            {'task': 'cv_interview_interpret', 'message': route['_text'], 'message_id': route.get('_message_id'),
                             'schema_retry': bool(attempt), **context})
                        result = InterviewTurn.model_validate(result)
                        if result.topic_relevant:
                            items_by_id = {i['id']: i for i in effective_items(document) if not i['removed']}
                            for interpretation in result.interpretations:
                                if interpretation.item_id not in items_by_id:
                                    raise ValueError('Interpretation refers to an unavailable source.')
                                validate_review_interpretation(
                                    {**interpretation.model_dump(mode='json'), 'answer_revision': 1},
                                    items_by_id[interpretation.item_id], {'answer_revision': 1})
                        break
                    except ValidationError:
                        if attempt:
                            active = conversation.get('active_question')
                            return await self.no_progress(app, account, conversation, document, route, token, memory, active)
                evaluated = {'result': result.model_dump(mode='json'), 'metadata': metadata}
                def remember(current):
                    service.check_lease(action_in(current, route['id']), token)
                    action_in(current, route['id'])['_interview_evaluation'] = evaluated
                await run_in_threadpool(service.update, owner, identifier, remember)
            result = InterviewTurn.model_validate(evaluated['result'])
            if result.intent == 'side_question' and (result.topic_relevant or is_side_question(route['_text'])):
                # Side replies do not create an evidence-question receipt.
                text = route['_text'].casefold()
                reply = safe_side_answer(result.reply) if result.topic_relevant else None
                if not reply:
                    if re.search(r'\b(why|purpose|reason)\b', text):
                        reply = 'These questions help clarify what you personally did and what remains uncertain.'
                    elif re.search(r'\b(skip|pass|answer|unsure)\b', text):
                        reply = 'You can skip a question or say you are unsure; unknown details stay uncertain.'
                    else:
                        reply = 'I can explain the review process here, but cannot answer that question from the saved CV.'
                if conversation.get('active_question'):
                    reply += ' Your current question is still open; you can answer it or skip.'
                return await self.publish(account, identifier, route['id'], token, memory,
                    reply, conversation.get('active_question'), conversation.get('interview_targets', []))
            if not result.topic_relevant:
                active = conversation.get('active_question')
                return await self.no_progress(app, account, conversation, document, route, token, memory, active)
            for note in result.memory_notes:
                if note.source_id != 'answer' or note.quote not in route['_text']:
                    continue
                entry = {'source_id': route.get('_message_id', route['_turn_id']), 'quote': note.quote}
                if entry not in memory['notes']: memory['notes'].append(entry)
            memory['notes'] = memory['notes'][-24:]
            if result.intent == 'stop':
                return await self.pause(account, identifier, route['id'], token, memory,
                    'We can stop here. Your answers are saved; remaining details stay uncertain.')
            if result.intent == 'skip' or (result.actions and all(a.kind == 'skip' for a in result.actions)):
                return await self.process(app, account, conversation, {**route, '_command': 'skip'}, token)
            payload = service.routing_payload(owner, conversation, route)
            items = {i['id']: i for i in effective_items(document) if not i['removed']}
            questions = {q['id']: q for q in payload['questions']}
            interpretations = {i.item_id: i.model_dump(mode='json') for i in result.interpretations}
            stored = service.get(owner, identifier)
            saved_route = action_in(stored, route['id'])
            if '_interview_action_ids' not in saved_route:
                actions = []
                for index, proposal in enumerate(result.actions):
                    if proposal.excerpt not in route['_text']:
                        proposal.excerpt = route['_text']  # Anchor the action to the saved answer.
                    if proposal.item_id and proposal.item_id not in items: raise ValueError('The interview referred to another source.')
                    if any(i not in items for i in proposal.candidate_item_ids): raise ValueError('Invalid source choice.')
                    if proposal.question_id and (proposal.question_id not in questions or
                        proposal.item_id and questions[proposal.question_id]['item_id'] != proposal.item_id):
                        raise ValueError('The interview referred to another question.')
                    action = service.proposal(conversation, route, proposal, index, items, questions)
                    if proposal.kind == 'clarify' and action['status'] != 'needs_source':
                        interpretation = interpretations.get(action.get('item_id'))
                        if interpretation is None: raise ValueError('A factual answer needs a matching source interpretation.')
                        action['_prepared_interpretation'] = (interpretation, evaluated['metadata'])
                    elif proposal.kind == 'correct' and not proposal.fields and action.get('item_id') in interpretations:
                        action['_prepared_interpretation'] = (interpretations[action['item_id']], evaluated['metadata'])
                    actions.append(action)
                await service.check_snapshot(app, account, conversation, route['_snapshot'])
                def stage(current):
                    saved = action_in(current, route['id'])
                    service.check_lease(saved, token)
                    if '_interview_action_ids' in saved: return
                    saved['_interview_action_ids'] = [a['id'] for a in actions]
                    action_message(current, route['id'])['actions'].extend(actions)
                stored = await run_in_threadpool(service.update, owner, identifier, stage)
            ids = action_in(stored, route['id'])['_interview_action_ids']
            for action_id in ids:
                current = action_in(service.get(owner, identifier), action_id)
                if current['status'] == 'pending': await service.execute(app, account, identifier, action_id)
            latest = service.get(owner, identifier)
            remaining = [action_in(latest, a) for a in ids if action_in(latest, a)['status'] != 'saved']
            if remaining:
                notes = memory['notes']
                memory = reconcile_memory(latest, service.cv.get(owner, latest['cv_id']))
                memory['notes'] = notes
                def waiting(current):
                    action_in(current, route['id'])['_interview_waiting'] = True
                await run_in_threadpool(service.update, owner, identifier, waiting)
                failed = any(a['status'] in {'failed', 'stale'} for a in remaining)
                reply = 'Your answer is saved. We couldn’t finish processing it yet.' if failed else 'Your answer is saved and is still being processed.'
                return await self.publish(account, identifier, route['id'], token, memory,
                    reply, latest.get('active_question'), latest.get('interview_targets', []), status_only=failed)
            conversation = latest
            document = service.cv.get(owner, conversation['cv_id'])
            notes = memory['notes']
            memory = reconcile_memory(conversation, document)
            memory['notes'] = notes
        if any(q.get('interpretation_status') in {'pending', 'failed'} and not q.get('reconciliation_required')
               for q in document['clarifications']):
            raise ValueError('Your saved evidence still needs interpretation. Retry that action before continuing.')
        return await self.plan(app, account, conversation, document, route, token, memory)

    async def skip_active(self, account, conversation, document, route, token, memory):
        """Record the active question as skipped; the same receipt makes a retry idempotent."""
        service, owner, identifier = self.service, account['id'], conversation['_id']
        active = conversation['active_question']
        operation = route.get('_interview_skip') or {'expected_version': document['version'],
            'mutation_id': key(route['id'] + ':interview-skip'), 'action': 'skip'}
        def remember_skip(current):
            service.check_lease(action_in(current, route['id']), token)
            action_in(current, route['id'])['_interview_skip'] = operation
        await run_in_threadpool(service.update, owner, identifier, remember_skip)
        document = await run_in_threadpool(answer, service.cv, owner, document['_id'], active['id'], AnswerMutation.model_validate(operation))
        memory['attempts'].update({target_key(active['item_id'], t['field'], t.get('skill_name')):
            {'signature': 'declined', 'count': MAX_TARGET_ATTEMPTS, 'declined': True}
            for t in conversation.get('interview_targets', [])})
        memory['questions'] = [{**q, 'skipped': True} if q['id'] == active['id'] else q for q in memory['questions']]
        return document

    async def topic_command(self, app, account, conversation, document, route, token, memory, command):
        """Skip one topic, skip every uncovered topic, or reopen a topic the user skipped.

        Skipped topics keep their CV evidence and saved answers; remaining details stay uncertain.
        """
        items = {i['id']: i for i in effective_items(document) if not i['removed']}
        target = route.get('_item_id')
        uncovered = [i for i in memory.get('topic_ids', []) if i in items and i not in memory['coverage']]
        if command == 'review_topic':
            if (target not in memory.get('deferred_topics', {})
                    or memory['coverage'].get(target, {}).get('status') != 'deferred'):
                raise Conflict('Only a skipped topic can be reviewed again.')
            # Check before mutating.
            if not any(option['open_fields'] for option in question_options(items[target], memory)):
                raise Conflict('elo has no questions left for this topic. Your CV is used as written for it.')
            document = await run_in_threadpool(self.service.cv.reopen_topic_skips, account['id'], document['_id'], target,
                key(route['id'] + ':reopen:' + target))
            items = {i['id']: i for i in effective_items(document) if not i['removed']}
            memory['attempts'] = {k: v for k, v in memory.get('attempts', {}).items() if not k.startswith(target + ':')}
            memory['questions'] = [{**q, 'skipped': False} if q['item_id'] == target else q for q in memory.get('questions', [])]
            if not any(option['open_fields'] for option in question_options(items[target], memory)):
                raise Conflict('elo has no questions left for this topic. Your CV is used as written for it.')
            memory['deferred_topics'].pop(target)
            memory['coverage'].pop(target)
            memory.update(status='reviewing', focus_item_id=target)
            self.requested_topic = target
            active = conversation.get('active_question')
            if active and active['item_id'] != target:
                document = await self.skip_active(account, conversation, document, route, token, memory)
                conversation = {**conversation, 'active_question': None}
            return await self.plan(app, account, conversation, document, route, token, memory)
        if command == 'skip_topic' and target not in uncovered:
            raise Conflict('This topic is already covered. Refresh to see the latest topics.')
        skipped = [target] if command == 'skip_topic' else uncovered
        if not skipped: raise Conflict('No topics are left to skip.')
        active = conversation.get('active_question')
        if active and active['item_id'] in skipped:
            document = await self.skip_active(account, conversation, document, route, token, memory)
            conversation, active = {**conversation, 'active_question': None}, None
        for item_id in skipped:
            memory.setdefault('deferred_topics', {})[item_id] = {'reason': 'user_skip', 'remaining_ownership': 'uncertain'}
            memory['coverage'][item_id] = {'item_id': item_id, 'status': 'deferred', 'evidence_refs': []}
        if memory.get('focus_item_id') in skipped: memory['focus_item_id'] = None
        self.lead = (f"Skipped {items[target]['title']}. I’ll use your CV as written for it. " if command == 'skip_topic'
                     else 'Skipped the remaining topics. I’ll use your CV as written for them. ')
        if active:
            # Skipping another topic leaves the current question in place.
            memory['focus_item_id'] = active['item_id']
            return await self.publish(account, conversation['_id'], route['id'], token, memory,
                f"Back to {active['title']}: {active['question']}", active, conversation.get('interview_targets', []))
        return await self.plan(app, account, conversation, document, route, token, memory)

    def close_finished_topics(self, memory, items):
        """End a discussed topic as soon as nothing material is left to ask, before its three-question limit."""
        closed = []
        for item in items:
            if item['id'] not in memory.get('topic_ids', []) or item['id'] in memory['coverage']: continue
            if not topic_discussed(memory, item['id']): continue
            used_budget = topic_question_count(memory, item['id']) >= MAX_TOPIC_QUESTIONS
            settled = not any(option['open_fields'] for option in question_options(item, memory))
            if settled or used_budget or enough_context(item):
                # A topic that used all its questions closes with gaps; an early close is reviewed only with proven ownership.
                status = 'reviewed' if not used_budget and ownership_established(item) else 'reviewed_with_gaps'
                memory['coverage'][item['id']] = {'item_id': item['id'], 'status': status, 'evidence_refs': []}
                closed.append(item['title'])
        # Focus stays on a just-closed topic so the planner can still cite its evidence when moving on.
        return closed

    async def plan(self, app, account, conversation, document, route, token, memory):
        memory['max_target_attempts'] = self.service.cv.settings.interview_max_target_attempts
        focus_id, feedback, recall_ids = None, [], []
        if not memory.get('topic_ids'):
            memory['status'] = 'reviewed'
            return await self.publish(account, conversation['_id'], route['id'], token, memory,
                'Your review is complete. There are no additional experience topics to clarify.', None, [])
        current_items = [item for item in effective_items(document) if not item['removed']]
        just_completed = self.close_finished_topics(memory, current_items)
        needed = set(topic_ids(current_items))
        available_topics = {item['id'] for item in current_items if topic_question_count(memory, item['id']) < MAX_TOPIC_QUESTIONS}
        eligible = [item for item in current_items
                    if item['id'] in needed and item['id'] in available_topics and item['id'] not in memory['coverage']]
        if not eligible:
            for item_id in memory['topic_ids']:
                memory['coverage'].setdefault(item_id, {'item_id': item_id, 'status': 'reviewed_with_gaps', 'evidence_refs': []})
            memory['status'] = 'reviewed_with_gaps' if any(v['status'] != 'reviewed' for v in memory['coverage'].values()) else 'reviewed'
            memory['focus_item_id'] = None
            return await self.publish(account, conversation['_id'], route['id'], token, memory,
                'Your baseline skill review is complete. Each project skill has an evidence-based estimate; details that could not be established remain unknown.', None, [])
        # Offer the next viable topic when the current one has no remaining material question.
        current_focus = next((item for item in eligible if item['id'] == memory.get('focus_item_id')), None)
        if not current_focus or not any(option['open_fields'] for option in question_options(current_focus, memory)):
            focus_id = next((item['id'] for item in eligible
                             if any(option['open_fields'] for option in question_options(item, memory))), None)
        if self.requested_topic: focus_id = self.requested_topic
        decision = None
        diagnostics = []

        async def record(code, action):
            safe_action = action if isinstance(action, str) and action in {'ask', 'finish', 'pause', 'answer', 'recall'} else 'invalid'
            diagnostics.append({'reason': code, 'action': safe_action})
            def save(current):
                stored = action_in(current, route['id'])
                self.service.check_lease(stored, token)
                stored['_interview_planning'] = diagnostics[-6:]
            await run_in_threadpool(self.service.update, account['id'], conversation['_id'], save)
            logger.warning('CV interview planning event reason=%s action=%s attempt=%s', code, safe_action, len(diagnostics))

        invalid_calls = context_calls = 0
        for _ in range(MAX_PLAN_CALLS + MAX_CONTEXT_CALLS):
            context = build_context(conversation, document, memory, focus_id=focus_id, recall_ids=recall_ids)
            if just_completed: context['just_completed_topics'] = just_completed
            try:
                result, _ = await self.call(app, account, conversation['_id'], route['id'], token,
                    {'task': 'cv_interview_plan', 'validation_feedback': feedback, **context})
            except ValidationError:
                await record('invalid_schema', 'invalid')
                feedback = ['Return a valid InterviewDecision matching the schema. Use only ask, finish, pause or recall; omit optional estimates if uncertain.']
                invalid_calls += 1
                if invalid_calls >= MAX_PLAN_CALLS: break
                continue
            raw = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
            if isinstance(raw.get('reply'), str):
                raw = {**raw, 'reply': review_reply(raw['reply'])}
            if isinstance(raw.get('estimates'), list):
                raw = {**raw, 'estimates': [{**estimate, 'explanation': review_reply(estimate['explanation'])}
                    if isinstance(estimate, dict) and isinstance(estimate.get('explanation'), str) else estimate
                    for estimate in raw['estimates']]}
            if raw.get('action') == 'answer':
                await record('answer_instead_of_next_step', 'answer')
                feedback = ['After saving an answer, ask a follow-up or move to the next topic; finish when all review topics are covered.']
                invalid_calls += 1
                if invalid_calls >= MAX_PLAN_CALLS: break
                continue
            if raw.get('action') == 'recall':
                available = {a['id'] for a in context['source_answers']}
                if not raw.get('recall_ids') or not set(raw['recall_ids']) <= available:
                    await record('recall_unavailable', 'recall')
                    feedback = ['Choose only available source answer IDs.']
                else:
                    await record('recall_answers', 'recall')
                    recall_ids = raw['recall_ids']
                    feedback = ['Requested answers are included. Choose the next interview action.']
                context_calls += 1
                if context_calls > MAX_CONTEXT_CALLS: break
                continue
            source_id = raw.get('item_id')
            if self.requested_topic and raw.get('action') == 'ask' and source_id != self.requested_topic:
                await record('question_requested_topic', 'ask')
                feedback = ['The person asked to review the focused topic. Ask about it now.']
                invalid_calls += 1
                if invalid_calls >= MAX_PLAN_CALLS: break
                continue
            # Hydrate another chosen experience before validating a question.
            if (raw.get('action') == 'ask' and isinstance(source_id, str) and source_id in available_topics
                    and (context.get('focused_source') or {}).get('id') != source_id):
                await record('hydrate_source', 'ask')
                focus_id = source_id
                feedback = [*feedback, 'Your selected experience is now hydrated. Reconsider the question against its known evidence.']
                context_calls += 1
                if context_calls > MAX_CONTEXT_CALLS: break
                continue
            try:
                decision, coverage = validate_decision(raw, context, memory, max_attempts=self.service.cv.settings.interview_max_target_attempts)
                break
            except ValueError as exc:
                await record(exc.code if isinstance(exc, DecisionRejected) else 'invalid_schema', raw.get('action'))
                feedback = [str(exc)[:500]]
                invalid_calls += 1
                if invalid_calls >= MAX_PLAN_CALLS: break
        if decision is None:
            skipped_topic = memory.get('focus_item_id')
            if route.get('_command') == 'skip' and skipped_topic:
                # Close the skipped topic with gaps and plan once more without it.
                memory['coverage'][skipped_topic] = {'item_id': skipped_topic, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
                memory['focus_item_id'] = None
                return await self.plan(app, account, conversation, document, route, token, memory)
            reason = diagnostics[-1]['reason'] if diagnostics else ''
            explanations = {
                'question_no_ambiguity': 'It tried to ask about an experience whose CV details are already clear.',
                'question_topic_limit': 'It tried to ask more than two questions in the same review group.',
                'question_targets_closed': 'It kept selecting details that are already answered, skipped or exhausted.',
                'question_targets_mixed': 'It kept mixing open questions with details that are already closed.',
                'question_multiple': 'It tried to combine several questions into one turn.',
                'finish_unvisited': 'It tried to finish before all review topics were covered.',
                'coverage_unvisited': 'It tried to close an experience that has not been discussed.',
                'coverage_source': 'It referred to an experience that is unavailable.',
                'hydrate_source': 'It could not settle on the next experience to review.',
                'recall_answers': 'It kept requesting earlier answers instead of choosing the next question.',
                'recall_unavailable': 'It requested an earlier answer that is unavailable in the current context.',
                'invalid_schema': 'Its proposed next steps did not match the required response format.',
                'answer_instead_of_next_step': 'It replied without choosing the next question or completion.',
                'question_requested_topic': 'It did not ask about the topic you chose to review.',
            }
            detail = explanations.get(reason, 'Its proposed next steps did not pass the review checks.')
            if reason.startswith('estimate_'):
                detail = 'It proposed a skill estimate without the required supporting evidence.'
            raise CodedError('no_valid_next_step', 'The interview could not choose a valid next step. ' + detail + ' Your answers are saved; retry to continue.')
        latest = self.service.cv.get(account['id'], document['_id'])
        if latest['version'] != document['version']: raise Conflict('Your CV changed while planning. Your answers are saved; retry with the latest evidence.')
        decision.reply = review_reply(decision.reply)
        for estimate in decision.estimates:
            estimate.explanation = review_reply(estimate.explanation)
        memory['coverage'] = coverage
        memory['summary'] = [{'item_id': i, 'status': v['status']} for i, v in coverage.items()]
        memory['estimates'] = baseline_estimates(current_items)
        active, targets, reply_text = None, [], decision.reply
        if decision.action == 'ask':
            memory.update(status='reviewing', focus_item_id=decision.item_id)
            asked = topic_question_count(memory, decision.item_id) + 1
            active = {'id': key(route['id'] + ':interview-question'), 'item_id': decision.item_id,
                      'title': context['focused_source']['title'], 'question': decision.reply,
                      'number': asked, 'limit': MAX_TOPIC_QUESTIONS,
                      'hints': ['Your own actions', 'Relevant decisions or constraints'] if decision.answer_hints else [],
                      'reason': 'This helps clarify your experience.' if decision.reason else None}
            targets = [t.model_dump(mode='json') for t in decision.targets]
            facts = fact_groups(evidence_for(context['focused_source']))
            for target in targets:
                identity = target_key(decision.item_id, target['field'], target.get('skill_name'))
                fact = fact_group_value(facts.get((target['field'], normalized_name(target.get('skill_name') or '')), []))
                signature = digest(fact) if fact else 'missing'
                previous = memory['attempts'].get(identity, {})
                memory['attempts'][identity] = {'signature': signature, 'count': previous.get('count', 0) + 1
                    if previous.get('signature') == signature else 1}
            group = memory.get('item_groups', {}).get(decision.item_id, decision.item_id)
            memory.setdefault('group_question_counts', {})[group] = asked
            memory.setdefault('question_counts', {})[decision.item_id] = asked
            unverified = next((i for i in current_items if i['id'] == decision.item_id and i.get('validation_issue')), None)
            if unverified and asked == 1:
                reply_text = unverified_notice(unverified['title']) + '\n\n' + decision.reply
            memory['questions'].append({**active, 'targets': targets, 'evidence_version': document['effective_version']})
            memory['questions'] = memory['questions'][-120:]
        elif decision.action == 'finish':
            memory['focus_item_id'] = None
            decision.reply = ('Your review is complete. Some details remain uncertain.' if any(v['status'] != 'reviewed' for v in coverage.values())
                              else 'Your review is complete.')
            reply_text = decision.reply
            memory['status'] = 'reviewed' if all(v['status'] == 'reviewed' for v in coverage.values()) else 'reviewed_with_gaps'
        elif decision.action == 'pause':
            memory['status'] = 'paused'
            reply_text = 'We can pause here. Your answers are saved; remaining details stay uncertain.'
            if memory.get('focus_item_id') in memory['coverage']: memory['focus_item_id'] = None
        else:
            active, targets = conversation.get('active_question'), conversation.get('interview_targets', [])
        if active:
            source = next(item for item in current_items if item['id'] == active['item_id'])
            return await self.save_question(account, conversation, document, route, token, memory,
                reply_text, active, targets, source)
        return await self.publish(account, conversation['_id'], route['id'], token, memory, reply_text, active, targets)

    async def save_question(self, account, conversation, document, route, token, memory, reply_text, active, targets, source):
        """Stage before writing so a retry publishes the same question and count exactly once."""
        uncertainty = 'claim'
        question = {'id': active['id'], 'item_id': active['item_id'],
            'kind': 'project' if source['kind'] == 'project' else 'work' if source['kind'] == 'experience' else 'other',
            'question': active['question'], 'uncertainty': uncertainty,
            'uncertainty_key': digest({'interview_question': active['id']}), 'status': 'unanswered', 'answer': None,
            'career_target_id': None, 'career_target_version': None, 'career_target_type': None,
            'extraction_version': document['extraction_version'], 'reconciliation_required': False,
            'answer_revision': 0, 'answer_sequence': 0, 'interpretation_status': 'not_requested',
            'interpretation_error': None, 'resolution': 'unresolved', 'interpretation': None, 'followup_of': None,
            '_interview_targets': targets, '_interview_group': memory.get('item_groups', {}).get(active['item_id'], active['item_id']),
            '_interview_policy': memory['review_policy'], '_interview_section': source['kind']}
        def retain_plan(current):
            action = action_in(current, route['id'])
            self.service.check_lease(action, token)
            action['_interview_plan'] = {'memory': memory, 'reply': reply_text, 'active': active, 'targets': targets,
                'question': question, 'expected_version': document['version']}
        await run_in_threadpool(self.service.update, account['id'], conversation['_id'], retain_plan)
        def add(current):
            saved_policy = current.setdefault('review_policy_snapshot', memory['review_policy'])
            if saved_policy != memory['review_policy']:
                raise Conflict('Your review policy changed. Continue with the current review.')
            if any(q['id'] == question['id'] for q in current['clarifications']): return
            if len(current['clarifications']) >= 800: raise CvError('This CV has reached its question history limit.', 409)
            current['clarifications'].append(question)
        await run_in_threadpool(self.service.cv.mutate, account['id'], document['_id'],
            Mutation(expected_version=document['version'], mutation_id=key(route['id'] + ':interview-question')),
            'interview-question', add)
        return await self.publish(account, conversation['_id'], route['id'], token, memory, reply_text, active, targets)

    async def rate_skill_levels(self, account, conversation):
        """Rate the skills of every closed or skipped topic, and of every source once the review ends.

        Runs after a reply is saved and when a finished review is read; failures back off and retry. Levels are stored beside the CV and applied on read.
        """
        service, owner = self.service, account['id']
        try:
            memory = conversation.get('interview_memory') or {}
            document = service.cv.get(owner, conversation['cv_id'])
            if document['operation']['status'] != 'ready' or document.get('candidate'): return
            finished = memory.get('status') in {'reviewed', 'reviewed_with_gaps'}
            statuses = {item_id: value['status'] for item_id, value in memory.get('coverage', {}).items()}
            items = [item for item in effective_items(document)
                     if not item['removed'] and (finished or item['id'] in statuses)]
            failures = document.get('skill_level_failures') or {}
            pending = [source for source in pending_sources(document, items, statuses) if rating_ready(source, failures, now())]
            for start in range(0, len(pending), BATCH):
                batch = pending[start:start + BATCH]
                try:
                    rated = await run_in_threadpool(service.rate_skill_levels, owner,
                        {'task': 'cv_skill_levels', 'sources': [source['model'] for source in batch]})
                    if rated is None: return
                    reviews = validate_level_review(rated[0], batch)
                except Exception:
                    current = service.cv.get(owner, document['_id'])
                    at = now()
                    def record_failure(target):
                        saved = target.setdefault('skill_level_failures', {})
                        for source in batch:
                            saved[source['item_id']] = rating_failure(source, saved.get(source['item_id'], {}), at)
                    await run_in_threadpool(service.cv.mutate, owner, document['_id'],
                        Mutation(expected_version=current['version'], mutation_id=uuid5(NAMESPACE_URL,
                            'elo:skill-level-failure:' + digest([source['fingerprint'] for source in batch]) + ':' + str(at))),
                        'skill-level-failure', record_failure, record_history=False)
                    return
                current = service.cv.get(owner, document['_id'])
                def store(target):
                    target.setdefault('skill_level_reviews', {}).update(deepcopy(reviews))
                    for item_id in reviews: target.get('skill_level_failures', {}).pop(item_id, None)
                await run_in_threadpool(service.cv.mutate, owner, document['_id'],
                    Mutation(expected_version=current['version'],
                             mutation_id=uuid5(NAMESPACE_URL, 'elo:skill-levels:' + digest(reviews))),
                    'skill-levels', store, record_history=False)
        except Exception as exc:
            logger.warning('CV skill level evaluation skipped reason=%s', type(exc).__name__)

    async def no_progress(self, app, account, conversation, document, route, token, memory, active):
        # Keep the original question visible without issuing it again.
        if active:
            failures = memory.setdefault('no_progress', {})
            failures[active['id']] = failures.get(active['id'], 0) + 1
            if failures[active['id']] >= 2:
                document = await self.skip_active(account, conversation, document, route, token, memory)
                groups = memory.get('item_groups', {})
                group = groups.get(active['item_id'], active['item_id'])
                for item_id in memory.get('topic_ids', []):
                    if groups.get(item_id, item_id) == group:
                        memory['coverage'][item_id] = {'item_id': item_id, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
                        memory.setdefault('deferred_topics', {})[item_id] = {'reason': 'no_progress', 'remaining_ownership': 'uncertain'}
                memory['focus_item_id'] = None
                self.lead = 'I could not process those answers, so I will leave these details uncertain and move on. '
                conversation = {**conversation, 'active_question': None}
                return await self.plan(app, account, conversation, document, route, token, memory)
        return await self.publish(account, conversation['_id'], route['id'], token, memory,
            'I could not connect that answer to the current question. You can edit your answer, skip, or continue.',
            active, conversation.get('interview_targets', []))

    async def pause(self, account, identifier, route_id, token, memory, reply):
        memory['status'] = 'paused'
        return await self.publish(account, identifier, route_id, token, memory, reply, None, [])

    async def publish(self, account, identifier, route_id, token, memory, reply, active, targets, status_only=False):
        reply = review_reply(self.lead + reply)
        if not reply:
            raise ValueError('The review reply contained no readable text. Your answer is saved; retry to continue.')
        if active: active = {**active, 'question': review_reply(active['question']),
                             **({'hints': [h for h in (review_reply(x) for x in active['hints']) if h]} if active.get('hints') else {})}
        def save(current):
            action = action_in(current, route_id)
            self.service.check_lease(action, token)
            action.pop('_resume_requested', None)
            action.update(status='saved', summary='Interview updated.', error=None, _token=None, _lease_until=0)
            message = action_message(current, route_id)
            message.update(text=reply, _status_only=status_only, _question_id=active['id'] if active else None)
            document = self.service.cv.get(account['id'], current['cv_id'])
            if document['effective_version'] != memory['evidence_version']:
                raise Conflict('Your evidence changed before the interview reply was saved. Continue with the latest evidence.')
            # Publish the same canonical memory shape that status polling reads.
            normalized = reconcile_memory({**current, 'interview_memory': memory}, document)
            current.update(interview_memory=normalized, interview_progress=progress(normalized, document),
                           active_question=active, interview_targets=targets)
            if active: current['last_item_id'] = active['item_id']
        saved = await run_in_threadpool(self.service.update, account['id'], identifier, save)
        await self.rate_skill_levels(account, saved)
        if memory.get('status') in {'reviewed', 'reviewed_with_gaps'}:
            await run_in_threadpool(self.service.cv.complete_review, account['id'], saved['cv_id'])
        return saved

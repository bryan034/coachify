"""Agent-led CV interview orchestration with durable, retryable stages.

The harness commits validated evidence before asking the agent for its next
interview action. Memory and decision policy have independent, inspectable modules.
"""
import logging
import re
from copy import deepcopy
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from app.domain.capabilities import effective_items, digest, normalized_name, validate_review_interpretation
from app.domain.errors import Conflict, CvError
from app.domain.baseline import baseline_estimates
from app.domain.review_context import clarification_context
from app.domain.service import now
from app.schemas.cv import Mutation
from app.schemas.interview import InterviewTurn
from app.schemas.interview_evidence import fact_key, fact_groups, fact_group_value
from app.conversation.interview_memory import (build_context, reconcile_memory, progress, evidence_for, target_key,
    topic_question_count, topic_discussed, topic_ids, enough_context, ownership_established, question_options, MAX_TOPIC_QUESTIONS, MAX_TARGET_ATTEMPTS)
from app.conversation.presentation import review_reply, unverified_notice
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


class InterviewHarness:
    def __init__(self, service):
        self.service = service
        self.lead = ''  # Fixed text placed before the next reply, e.g. confirming a skipped topic.
        self.requested_topic = None  # A topic the user asked to review; the next question must be about it.

    async def call(self, app, account, conversation_id, route_id, token, payload):
        from app.conversation.service import action_in, LEASE_SECONDS
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
        from app.conversation.service import action_in, action_message, key
        service, owner, identifier = self.service, account['id'], conversation['_id']
        document = service.cv.get(owner, conversation['cv_id'])
        if document['operation']['status'] != 'ready' or document.get('candidate'):
            raise CvError('Finish CV processing or source reconciliation before reviewing. Your conversation is saved.', 409)
        memory = reconcile_memory(conversation, document)
        memory['max_target_attempts'] = service.cv.settings.interview_max_target_attempts
        retained = route.get('_interview_plan')
        if retained:
            question = retained['question']
            receipt = key(route['id'] + ':interview-question')
            if document['extraction_version'] != retained['memory']['extraction_version']:
                raise Conflict('Your source changed while saving the question. Continue from the latest evidence.')
            def add(current):
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
        if command == 'skip':
            active = conversation.get('active_question')
            if active:
                document = await self.skip_active(account, conversation, document, route, token, memory)
                conversation = {**conversation, 'active_question': None}
                # With nothing left to ask here, close the topic now rather than
                # leaving the planner focused on a source it cannot question.
                source = next((i for i in effective_items(document) if i['id'] == active['item_id'] and not i['removed']), None)
                if source and not clarification_context(source, evidence_for(source))['clarification_targets']:
                    memory['coverage'][source['id']] = {'item_id': source['id'], 'status': 'reviewed_with_gaps', 'evidence_refs': []}
                    memory['focus_item_id'] = None
            else:
                failed = next((a for m in reversed(conversation['messages']) for a in reversed(m.get('actions', []))
                    if a['kind'] == 'route' and a['status'] == 'failed'
                    and (a.get('error') or '').startswith('The interview could not choose a valid next step.')), None)
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
                                        and ((previous.get('error') or '').startswith('The interview could not choose a valid next step.')
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
                            reply = 'Could you clarify that in a little more detail?' + (' ' + active['question'] if active else '')
                            return await self.publish(account, identifier, route['id'], token, memory,
                                reply, active, conversation.get('interview_targets', []))
                evaluated = {'result': result.model_dump(mode='json'), 'metadata': metadata}
                def remember(current):
                    service.check_lease(action_in(current, route['id']), token)
                    action_in(current, route['id'])['_interview_evaluation'] = evaluated
                await run_in_threadpool(service.update, owner, identifier, remember)
            result = InterviewTurn.model_validate(evaluated['result'])
            if not result.topic_relevant:
                active = conversation.get('active_question')
                reply = 'Let’s stay with your experience and skills.' + (' ' + active['question'] if active else ' Which experience would you like to discuss?')
                return await self.publish(account, identifier, route['id'], token, memory,
                    reply, active, conversation.get('interview_targets', []))
            for note in result.memory_notes:
                if note.source_id != 'answer' or note.quote not in route['_text']:
                    continue  # Ignore unusable optional notes without blocking the answer.
                entry = {'source_id': route.get('_message_id', route['_turn_id']), 'quote': note.quote}
                if entry not in memory['notes']: memory['notes'].append(entry)
            memory['notes'] = memory['notes'][-24:]
            if result.intent == 'stop':
                return await self.pause(account, identifier, route['id'], token, memory,
                    'We can stop here. Your answers are saved; remaining details stay uncertain.')
            if result.intent == 'skip' or (result.actions and all(a.kind == 'skip' for a in result.actions)):
                return await self.process(app, account, conversation, {**route, '_command': 'skip'}, token)
            if result.intent == 'side_question':
                return await self.publish(account, identifier, route['id'], token, memory,
                    result.reply, conversation.get('active_question'), conversation.get('interview_targets', []))
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
                        proposal.excerpt = route['_text']  # Anchor the action to the saved answer, not a model paraphrase.
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
                # Interpretation succeeded. Recovery belongs to each evidence
                # action, not a duplicate failed routing card for the same turn.
                notes = memory['notes']
                memory = reconcile_memory(latest, service.cv.get(owner, latest['cv_id']))
                memory['notes'] = notes
                def waiting(current):
                    action_in(current, route['id'])['_interview_waiting'] = True
                await run_in_threadpool(service.update, owner, identifier, waiting)
                reply = 'Your answer is saved. We couldn’t finish processing it yet.' if any(a['status'] in {'failed', 'stale'} for a in remaining) else result.reply
                return await self.publish(account, identifier, route['id'], token, memory,
                    reply, latest.get('active_question'), latest.get('interview_targets', []))
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
        from app.conversation.service import action_in, key
        from app.clarification.service import answer
        from app.schemas.cv import AnswerMutation
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
            # Reviewing again starts from what was saved: answers stay, but the skipped questions are
            # reopened and the topic gets a fresh question budget, using the updated source context.
            from app.conversation.service import key
            document = await run_in_threadpool(self.service.cv.reopen_topic_skips, account['id'], document['_id'], target,
                key(route['id'] + ':reopen:' + target))
            items = {i['id']: i for i in effective_items(document) if not i['removed']}
            memory.setdefault('question_counts', {})[target] = 0
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
                # A topic that needed all of its questions closes with gaps, as before. An early
                # close is reviewed only with proven ownership; skill levels stay uncertain where unproven.
                status = 'reviewed' if not used_budget and ownership_established(item) else 'reviewed_with_gaps'
                memory['coverage'][item['id']] = {'item_id': item['id'], 'status': status, 'evidence_refs': []}
                closed.append(item['title'])
        # Focus stays on a just-closed topic so the planner can still cite its evidence when moving on.
        return closed

    async def plan(self, app, account, conversation, document, route, token, memory):
        from app.conversation.service import key
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
        # Offer the next viable topic up front when the current one has no
        # remaining material question. The previous ledger remains citable.
        current_focus = next((item for item in eligible if item['id'] == memory.get('focus_item_id')), None)
        if not current_focus or not any(option['open_fields'] for option in question_options(current_focus, memory)):
            focus_id = next((item['id'] for item in eligible
                             if any(option['open_fields'] for option in question_options(item, memory))), None)
        if self.requested_topic: focus_id = self.requested_topic
        decision = None
        diagnostics = []

        async def record(code, action):
            from app.conversation.service import action_in
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
            # The agent can choose another experience; hydrate it before validating
            # a question rather than asking it to reason from an abbreviated title.
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
                # A skip must not strand the user on a failed plan: close this topic with
                # gaps and plan once more without it. Focus is now empty, so this cannot loop.
                memory['coverage'][skipped_topic] = {'item_id': skipped_topic, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
                memory['focus_item_id'] = None
                return await self.plan(app, account, conversation, document, route, token, memory)
            reason = diagnostics[-1]['reason'] if diagnostics else ''
            explanations = {
                'question_no_ambiguity': 'It tried to ask about an experience whose CV details are already clear.',
                'question_topic_limit': 'It tried to ask more than three questions about the same topic.',
                'question_targets_closed': 'It kept selecting details that are already answered, skipped or exhausted.',
                'question_targets_mixed': 'It kept mixing open questions with details that are already closed.',
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
            raise ValueError('The interview could not choose a valid next step. ' + detail + ' Your answers are saved; retry to continue.')
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
                      'hints': [hint for hint in (review_reply(h) for h in decision.answer_hints) if hint][:4],
                      'reason': review_reply(decision.reason) or None if decision.reason else None}
            targets = [t.model_dump(mode='json') for t in decision.targets]
            facts = fact_groups(evidence_for(context['focused_source']))
            for target in targets:
                identity = target_key(decision.item_id, target['field'], target.get('skill_name'))
                fact = fact_group_value(facts.get((target['field'], normalized_name(target.get('skill_name') or '')), []))
                signature = digest(fact) if fact else 'missing'
                previous = memory['attempts'].get(identity, {})
                memory['attempts'][identity] = {'signature': signature, 'count': previous.get('count', 0) + 1
                    if previous.get('signature') == signature else 1}
            memory.setdefault('question_counts', {})[decision.item_id] = asked
            unverified = next((i for i in current_items if i['id'] == decision.item_id and i.get('validation_issue')), None)
            # Say it again in the chat, once, before the first question about a section that failed validation.
            if unverified and memory['question_counts'][decision.item_id] == 1:
                reply_text = unverified_notice(unverified['title']) + '\n\n' + decision.reply
            memory['questions'].append({**active, 'targets': targets, 'evidence_version': document['effective_version']})
            memory['questions'] = memory['questions'][-120:]
        elif decision.action == 'finish':
            memory['focus_item_id'] = None
            decision.reply = ('Your review is complete. Some details remain uncertain.' if any(v['status'] != 'reviewed' for v in coverage.values())
                              else 'Your review is complete.')
            memory['status'] = 'reviewed' if all(v['status'] == 'reviewed' for v in coverage.values()) else 'reviewed_with_gaps'
        elif decision.action == 'pause':
            memory['status'] = 'paused'
            if memory.get('focus_item_id') in memory['coverage']: memory['focus_item_id'] = None
        else:
            active, targets = conversation.get('active_question'), conversation.get('interview_targets', [])
        if active:
            from app.conversation.service import action_in
            # Interview targets carry field scope. Legacy attribution-wide questions
            # would require reinterpreting every skill on an unrelated follow-up.
            uncertainty = 'claim'
            question = {'id': active['id'], 'item_id': active['item_id'],
                'kind': 'project' if context['focused_source']['kind'] == 'project' else 'work' if context['focused_source']['kind'] == 'experience' else 'other',
                'question': active['question'], 'uncertainty': uncertainty,
                'uncertainty_key': digest({'interview_question': active['id']}), 'status': 'unanswered', 'answer': None,
                'career_target_id': None, 'career_target_version': None, 'career_target_type': None,
                'extraction_version': document['extraction_version'], 'reconciliation_required': False,
                'answer_revision': 0, 'answer_sequence': 0, 'interpretation_status': 'not_requested',
                'interpretation_error': None, 'resolution': 'unresolved', 'interpretation': None, 'followup_of': None,
                '_interview_targets': targets}
            def retain_plan(current):
                action = action_in(current, route['id'])
                self.service.check_lease(action, token)
                action['_interview_plan'] = {'memory': memory, 'reply': reply_text, 'active': active, 'targets': targets,
                    'question': question, 'expected_version': document['version']}
            await run_in_threadpool(self.service.update, account['id'], conversation['_id'], retain_plan)
            def add(current):
                if any(q['id'] == question['id'] for q in current['clarifications']): return
                if len(current['clarifications']) >= 800: raise CvError('This CV has reached its question history limit.', 409)
                current['clarifications'].append(question)
            await run_in_threadpool(self.service.cv.mutate, account['id'], document['_id'],
                Mutation(expected_version=document['version'], mutation_id=key(route['id'] + ':interview-question')),
                'interview-question', add)
        return await self.publish(account, conversation['_id'], route['id'], token, memory, reply_text, active, targets)

    async def pause(self, account, identifier, route_id, token, memory, reply):
        memory['status'] = 'paused'
        return await self.publish(account, identifier, route_id, token, memory, reply, None, [])

    async def publish(self, account, identifier, route_id, token, memory, reply, active, targets):
        reply = review_reply(self.lead + reply)
        if not reply:
            raise ValueError('The review reply contained no readable text. Your answer is saved; retry to continue.')
        if active: active = {**active, 'question': review_reply(active['question']),
                             **({'hints': [h for h in (review_reply(x) for x in active['hints']) if h]} if active.get('hints') else {})}
        from app.conversation.service import action_in, action_message
        def save(current):
            action = action_in(current, route_id)
            self.service.check_lease(action, token)
            action.pop('_resume_requested', None)
            action.update(status='saved', summary='Interview updated.', error=None, _token=None, _lease_until=0)
            action_message(current, route_id)['text'] = reply
            document = self.service.cv.get(account['id'], current['cv_id'])
            if document['effective_version'] != memory['evidence_version']:
                raise Conflict('Your evidence changed before the interview reply was saved. Continue with the latest evidence.')
            # Publish the same canonical memory shape that status polling reads.
            # A read racing this write must not normalize private fields later
            # and silently invalidate the revision returned with this reply.
            normalized = reconcile_memory({**current, 'interview_memory': memory}, document)
            current.update(interview_memory=normalized, interview_progress=progress(normalized, document),
                           active_question=active, interview_targets=targets)
            if active: current['last_item_id'] = active['item_id']
        saved = await run_in_threadpool(self.service.update, account['id'], identifier, save)
        if memory.get('status') in {'reviewed', 'reviewed_with_gaps'}:
            await run_in_threadpool(self.service.cv.mark_reviewed_when_ready, account['id'], saved['cv_id'])
        return saved

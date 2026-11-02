"""Agent-led CV interview orchestration with durable, retryable stages.

The harness commits validated evidence before asking the agent for its next
interview action. Memory and decision policy have independent, inspectable modules.
"""
from copy import deepcopy
from starlette.concurrency import run_in_threadpool
from app.domain.capabilities import effective_items, digest, normalized_name
from app.domain.errors import Conflict, CvError
from app.domain.service import now
from app.schemas.cv import Mutation
from app.schemas.interview import InterviewTurn
from app.schemas.interview_evidence import fact_key
from app.conversation.interview_memory import build_context, reconcile_memory, progress, evidence_for, target_key, MAX_TARGET_ATTEMPTS
from app.conversation.interview_policy import validate_decision

MAX_PLAN_CALLS = 3


class InterviewHarness:
    def __init__(self, service): self.service = service

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
        if command == 'finish':
            return await self.pause(account, identifier, route['id'], token, memory,
                'We can stop here. Your answers are saved; remaining details stay uncertain.')
        if command == 'skip':
            active = conversation.get('active_question')
            if active:
                from app.clarification.service import answer
                from app.schemas.cv import AnswerMutation
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
                conversation = {**conversation, 'active_question': None}
        elif command not in {'review', 'continue'}:
            evaluated = route.get('_interview_evaluation')
            if evaluated is None:
                context = build_context(conversation, document, memory)
                result, metadata = await self.call(app, account, identifier, route['id'], token,
                    {'task': 'cv_interview_interpret', 'message': route['_text'], **context})
                result = InterviewTurn.model_validate(result)
                evaluated = {'result': result.model_dump(mode='json'), 'metadata': metadata}
                def remember(current):
                    service.check_lease(action_in(current, route['id']), token)
                    action_in(current, route['id'])['_interview_evaluation'] = evaluated
                await run_in_threadpool(service.update, owner, identifier, remember)
            result = InterviewTurn.model_validate(evaluated['result'])
            for note in result.memory_notes:
                if note.source_id != 'answer' or note.quote not in route['_text']:
                    raise ValueError('Conversation memory must quote your current message exactly.')
                entry = {'source_id': route.get('_message_id', route['_turn_id']), 'quote': note.quote}
                if entry not in memory['notes']: memory['notes'].append(entry)
            memory['notes'] = memory['notes'][-24:]
            if result.intent == 'stop':
                return await self.pause(account, identifier, route['id'], token, memory,
                    'We can stop here. Your answers are saved; remaining details stay uncertain.')
            if result.intent == 'skip':
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
                    if proposal.excerpt not in route['_text']: raise ValueError('The interview cited words you did not send.')
                    if proposal.item_id and proposal.item_id not in items: raise ValueError('The interview referred to another source.')
                    if any(i not in items for i in proposal.candidate_item_ids): raise ValueError('Invalid source choice.')
                    if proposal.question_id and (proposal.question_id not in questions or
                        proposal.item_id and questions[proposal.question_id]['item_id'] != proposal.item_id):
                        raise ValueError('The interview referred to another question.')
                    if proposal.kind == 'add_capability':
                        statement = f'The user personally performed {proposal.name}: {proposal.excerpt}'
                        supported = await run_in_threadpool(service.verify_intake, owner,
                            [{'id': 'answer', 'text': proposal.excerpt}], [{'block_id': 'answer', 'excerpt': statement}])
                        if ('answer', statement) not in supported:
                            raise ValueError('That capability is not supported by your stated personal work. Your message is saved.')
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
                if any(a['status'] in {'failed', 'stale'} for a in remaining):
                    raise ValueError('Your answer is saved. Finish or retry the evidence action before continuing the interview.')
                def waiting(current):
                    action_in(current, route['id'])['_interview_waiting'] = True
                await run_in_threadpool(service.update, owner, identifier, waiting)
                return await self.publish(account, identifier, route['id'], token, memory,
                    result.reply, latest.get('active_question'), latest.get('interview_targets', []))
            conversation = latest
            document = service.cv.get(owner, conversation['cv_id'])
            notes = memory['notes']
            memory = reconcile_memory(conversation, document)
            memory['notes'] = notes
        if any(q.get('interpretation_status') in {'pending', 'failed'} and not q.get('reconciliation_required')
               for q in document['clarifications']):
            raise ValueError('Your saved evidence still needs interpretation. Retry that action before continuing.')
        return await self.plan(app, account, conversation, document, route, token, memory)

    async def plan(self, app, account, conversation, document, route, token, memory):
        from app.conversation.service import key
        focus_id, feedback, recall_ids = None, [], []
        decision = None
        for _ in range(MAX_PLAN_CALLS):
            context = build_context(conversation, document, memory, focus_id=focus_id, recall_ids=recall_ids)
            result, _ = await self.call(app, account, conversation['_id'], route['id'], token,
                {'task': 'cv_interview_plan', 'validation_feedback': feedback, **context})
            raw = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
            if raw.get('action') == 'recall':
                available = {a['id'] for a in context['source_answers']}
                if not raw.get('recall_ids') or not set(raw['recall_ids']) <= available:
                    feedback = ['Choose only available source answer IDs.']
                else:
                    recall_ids = raw['recall_ids']
                    feedback = ['Requested answers are included. Choose the next interview action.']
                continue
            # The agent can choose another experience; hydrate it before validating
            # a question rather than asking it to reason from an abbreviated title.
            if raw.get('action') == 'ask' and raw.get('item_id') and (context.get('focused_source') or {}).get('id') != raw['item_id']:
                focus_id = raw['item_id']
                feedback = ['Your selected experience is now hydrated. Reconsider the question against its known evidence.']
                continue
            try:
                decision, coverage = validate_decision(raw, context, memory, max_attempts=self.service.cv.settings.interview_max_target_attempts)
                break
            except ValueError as exc:
                feedback = [str(exc)[:500]]
        else:
            raise ValueError('The interview could not choose a valid next step. Your answers are saved; retry to continue.')
        latest = self.service.cv.get(account['id'], document['_id'])
        if latest['version'] != document['version']: raise Conflict('Your CV changed while planning. Your answers are saved; retry with the latest evidence.')
        memory['coverage'] = coverage
        memory['summary'] = [{'item_id': i, 'status': v['status']} for i, v in coverage.items()]
        estimates = {(e['item_id'], normalized_name(e['skill_name'])): e for e in memory['estimates']}
        estimates.update({(e.item_id, normalized_name(e.skill_name)): e.model_dump(mode='json') for e in decision.estimates})
        memory['estimates'] = list(estimates.values())
        active, targets = None, []
        if decision.action == 'ask':
            memory.update(status='reviewing', focus_item_id=decision.item_id)
            active = {'id': key(route['id'] + ':interview-question'), 'item_id': decision.item_id,
                      'title': context['focused_source']['title'], 'question': decision.reply}
            targets = [t.model_dump(mode='json') for t in decision.targets]
            facts = {fact_key(f): f for f in evidence_for(context['focused_source'])}
            for target in targets:
                identity = target_key(decision.item_id, target['field'], target.get('skill_name'))
                fact = facts.get((target['field'], normalized_name(target.get('skill_name') or '')))
                signature = digest(fact) if fact else 'missing'
                previous = memory['attempts'].get(identity, {})
                memory['attempts'][identity] = {'signature': signature, 'count': previous.get('count', 0) + 1
                    if previous.get('signature') == signature else 1}
            memory['questions'].append({**active, 'targets': targets, 'evidence_version': document['effective_version']})
            memory['questions'] = memory['questions'][-120:]
        elif decision.action == 'finish':
            memory['status'] = 'reviewed' if coverage and all(v['status'] == 'reviewed' for v in coverage.values()) else 'reviewed_with_gaps'
        elif decision.action == 'pause': memory['status'] = 'paused'
        else:
            active, targets = conversation.get('active_question'), conversation.get('interview_targets', [])
        if active:
            from app.conversation.service import action_in
            uncertainty = 'personal_contribution' if any(t['field'] == 'personal_contribution' for t in targets) else 'responsibility' if any(t['field'] == 'responsibilities' for t in targets) else 'claim'
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
                action['_interview_plan'] = {'memory': memory, 'reply': decision.reply, 'active': active, 'targets': targets,
                    'question': question, 'expected_version': document['version']}
            await run_in_threadpool(self.service.update, account['id'], conversation['_id'], retain_plan)
            def add(current):
                if any(q['id'] == question['id'] for q in current['clarifications']): return
                if len(current['clarifications']) >= 800: raise CvError('This CV has reached its question history limit.', 409)
                current['clarifications'].append(question)
            await run_in_threadpool(self.service.cv.mutate, account['id'], document['_id'],
                Mutation(expected_version=document['version'], mutation_id=key(route['id'] + ':interview-question')),
                'interview-question', add)
        return await self.publish(account, conversation['_id'], route['id'], token, memory, decision.reply, active, targets)

    async def pause(self, account, identifier, route_id, token, memory, reply):
        memory['status'] = 'paused'
        return await self.publish(account, identifier, route_id, token, memory, reply, None, [])

    async def publish(self, account, identifier, route_id, token, memory, reply, active, targets):
        from app.conversation.service import action_in, action_message
        def save(current):
            action = action_in(current, route_id)
            self.service.check_lease(action, token)
            action.update(status='saved', summary='Interview updated.', error=None, _token=None, _lease_until=0)
            action_message(current, route_id)['text'] = reply
            document = self.service.cv.get(account['id'], current['cv_id'])
            if document['effective_version'] != memory['evidence_version']:
                raise Conflict('Your evidence changed before the interview reply was saved. Continue with the latest evidence.')
            current.update(interview_memory=memory, interview_progress=progress(memory, document),
                           active_question=active, interview_targets=targets)
            if active: current['last_item_id'] = active['item_id']
        return await run_in_threadpool(self.service.update, account['id'], identifier, save)

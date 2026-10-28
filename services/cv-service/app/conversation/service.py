"""CV conversation coordination. Existing domain operations remain the write authority."""
from copy import deepcopy
import asyncio
import json
from uuid import uuid4, uuid5, NAMESPACE_URL
import re
import httpx
from bson import BSON
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from app.domain.capabilities import digest, effective_items, normalized_name
from app.domain.errors import Conflict, CvError, Missing
from app.domain.service import now, iso
from app.domain.attachments import source_fingerprint
from app.clarification.service import answer, prepare, envelope, context_identity, retry_interpretation
from app.schemas.cv import Mutation, AnswerMutation, ItemMutation, PrepareMutation, ConfirmedContext
from app.schemas.conversation import ConversationRoute, ChatAction

MAX_MESSAGES = 500
MAX_SEGMENTS = 100
LEASE_SECONDS = 90


def key(value): return str(uuid5(NAMESPACE_URL, 'coachify-cv-chat:' + value))


def at_capacity(document):
    # Reserve both user and assistant messages plus room for this turn's bounded
    # action receipts. A capacity limit never deletes older factual provenance.
    return len(document['messages']) + 2 > MAX_MESSAGES or len(BSON.encode(document)) >= 6 * 1024 * 1024


def public_action(action):
    result = {field: value for field, value in action.items() if field in ChatAction.model_fields}
    deadline = action.get('_lease_until') or action.get('_queued_at', now()) + LEASE_SECONDS
    if action['status'] == 'pending' and deadline <= now():
        result.update(status='failed', error='Processing was interrupted. Retry this saved action.',
                      summary='Your message is saved. Retry to finish the interrupted action.')
    return ChatAction.model_validate(result).model_dump(mode='json')


def view(document, before=None, limit=40):
    messages = [message for message in document['messages'] if before is None or message['sequence'] < before]
    window = messages[-limit:]
    return {'id': document['_id'], 'cv_id': document['cv_id'], 'revision': document['revision'],
        'read_only': at_capacity(document),
        'previous_conversation_id': document.get('previous_conversation_id'),
        'active_question': document.get('active_question'), 'context': document.get('context'),
        'context_error': document.get('context_error'),
        'messages': [{**{k: m[k] for k in ('id', 'sequence', 'role', 'text', 'created_at')},
                      'actions': [public_action(a) for a in m.get('actions', [])]} for m in window],
        'next_before': window[0]['sequence'] if len(messages) > len(window) else None}


def action_in(document, identifier):
    for message in document['messages']:
        for action in message.get('actions', []):
            if action['id'] == identifier: return action
    raise Missing()


def action_message(document, identifier):
    return next(m for m in document['messages'] if any(a['id'] == identifier for a in m.get('actions', [])))


def make_message(document, role, text, actions=None):
    return {'id': str(uuid4()), 'sequence': len(document['messages']) + 1, 'role': role, 'text': text,
            'created_at': iso(now()), 'actions': actions or []}


class ConversationService:
    def __init__(self, cv_service, provider):
        self.cv, self.repository, self.provider = cv_service, cv_service.repository.conversations, provider
        # Share the CV interpreter's global provider limit, including routing calls.
        self.slots = cv_service.interpretation_slots
        self.tasks = set()

    async def dispatch(self, operation, owner, identifier, action_id, token=None):
        if len(self.tasks) >= 16:
            operation.close()
            await self.fail(owner, identifier, action_id, token, 'Conversation processing is busy. Your message is saved; retry shortly.')
            return
        task = asyncio.create_task(operation)
        self.tasks.add(task)
        def finished(completed):
            self.tasks.discard(completed)
            # Storage can disappear before the coordinator can publish a failure.
            # The durable lease remains recoverable; never log private task data.
            if not completed.cancelled(): completed.exception()
        task.add_done_callback(finished)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)

    async def authenticate(self, app, account):
        try:
            response = await app.state.profile_client.get('/api/v1/profile/auth/session',
                headers={'Authorization': account['authorization']})
            data = response.json() if response.status_code == 200 else {}
            if response.status_code == 401:
                raise CvError('Your session ended. Sign in again to finish this saved action.', 401)
            if data.get('id') != account['id'] or data.get('email_verified') is not True:
                raise CvError('Session verification is unavailable. Your message is saved; retry.', 503)
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise CvError('Session verification is unavailable. Your message is saved; retry.', 503) from exc

    def get(self, owner, identifier):
        document = self.repository.get(owner, identifier)
        if document is None: raise Missing()
        return document

    def update(self, owner, identifier, transform):
        for _ in range(8):
            previous = self.get(owner, identifier)
            document = deepcopy(previous)
            transform(document)
            if document == previous: return previous
            document['revision'] += 1
            document['updated_at'] = now()
            document['message_count'] = len(document['messages'])
            document['at_capacity'] = at_capacity(document)
            if len(BSON.encode(document)) > 8 * 1024 * 1024:
                raise Conflict('This conversation has reached its saved history capacity. Its messages are retained.')
            try: return self.repository.replace(previous, document)
            except Conflict: continue
        raise Conflict('The conversation is receiving another update. Refresh and retry your saved draft.')

    def start(self, owner, mutation):
        if mutation.cv_id: self.cv.get(owner, mutation.cv_id)
        previous = self.repository.latest(owner, mutation.cv_id)
        if previous and not at_capacity(previous): return previous
        if previous and any(a['status'] in {'pending', 'awaiting_confirmation', 'needs_source', 'failed'}
                for m in previous['messages'] for a in m.get('actions', [])):
            return previous  # Finish/cancel recoverable actions before rolling over.
        if self.repository.count(owner, mutation.cv_id) >= MAX_SEGMENTS:
            raise Conflict('This CV conversation has reached its history capacity. Saved history remains available.')
        document = {'_id': str(uuid4()), 'user_id': owner, 'cv_id': mutation.cv_id,
            'context_key': mutation.cv_id or 'manual-only', 'segment': previous['segment'] + 1 if previous else 1,
            'previous_conversation_id': previous['_id'] if previous else None, 'revision': 1,
            'created_at': now(), 'updated_at': now(), 'receipts': {}, 'messages': [],
            'active_question': previous.get('active_question') if previous else None,
            'last_item_id': previous.get('last_item_id') if previous else None,
            'context': previous.get('context') if previous else None}
        text = ('Welcome back. Your earlier conversation is available in history.' if previous else
            'Upload or choose a CV, then review it with me. You can ask questions, add context or correct a detail at any time.'
            if mutation.cv_id else 'Tell me about a capability you would like to add. You do not need to upload a CV.')
        document['messages'].append(make_message(document, 'assistant', text))
        document.update(message_count=1, at_capacity=False)
        return self.repository.insert(document)

    async def context(self, app, authorization):
        raw = await app.state.target_provider.selected_context(authorization)
        return ConfirmedContext.model_validate(raw).model_dump(mode='json') if raw is not None else None

    async def refresh(self, app, account, identifier):
        previous = self.get(account['id'], identifier)
        context, error = None, None
        if previous['cv_id']:
            try: context = await self.context(app, account['authorization'])
            except CvError as exc:
                if exc.status in {401, 403}: raise
                error = 'Career context is unavailable. Your conversation is saved; retry to prepare relevant questions.'
        document = self.cv.get(account['id'], previous['cv_id']) if previous['cv_id'] else None
        def transform(current):
            active = current.get('active_question')
            if active:
                available = envelope(document, context) if document else {'questions': []}
                valid = next((q for q in available['questions'] if q['id'] == active['id'] and
                    q['status'] == 'unanswered' and not q.get('reconciliation_required')), None)
                if (current.get('context') != context or not valid or document['operation']['status'] != 'ready'
                        or document.get('candidate')):
                    current['active_question'] = None
            current['context'], current['context_error'] = context, error
        return await run_in_threadpool(self.update, account['id'], identifier, transform)

    def snapshot(self, owner, conversation, context):
        doc = self.cv.get(owner, conversation['cv_id']) if conversation['cv_id'] else None
        selection = self.cv.repository.selection(owner)
        return {'cv_version': doc['version'] if doc else None,
                'extraction_version': doc['extraction_version'] if doc else None,
                'selection': {'cv_id': selection['selected_cv_id'], 'version': selection['version']},
                'target': context_identity(ConfirmedContext.model_validate(context)) if context else None}

    async def check_snapshot(self, app, account, conversation, snapshot, target=True):
        current = (await self.context(app, account['authorization']) if conversation['cv_id'] else None) if target else conversation.get('context')
        latest = await run_in_threadpool(self.snapshot, account['id'], conversation, current)
        if latest != snapshot:
            raise Conflict('The CV, selected source or Career target changed. Your message is retained; review the current context before trying again.')
        return current

    def route(self, payload):
        if not self.slots.acquire(blocking=False):
            raise ValueError('Chat interpretation is busy. Your message is saved; retry shortly.')
        try: return self.provider.route(payload)
        finally: self.slots.release()

    async def send(self, app, account, identifier, mutation):
        owner, receipt_id = account['id'], str(mutation.mutation_id)
        fingerprint = digest(mutation.model_dump(mode='json'))
        previous = self.get(owner, identifier)
        receipt = previous['receipts'].get(receipt_id)
        if receipt:
            if receipt['fingerprint'] != fingerprint: raise Conflict('This message key was already used for different text.')
            return previous
        context = await self.context(app, account['authorization']) if previous['cv_id'] else None
        snapshot = await run_in_threadpool(self.snapshot, owner, previous, context)
        if mutation.item_id:
            self.source(owner, previous, mutation.item_id)
        token, route_id = str(uuid4()), key(identifier + ':' + receipt_id + ':route')
        def save(document):
            if receipt_id in document['receipts']:
                if document['receipts'][receipt_id]['fingerprint'] != fingerprint: raise Conflict('This message key was already used.')
                return
            if document['revision'] != mutation.expected_revision:
                raise Conflict('New messages arrived. Refresh; your unsent text can be sent against the latest conversation.')
            if at_capacity(document):
                raise Conflict('This conversation segment is full. Open the conversation again to start a new segment with history retained.')
            document['messages'].append(make_message(document, 'user', mutation.text))
            action = {'id': route_id, 'kind': 'route', 'status': 'pending', 'title': 'Understand your message',
                'summary': 'Your message is saved. Understanding it now.', 'error': None,
                '_token': token, '_lease_until': now() + LEASE_SECONDS,
                '_text': mutation.text, '_command': mutation.command, '_item_id': mutation.item_id,
                '_snapshot': snapshot, '_turn_id': receipt_id}
            if mutation.command == 'skip':
                action['_guided_question_id'] = ((document.get('active_question') or {}).get('id')
                    if document.get('context') == context else None)
            document['messages'].append(make_message(document, 'assistant', 'Your message is saved. Working on it…', [action]))
            document['receipts'][receipt_id] = {'fingerprint': fingerprint, 'action_id': route_id}
            if document.get('context') != context: document['active_question'] = None
            document['context'] = context
        saved = await run_in_threadpool(self.update, owner, identifier, save)
        if action_in(saved, route_id).get('_token') != token: return saved
        await self.dispatch(self.process(app, account, identifier, route_id, token), owner, identifier, route_id, token)
        return self.get(owner, identifier)

    def source(self, owner, conversation, item_id, allow_removed=False):
        if not conversation['cv_id']: raise CvError('Choose a CV before referring to an extracted item.')
        doc = self.cv.get(owner, conversation['cv_id'])
        item = next((i for i in effective_items(doc) if i['id'] == item_id and (allow_removed or not i['removed'])), None)
        if item is None: raise Missing()
        return doc, item

    def routing_payload(self, owner, conversation, route):
        document = self.cv.get(owner, conversation['cv_id']) if conversation['cv_id'] else None
        items = effective_items(document) if document else []
        # Identity summaries establish references. Only a deliberately focused
        # source gets its fuller context; the interpreter later sees that source.
        summaries = [{'id': i['id'], 'kind': i['kind'], 'title': i['title'],
            'description': i['description'][:120], 'skill_names': [n[:60] for n in i['skill_names'][:4]]}
            for i in items if not i['removed']]
        focused_id = route.get('_item_id') or (conversation.get('active_question') or {}).get('item_id') or conversation.get('last_item_id')
        focus = next((i for i in items if i['id'] == focused_id and not i['removed']), None)
        result = {'task': 'cv_conversation', 'message': route['_text'],
            'active_question': conversation.get('active_question'),
            'explicit_item_id': route.get('_item_id'), 'last_item_id': conversation.get('last_item_id'),
            'items': summaries,
            'focused_source': {field: focus.get(field) for field in ('id', 'kind', 'title', 'description', 'start_date', 'end_date', 'ongoing')} if focus else None,
            'questions': [{field: q.get(field) for field in ('id', 'item_id', 'uncertainty', 'status', 'question')}
                for q in (document['clarifications'] if document else []) if not q.get('reconciliation_required')][-100:],
            'target': {k: v for k, v in (conversation.get('context') or {}).items() if k in {'id', 'type', 'role', 'field', 'skill_ids'}},
            'history': [{'role': m['role'], 'text': m['text'][:600]} for m in conversation['messages'][-6:-2]]}
        if len(json.dumps(result, ensure_ascii=False).encode()) > 96 * 1024:
            result['items'] = [{k: value for k, value in i.items() if k in {'id', 'kind', 'title'}} for i in summaries]
        if len(json.dumps(result, ensure_ascii=False).encode()) > 96 * 1024:
            raise ValueError('This source is too large to route safely. Choose an item in the CV summary and send a focused message.')
        return result

    async def process(self, app, account, identifier, route_id, token):
        owner = account['id']
        conversation = self.get(owner, identifier)
        route = deepcopy(action_in(conversation, route_id))
        try:
            await self.authenticate(app, account)
            if route.get('_command'):
                await self.guided(app, account, conversation, route, token)
                return
            payload = await run_in_threadpool(self.routing_payload, owner, conversation, route)
            result, metadata = await run_in_threadpool(self.route, payload)
            result = ConversationRoute.model_validate(result)
            # Validate the whole response before any mutation or confirmation card.
            allowed_ids = {item['id'] for item in payload['items']}
            source_document = self.cv.get(owner, conversation['cv_id']) if conversation['cv_id'] else None
            items = {item['id']: item for item in effective_items(source_document) if not item['removed']} if source_document else {}
            questions = {q['id']: q for q in payload['questions']}
            actions = []
            for index, proposed in enumerate(result.actions):
                if proposed.excerpt not in route['_text']:
                    raise ValueError('Chat interpretation referred to words you did not send. Your message is saved; retry.')
                if proposed.item_id and (proposed.item_id not in items or proposed.item_id not in allowed_ids): raise ValueError('Chat interpretation referred to an unavailable source.')
                if any(i not in items or i not in allowed_ids for i in proposed.candidate_item_ids): raise ValueError('Chat interpretation returned an invalid source choice.')
                if proposed.question_id and (proposed.question_id not in questions or
                        (proposed.item_id and questions[proposed.question_id]['item_id'] != proposed.item_id)):
                    raise ValueError('Chat interpretation referred to a different clarification.')
                if proposed.kind == 'add_capability' and normalized_name(proposed.name) not in normalized_name(proposed.excerpt):
                    raise ValueError('A manual capability must be named in your own explanation.')
                actions.append(self.proposal(conversation, route, proposed, index, items, questions))
            if actions:
                await self.check_snapshot(app, account, conversation, route['_snapshot'])
            def publish(document):
                current = action_in(document, route_id)
                self.check_lease(current, token)
                message = action_message(document, route_id)
                message['text'] = result.reply
                current.update(status='saved', summary='Message understood.', _token=None, _lease_until=0, _metadata=metadata)
                message['actions'].extend(actions)
            await run_in_threadpool(self.update, owner, identifier, publish)
            for action in actions:
                if action['status'] == 'pending':
                    await self.execute(app, account, identifier, action['id'])
        except Conflict as exc:
            await self.fail(owner, identifier, route_id, token, exc.detail, 'stale')
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, ValidationError) else 'Chat interpretation could not finish. Your message is saved; retry.'
            await self.fail(owner, identifier, route_id, token, message[:1000])

    @staticmethod
    def check_lease(action, token):
        if action.get('_token') != token or action.get('_lease_until', 0) <= now():
            raise Conflict('A newer attempt has taken over this saved message. Refresh its current status.')

    async def fail(self, owner, identifier, action_id, token, message, status='failed'):
        def transform(document):
            action = action_in(document, action_id)
            if action['status'] in {'saved', 'cancelled'}: return
            if action.get('_token') != token: return
            action.update(status=status, error=message, summary=message, _token=None, _lease_until=0)
            if action['kind'] == 'route': action_message(document, action_id)['text'] = message
        return await run_in_threadpool(self.update, owner, identifier, transform)

    def proposal(self, conversation, route, proposed, index, items, questions):
        data = proposed.model_dump(mode='json')
        item_id = proposed.item_id or route.get('_item_id')
        if not item_id and proposed.question_id: item_id = questions[proposed.question_id]['item_id']
        if not item_id and proposed.kind in {'clarify', 'correct', 'skip'} and not proposed.candidate_item_ids:
            active = conversation.get('active_question')
            item_id = active['item_id'] if active else None
        if proposed.kind == 'add_capability': item_id = None
        item = items.get(item_id)
        kind = proposed.kind
        status = 'pending' if kind in {'clarify', 'skip'} else 'awaiting_confirmation'
        candidates = proposed.candidate_item_ids or list(items)
        if kind != 'add_capability' and item is None:
            if not candidates: raise ValueError('Choose a CV source before clarifying this detail. Your message is saved.')
            status = 'needs_source'
        labels = {'clarify': 'Save your explanation', 'correct': 'Review this correction',
            'remove': 'Remove this item', 'add_capability': 'Add a capability', 'skip': 'Skip this question'}
        changes = [{'field': field.replace('_', ' '), 'before': self.display(item.get(field)) if item else None,
                    'after': self.display(value)} for field, value in proposed.fields.items()]
        if kind == 'correct' and not changes:
            changes = [{'field': 'Clarification', 'before': 'Earlier explanation remains in history', 'after': proposed.excerpt}]
        if kind == 'add_capability':
            changes = [{'field': 'Capability', 'before': None, 'after': proposed.name},
                       {'field': 'Your explanation', 'before': None, 'after': proposed.excerpt}]
        return {'id': key(conversation['_id'] + ':' + route['_turn_id'] + ':' + str(index)),
            'kind': kind, 'status': status, 'title': labels[kind], 'summary': proposed.excerpt,
            'item_id': item_id, 'item_title': item['title'] if item else None,
            'question_id': proposed.question_id, 'changes': changes,
            'choices': [{'id': i, 'label': items[i]['title'], 'description': items[i]['kind'] + ' · ' + i,
                         'kind': 'item'} for i in candidates] if status == 'needs_source' else [],
            'error': None, '_payload': data, '_text': route['_text'], '_snapshot': deepcopy(route['_snapshot']),
            '_turn_id': route['_turn_id'], '_lease_until': 0, '_queued_at': now(), '_token': None}

    @staticmethod
    def display(value):
        if value is None: return 'Unknown'
        if isinstance(value, bool): return 'Yes' if value else 'No'
        return str(value)

    async def guided(self, app, account, conversation, route, token):
        owner, command = account['id'], route['_command']
        await self.authenticate(app, account)
        expected = deepcopy(route['_snapshot'])
        document = self.cv.get(owner, conversation['cv_id']) if conversation['cv_id'] else None
        if document and any(key(route['id'] + suffix) in document['receipts'] for suffix in (':skip', ':prepare')):
            # Only receipts for this guided turn may advance its CV snapshot.
            # Selection, extraction and confirmed target must still match.
            expected['cv_version'] = document['version']
        await self.check_snapshot(app, account, conversation, expected)
        active = conversation.get('active_question')
        skipped = False
        if not conversation['cv_id']:
            text, active = 'You can add a capability here without a CV. Upload or choose a CV to review extracted information.', None
        else:
            skip = route.get('_guided_skip')
            question_id = skip['question_id'] if skip else route.get('_guided_question_id')
            if command == 'skip' and question_id:
                skip = skip or {'question_id': question_id, 'body': {
                    'expected_version': document['version'], 'mutation_id': key(route['id'] + ':skip'), 'action': 'skip'}}
                skip = await run_in_threadpool(self.remember_guided, owner, conversation['_id'], route['id'],
                    '_guided_skip', skip, token)
                document = await run_in_threadpool(answer, self.cv, owner, conversation['cv_id'], skip['question_id'],
                    AnswerMutation.model_validate(skip['body']))
                skipped = next(q for q in document['clarifications'] if q['id'] == skip['question_id'])['status'] == 'skipped'
            context = conversation.get('context')
            if not context:
                text, active = 'Your CV is saved. You can ask questions or correct details here. Confirm a target in Career to review questions that matter to that target.', None
            elif document['operation']['status'] != 'ready' or document.get('candidate'):
                text, active = 'Finish processing or review the source comparison first. Your saved conversation is retained.', None
            elif any(q.get('interpretation_status') in {'pending', 'failed'} and not q.get('reconciliation_required') for q in document['clarifications']):
                text, active = 'Your saved explanation still needs interpretation. Wait for it to finish, or retry its saved action before preparing more questions.', None
            else:
                current_context = await self.context(app, account['authorization'])
                if current_context != context: raise Conflict('Your Career target changed. Refresh before reviewing questions.')
                operation = route.get('_guided_prepare') or {
                    'expected_version': document['version'], 'mutation_id': key(route['id'] + ':prepare'),
                    'career_target_id': context['id'], 'career_target_version': context['version'],
                    'career_target_selection_version': context['selection_version']}
                operation = await run_in_threadpool(self.remember_guided, owner, conversation['_id'], route['id'],
                    '_guided_prepare', operation, token)
                prepared = await run_in_threadpool(prepare, self.cv, owner, conversation['cv_id'],
                    PrepareMutation.model_validate(operation), context)
                again = await self.context(app, account['authorization'])
                if again != context: raise Conflict('Your Career target changed while preparing questions. Refresh to continue.')
                document = self.cv.get(owner, conversation['cv_id'])
                items = {i['id']: i for i in effective_items(document) if not i['removed']}
                pending = [q for q in prepared['questions'] if q['status'] == 'unanswered' and
                           not q.get('reconciliation_required') and q['item_id'] in items]
                question = next((q for q in pending if route.get('_item_id') == q['item_id']), pending[0] if pending else None)
                active = ({'id': question['id'], 'item_id': question['item_id'],
                    'title': items[question['item_id']]['title'], 'question': question['question']} if question else None)
                text = (f"{active['title']}: {active['question']}" if active else
                    'No relevant unanswered questions remain. You can add context, correct a detail or continue with what is known. This does not complete an assessment.')
                if command == 'skip' and question_id:
                    text = ('Skipped; that detail remains unknown. ' if skipped else
                        'The existing answer was retained; nothing was skipped. ') + text
        def publish(current):
            action = action_in(current, route['id'])
            self.check_lease(action, token)
            action.update(status='saved', summary='Review updated.', _token=None, _lease_until=0)
            current['active_question'] = active
            if active: current['last_item_id'] = active['item_id']
            action_message(current, route['id'])['text'] = text
        await run_in_threadpool(self.update, owner, conversation['_id'], publish)

    def remember_guided(self, owner, identifier, action_id, field, operation, token):
        def transform(document):
            action = action_in(document, action_id)
            self.check_lease(action, token)
            action.setdefault(field, operation)
        saved = self.update(owner, identifier, transform)
        return action_in(saved, action_id)[field]

    async def execute(self, app, account, identifier, action_id, decision=None):
        owner, token = account['id'], str(uuid4())
        conversation = self.get(owner, identifier)
        original = deepcopy(action_in(conversation, action_id))
        if original['status'] in {'saved', 'cancelled'}: return conversation
        try:
            await self.authenticate(app, account)
            expected = deepcopy(original['_snapshot'])
            cv_document = self.cv.get(owner, conversation['cv_id']) if conversation['cv_id'] else None
            applied = bool(cv_document and key(action_id + ':apply') in cv_document['receipts'])
            created = bool(cv_document and key(action_id + ':question-create') in cv_document['receipts'])
            if applied or created:
                # Recover only an exact durable operation belonging to this action.
                # Extraction/selection/target identities are still checked below.
                expected['cv_version'] = cv_document['version']
                question_id = original.get('_saved_question_id') or key(action_id + ':question')
                if any(q['id'] == question_id for q in cv_document['clarifications']):
                    original['_saved_question_id'] = question_id
            await self.check_snapshot(app, account, conversation, expected)
            if original['kind'] == 'add_capability':
                return await self.manual(app, account, conversation, original, decision, token)
            document, item = self.source(owner, conversation, original['item_id'],
                allow_removed=applied and original['kind'] == 'remove')
            action = deepcopy(original)
            action['_snapshot']['cv_version'] = document['version']
            def claim(current):
                current_action = action_in(current, action_id)
                if current_action['status'] in {'saved', 'cancelled'}: return
                if current_action.get('_lease_until', 0) > now(): raise Conflict('This action is still saving. Wait briefly before retrying.')
                current_action.update(status='pending', _token=token, _lease_until=now() + LEASE_SECONDS)
            claimed = await run_in_threadpool(self.update, owner, identifier, claim)
            if action_in(claimed, action_id).get('_token') != token: return claimed
            payload = action['_payload']
            if action['kind'] == 'remove' or (action['kind'] == 'correct' and payload['fields']):
                body = action.get('_cv_mutation') or {'expected_version': document['version'],
                    'mutation_id': key(action_id + ':apply'), 'action': 'remove' if action['kind'] == 'remove' else 'update',
                    **(payload['fields'] if action['kind'] == 'correct' else {})}
                mutation = ItemMutation.model_validate(body)
                await run_in_threadpool(self.remember_mutation, owner, identifier, action_id, body)
                saved = await run_in_threadpool(self.cv.edit, owner, conversation['cv_id'], item['id'], mutation)
                summary = 'Removed this item from current CV evidence.' if action['kind'] == 'remove' else 'Saved the correction. Original details remain in history.'
            else:
                saved, summary = await self.clarify(app, account, conversation, action, document, item)
            def completed(current):
                current_action = action_in(current, action_id)
                self.check_lease(current_action, token)
                question = next((q for q in saved['clarifications'] if q['id'] == current_action.get('_saved_question_id')), None)
                pending = question and question.get('interpretation_status') != 'ready' and action['kind'] != 'skip'
                current_action.update(status='failed' if pending else 'saved', summary=summary,
                    error=question.get('interpretation_error') if pending else None, _token=None, _lease_until=0)
                current_action['_snapshot']['cv_version'] = saved['version']
                current['last_item_id'] = item['id']
                # Only our acknowledged write may advance sibling action snapshots.
                for message in current['messages']:
                    for other in message.get('actions', []):
                        if other.get('_turn_id') == action['_turn_id'] and other['id'] != action_id and other.get('_snapshot') == original['_snapshot']:
                            other['_snapshot']['cv_version'] = saved['version']
                if current.get('active_question') and current['active_question']['item_id'] == item['id']:
                    q = next((q for q in saved['clarifications'] if q['id'] == current['active_question']['id']), None)
                    if q and q['status'] in {'answered', 'skipped'}: current['active_question'] = None
            await run_in_threadpool(self.update, owner, identifier, completed)
        except Conflict as exc:
            # The saved CV receipt may already exist after a process/response failure;
            # recovery uses the stored exact mutation payload rather than a new write.
            latest_token = action_in(self.get(owner, identifier), action_id).get('_token')
            await self.fail(owner, identifier, action_id, token if latest_token == token else original.get('_token'), exc.detail, 'stale')
        except Exception as exc:
            message = exc.detail if isinstance(exc, CvError) else 'This action could not finish. Your message is saved; retry.'
            latest_token = action_in(self.get(owner, identifier), action_id).get('_token')
            await self.fail(owner, identifier, action_id, token if latest_token == token else original.get('_token'), message)
        return self.get(owner, identifier)

    def remember_mutation(self, owner, identifier, action_id, body):
        def transform(document): action_in(document, action_id)['_cv_mutation'] = body
        return self.update(owner, identifier, transform)

    async def clarify(self, app, account, conversation, action, document, item):
        owner, cv_id = account['id'], conversation['cv_id']
        if action['kind'] == 'skip':
            question_id = action.get('_saved_question_id') or action.get('question_id')
            if not question_id:
                active = conversation.get('active_question')
                if active and active['item_id'] == item['id']: question_id = active['id']
            question = next((q for q in document['clarifications'] if q['id'] == question_id and
                q['item_id'] == item['id'] and not q.get('reconciliation_required')), None)
            if not question: raise CvError('There is no current question to skip. Your other answers remain saved.')
            body = action.get('_cv_mutation') or {'expected_version': document['version'],
                'mutation_id': key(action['id'] + ':apply'), 'action': 'skip'}
            def remember_skip(current):
                candidate = action_in(current, action['id'])
                candidate.update(_saved_question_id=question_id, question_id=question_id, _cv_mutation=body)
            await run_in_threadpool(self.update, owner, conversation['_id'], remember_skip)
            result = await run_in_threadpool(answer, self.cv, owner, cv_id, question_id,
                AnswerMutation.model_validate(body))
            skipped = next(q for q in result['clarifications'] if q['id'] == question_id)['status'] == 'skipped'
            return result, ('Skipped; this detail remains unknown. Earlier answers remain saved.' if skipped else
                'This question already has a saved answer. It was retained; nothing was skipped.')
        loop = asyncio.get_running_loop()
        coordinator = self
        class SessionInterpreter:
            def interpret(self, *args):
                result = app.state.interpreter.interpret(*args)
                # A provider request may outlive sign-out. Verify again immediately
                # before returning facts to the existing fenced publication path.
                asyncio.run_coroutine_threadsafe(coordinator.authenticate(app, account), loop).result(timeout=8)
                return result
        interpreter = SessionInterpreter()
        question_id = action.get('_saved_question_id')
        recovered_unanswered = None
        if question_id:
            question = next((q for q in document['clarifications'] if q['id'] == question_id), None)
            if question and question['interpretation_status'] == 'ready': return document, question['interpretation']['summary']
            if question and question['status'] == 'answered':
                result = await run_in_threadpool(retry_interpretation, self.cv, owner, cv_id, question_id,
                    Mutation(expected_version=document['version'], mutation_id=key(action['id'] + ':interpret:' + str(document['version']))), interpreter)
                q = next(q for q in result['clarifications'] if q['id'] == question_id)
                return result, self.answer_summary(q)
            if question and question['status'] == 'unanswered': recovered_unanswered = question
        requested = action.get('question_id')
        question = recovered_unanswered or next((q for q in document['clarifications'] if q['id'] == requested and q['item_id'] == item['id'] and not q.get('reconciliation_required')), None)
        if not question:
            active = conversation.get('active_question')
            if active and active['item_id'] == item['id']:
                question = next((q for q in document['clarifications'] if q['id'] == active['id']), None)
        if any(q['item_id'] == item['id'] and q.get('interpretation_status') in {'pending', 'failed'}
                and not q.get('reconciliation_required') for q in document['clarifications']):
            raise Conflict('An earlier explanation for this source still needs interpretation. Finish or retry it first; this new message remains saved.')
        # Shared CV history snapshots are intentionally unchanged in this slice.
        # Reserve all three publication steps before creating an unanswered event,
        # so a long history cannot accept half a turn and then exhaust the source.
        history_bytes = len(BSON.encode({'clarifications': document['clarifications'],
            'overlays': document['overlays'], 'prepared_context': document.get('prepared_context')}))
        if len(BSON.encode(document)) + 3 * history_bytes + 512 * 1024 > 12 * 1024 * 1024:
            raise CvError('This CV has reached its saved history limit for another complete explanation. Your message is retained; keep this source for history and use a new saved CV.', 409)
        # An appended statement is a separate source-bound event, never replacement
        # of the previous answer. Its interpretation changes only explicitly named
        # fields; old evidence survives even after cumulative text exceeds 4000 chars.
        if not recovered_unanswered and (not question or question['status'] != 'unanswered' or action['kind'] == 'correct'):
            parent = question or next((q for q in reversed(document['clarifications']) if q['item_id'] == item['id'] and not q.get('reconciliation_required')), None)
            question_id = key(action['id'] + ':question')
            def add_question(doc):
                if any(q['id'] == question_id for q in doc['clarifications']): return
                if len(doc['clarifications']) >= 800:
                    raise CvError('This CV has reached its clarification history capacity. Saved answers remain available; use a new saved source for additional review.', 409)
                if any(q['item_id'] == item['id'] and q.get('reconciliation_required') for q in doc['clarifications']):
                    raise Conflict('Review changed-source clarifications before adding more context to this item.')
                context = conversation.get('context') or {}
                doc['clarifications'].append({'id': question_id, 'item_id': item['id'],
                    'kind': 'project' if item['kind'] == 'project' else 'work' if item['kind'] == 'experience' else 'other',
                    'question': 'What additional or corrected facts are you stating about this source?',
                    'uncertainty_key': digest({'conversation_action': action['id']}), 'uncertainty': 'claim',
                    'status': 'unanswered', 'answer': None, 'career_target_id': context.get('id'),
                    'career_target_version': context.get('version'), 'career_target_type': context.get('type'),
                    'extraction_version': doc['extraction_version'], 'reconciliation_required': False,
                    'answer_revision': 0, 'answer_sequence': 0, 'interpretation_status': 'not_requested',
                    'interpretation_error': None, 'resolution': 'unresolved', 'interpretation': None,
                    'followup_of': parent['id'] if parent else None})
            document = await run_in_threadpool(self.cv.mutate, owner, cv_id,
                Mutation(expected_version=document['version'], mutation_id=key(action['id'] + ':question-create')),
                'chat-question:' + action['id'], add_question)
        else: question_id = question['id']
        def remember(current):
            saved_action = action_in(current, action['id'])
            saved_action['_saved_question_id'] = question_id
            saved_action['question_id'] = question_id
            saved_action['_snapshot']['cv_version'] = document['version']
            saved_action['_cv_mutation'] = {'expected_version': document['version'],
                'mutation_id': key(action['id'] + ':apply'), 'action': 'answer', 'answer': action['_text']}
        await run_in_threadpool(self.update, owner, conversation['_id'], remember)
        result = await run_in_threadpool(answer, self.cv, owner, cv_id, question_id,
            AnswerMutation(expected_version=document['version'], mutation_id=key(action['id'] + ':apply'),
                           action='answer', answer=action['_text']), interpreter)
        q = next(q for q in result['clarifications'] if q['id'] == question_id)
        return result, self.answer_summary(q)

    @staticmethod
    def answer_summary(question):
        if question.get('interpretation_status') == 'ready':
            return 'Saved: ' + question['interpretation']['summary']
        return 'Your explanation is saved. Its interpretation still needs attention; retry to finish.'

    async def manual(self, app, account, conversation, action, decision, token):
        headers = {'Authorization': account['authorization']}
        response = await app.state.profile_client.get('/api/v1/profile/capabilities', headers=headers)
        if response.status_code != 200: raise CvError('Manual capabilities are unavailable. Your proposed addition is saved; retry.', 503)
        current = response.json()
        if type(current.get('version')) is not int or not isinstance(current.get('declarations'), list):
            raise CvError('Manual capabilities returned an invalid response. Your message is saved.', 503)
        proposed = action['_payload']
        name, description = proposed['name'], proposed['excerpt']
        if len(description) > 2000: raise CvError('A manual capability explanation can contain up to 2000 characters. Send a shorter description; your original message remains saved.')
        matches = [d for d in current['declarations'] if normalized_name(d['name']) == normalized_name(name)]
        cv_matches = []
        if conversation['cv_id']:
            doc = self.cv.get(account['id'], conversation['cv_id'])
            cv_matches = [i for i in effective_items(doc) if not i['removed'] and normalized_name(name) in
                {normalized_name(n) for n in i.get('skill_names', [])}]
        choices = [{'id': d['id'], 'label': d['name'], 'description': d['description'][:500], 'kind': 'declaration'} for d in matches]
        choices += [{'id': i['id'], 'label': i['title'], 'description': i['description'][:500], 'kind': 'item'} for i in cv_matches]
        if choices and (decision is None or decision.mode is None) and not action.get('_manual_body'):
            def matching(document):
                candidate = action_in(document, action['id'])
                candidate.update(status='awaiting_confirmation', choices=choices,
                    summary='Matching evidence exists. Choose attach to existing evidence or keep a distinct capability.',
                    _declarations_version=current['version'])
            return await run_in_threadpool(self.update, account['id'], conversation['_id'], matching)
        mode = decision.mode if decision and decision.mode else 'new'
        body = {'expected_version': current['version'], 'mutation_id': key(action['id'] + ':manual'),
                'name': name, 'description': description, 'mode': mode}
        if mode == 'attach':
            if decision.attach_to_id and decision.attach_to_id in {d['id'] for d in matches}:
                body['attach_to_id'] = decision.attach_to_id
            elif decision.item_id and decision.item_id in {i['id'] for i in cv_matches}:
                body['cv_match'] = {'cv_id': conversation['cv_id'], 'item_id': decision.item_id, 'cv_version': doc['version']}
            else: raise CvError('Choose one of the matching sources before attaching this capability.')
        if action.get('_manual_body'):
            # Lost response recovery repeats exactly the same body and idempotency key.
            body = action['_manual_body']
        def claim(document):
            candidate = action_in(document, action['id'])
            if candidate['status'] in {'saved', 'cancelled'}: return
            if candidate.get('_lease_until', 0) > now(): raise Conflict('This capability is still saving. Wait before retrying.')
            if candidate.get('_declarations_version') is not None and candidate['_declarations_version'] != current['version'] and not candidate.get('_manual_body'):
                raise Conflict('Manual capabilities changed. Review matching evidence again before saving.')
            candidate.update(status='pending', _manual_body=body, _token=token, _lease_until=now() + LEASE_SECONDS)
        claimed = await run_in_threadpool(self.update, account['id'], conversation['_id'], claim)
        if action_in(claimed, action['id']).get('_token') != token: return claimed
        result = await app.state.profile_client.post('/api/v1/profile/capabilities', headers=headers, json=body)
        if result.status_code == 409:
            raise Conflict('Manual capability evidence changed. Refresh and review the saved matching choices before retrying.')
        if result.status_code != 200: raise CvError('The manual capability could not be saved. Your proposal remains available; retry.', 503)
        def finish(document):
            candidate = action_in(document, action['id'])
            self.check_lease(candidate, token)
            candidate.update(status='saved', summary='Saved your manual capability to your account. It remains available when you change CVs.', error=None,
                             _token=None, _lease_until=0)
        return await run_in_threadpool(self.update, account['id'], conversation['_id'], finish)

    async def decide(self, app, account, identifier, action_id, mutation):
        owner, receipt_id = account['id'], str(mutation.mutation_id)
        fingerprint = digest({'action_id': action_id, **mutation.model_dump(mode='json')})
        previous = self.get(owner, identifier)
        if receipt_id in previous['receipts']:
            if previous['receipts'][receipt_id]['fingerprint'] != fingerprint: raise Conflict('This action key was already used for another request.')
            return previous
        candidate = action_in(previous, action_id)
        if candidate['status'] in {'saved', 'cancelled'}: return previous
        if candidate.get('_lease_until', 0) > now(): raise Conflict('This saved action is still processing. Interrupted work becomes retryable after 90 seconds.')
        if candidate['status'] == 'pending' and not candidate.get('_lease_until') and candidate.get('_queued_at', 0) + LEASE_SECONDS > now():
            raise Conflict('This action is queued. Wait briefly before retrying.')
        if candidate['status'] in {'awaiting_confirmation', 'needs_source'} and mutation.decision == 'retry':
            raise CvError('Review this proposal and explicitly save or cancel it.')
        token = str(uuid4())
        context = await self.context(app, account['authorization']) if previous['cv_id'] else None
        def choose(document):
            if document['revision'] != mutation.expected_revision:
                raise Conflict('The conversation changed. Refresh and review this action again.')
            action = action_in(document, action_id)
            if mutation.decision == 'cancel':
                attempted = action.get('_manual_body') or action.get('_cv_mutation')
                action.update(status='cancelled', summary=(
                    'Stopped retrying this action. Previously saved facts and explanations remain; check your summary for any save that already completed.'
                    if attempted else 'Cancelled. Saved CV facts were not changed.'), error=None)
            else:
                if action['status'] == 'needs_source':
                    if mutation.item_id not in {choice['id'] for choice in action['choices']}:
                        raise CvError('Choose the source this message refers to.')
                    _, item = self.source(owner, document, mutation.item_id)
                    action['item_id'], action['item_title'] = item['id'], item['title']
                    action['_payload']['item_id'] = item['id']
                    action['choices'] = []
                    action['status'] = 'awaiting_confirmation' if action['kind'] in {'correct', 'remove'} else 'pending'
                if action['kind'] == 'route':
                    action.update(status='pending', _token=token, _lease_until=now() + LEASE_SECONDS, error=None)
                    # A stale route is reparsed from its retained original message.
                    if not (action.get('_guided_skip') or action.get('_guided_prepare')):
                        action['_snapshot'] = self.snapshot(owner, document, context)
                    document['context'] = context
                elif not (candidate['status'] == 'needs_source' and action['kind'] in {'correct', 'remove'}):
                    action.update(status='pending', _queued_at=now(), error=None)
            document['receipts'][receipt_id] = {'fingerprint': fingerprint, 'action_id': action_id}
        saved = await run_in_threadpool(self.update, owner, identifier, choose)
        action = action_in(saved, action_id)
        if mutation.decision == 'cancel': return saved
        if action['kind'] == 'route':
            await self.dispatch(self.process(app, account, identifier, action_id, token), owner, identifier, action_id, token)
        elif candidate['status'] == 'needs_source' and action['kind'] in {'correct', 'remove'}:
            # Choosing the identity is not the same as approving a correction.
            return saved
        else:
            await self.dispatch(self.execute(app, account, identifier, action_id, mutation), owner, identifier, action_id)
        return self.get(owner, identifier)

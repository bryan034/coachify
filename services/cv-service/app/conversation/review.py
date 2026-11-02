"""Explicit, target-independent CV review using the existing clarification authority."""
from copy import deepcopy
from starlette.concurrency import run_in_threadpool
from app.domain.capabilities import effective_items, digest
from app.domain.errors import Conflict, CvError
from app.schemas.cv import Mutation, AnswerMutation
from app.clarification.service import answer, question_key


def targets(document):
    for item in effective_items(document):
        if item['removed']: continue
        previous = [q for q in document['clarifications'] if q['item_id'] == item['id']
                    and not q.get('reconciliation_required')]
        if any(q.get('interpretation_status') in {'pending', 'failed'} for q in previous):
            continue
        if any(q.get('resolution') == 'unanswerable' for q in previous): continue
        for uncertainty in item.get('uncertainties', []):
            identifier = question_key(document, item['id'], uncertainty)
            if not any(q['uncertainty_key'] == identifier for q in previous):
                yield item, uncertainty, identifier, uncertainty, None
        for claim in item.get('skill_claims', []):
            if claim.get('attribution') != 'personal': continue
            for field in ('complexity', 'independence', 'recency', 'frequency', 'outcome', 'limitations'):
                if field == 'independence' and claim.get('assistance', 'unknown') != 'unknown': continue
                # Existing source generation/history participates in the identity.
                identifier = digest({'base': question_key(document, item['id'], 'claim'),
                    'skill_id': claim['skill_id'], 'profile_field': field})
                if not any(q['uncertainty_key'] == identifier for q in previous):
                    yield item, 'claim', identifier, field, claim['name']


async def guided_review(service, app, account, conversation, route, token):
    from app.conversation.service import action_in, action_message, key
    owner, identifier = account['id'], conversation['_id']
    await service.authenticate(app, account)
    document = service.cv.get(owner, conversation['cv_id'])
    if document['operation']['status'] != 'ready' or document.get('candidate'):
        raise CvError('Finish CV processing or source reconciliation before reviewing. Your conversation is saved.', 409)
    if any(q.get('interpretation_status') in {'pending', 'failed'} and not q.get('reconciliation_required')
           for q in document['clarifications']):
        raise CvError('Finish or retry your saved interpretation before continuing the review.', 409)
    reviewed = route.get('_review_mutation')
    if route['_command'] == 'finish':
        mutation = reviewed or {'expected_version': document['version'], 'mutation_id': key(route['id'] + ':finish')}
        def remember(current):
            service.check_lease(action_in(current, route['id']), token)
            action_in(current, route['id'])['_review_mutation'] = mutation
        await run_in_threadpool(service.update, owner, identifier, remember)
        document = await run_in_threadpool(service.cv.mark_profile_reviewed, owner, document['_id'], Mutation.model_validate(mutation))
        text, active = 'Your reviewed CV profile is saved. Unanswered details remain uncertain. Return to the summary whenever you are ready.', None
    else:
        active = conversation.get('active_question')
        if route['_command'] == 'skip' and active:
            operation = route.get('_review_skip') or {'expected_version': document['version'],
                'mutation_id': key(route['id'] + ':skip'), 'action': 'skip'}
            def remember(current):
                service.check_lease(action_in(current, route['id']), token)
                action_in(current, route['id'])['_review_skip'] = operation
            await run_in_threadpool(service.update, owner, identifier, remember)
            document = await run_in_threadpool(answer, service.cv, owner, document['_id'], active['id'],
                                               AnswerMutation.model_validate(operation))
            active = None
        available = {q['id']: q for q in document['clarifications'] if q['status'] == 'unanswered'
                     and not q.get('reconciliation_required')}
        existing_active = available.get((active or {}).get('id'))
        saved_question = route.get('_review_question')
        if saved_question:
            item = next((i for i in effective_items(document) if i['id'] == saved_question['item_id'] and not i['removed']), None)
            if not item or saved_question['extraction_version'] != document['extraction_version']:
                raise Conflict('The reviewed source changed. Refresh before continuing.')
        elif existing_active:
            saved_question = existing_active
        else:
            target = next(targets(document), None)
            if target:
                item, uncertainty, uncertainty_key, field, skill = target
                result, _ = await run_in_threadpool(service.route, owner, {'task': 'cv_review_question',
                    'target': {'source_title': item['title'], 'source_description': item['description'],
                               'skill': skill, 'field': field, 'uncertainty': uncertainty},
                    'instruction': 'Ask about the stated source only. Complexity means concrete task scope, not an invented rating. Do not infer skill use from employment dates.'})
                question_text = result['reply'] if isinstance(result, dict) else result.reply
                saved_question = {'id': key(document['_id'] + ':profile:' + uncertainty_key), 'item_id': item['id'],
                    'kind': 'project' if item['kind'] == 'project' else 'work' if item['kind'] == 'experience' else 'other',
                    'question': question_text, 'uncertainty_key': uncertainty_key, 'uncertainty': uncertainty,
                    'status': 'unanswered', 'answer': None, 'career_target_id': None, 'career_target_version': None,
                    'career_target_type': None, 'extraction_version': document['extraction_version'],
                    'reconciliation_required': False, 'answer_revision': 0, 'answer_sequence': 0,
                    'interpretation_status': 'not_requested', 'interpretation_error': None,
                    'resolution': 'unresolved', 'interpretation': None, 'followup_of': None}
                def remember(current):
                    service.check_lease(action_in(current, route['id']), token)
                    action_in(current, route['id'])['_review_question'] = saved_question
                    action_in(current, route['id'])['_review_prepare'] = {
                        'expected_version': document['version'], 'mutation_id': key(route['id'] + ':prepare')}
                await run_in_threadpool(service.update, owner, identifier, remember)
        if saved_question:
            operation = route.get('_review_prepare') or {'expected_version': document['version'],
                                                       'mutation_id': key(route['id'] + ':prepare')}
            def add(current):
                if any(q['id'] == saved_question['id'] for q in current['clarifications']): return
                if len(current['clarifications']) >= 800: raise CvError('This CV has reached its question history limit.', 409)
                current['clarifications'].append(deepcopy(saved_question))
            document = await run_in_threadpool(service.cv.mutate, owner, document['_id'], Mutation.model_validate(operation),
                                               'profile-question', add)
            active = {'id': saved_question['id'], 'item_id': saved_question['item_id'],
                      'title': next(i['title'] for i in effective_items(document) if i['id'] == saved_question['item_id']),
                      'question': saved_question['question']}
            text = active['title'] + ': ' + active['question']
        else:
            active, text = None, 'No further review questions remain. Review your summary and save your profile, or add more context. Unknown details remain unknown.'
    # A late provider reply must not publish a question for newer evidence.
    latest = service.cv.get(owner, document['_id'])
    if latest['version'] != document['version']:
        raise Conflict('Your CV changed while preparing this question. Refresh before continuing.')
    def publish(current):
        action = action_in(current, route['id'])
        service.check_lease(action, token)
        action.update(status='saved', summary='CV profile saved.' if route['_command'] == 'finish' else 'Review updated.',
                      _token=None, _lease_until=0)
        action_message(current, route['id'])['text'] = text
        current['active_question'] = active
        if active: current['last_item_id'] = active['item_id']
        if route['_command'] == 'finish': current['reviewed_effective_version'] = document['effective_version']
    await run_in_threadpool(service.update, owner, identifier, publish)

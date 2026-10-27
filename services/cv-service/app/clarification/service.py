from copy import deepcopy
import re
from uuid import uuid4
from pydantic import ValidationError
from app.domain.capabilities import digest, effective_items, effective_fingerprint, normalized_name, validate_interpretation
from app.domain.errors import Conflict, Missing
from app.domain.service import bump, now
from app.schemas.cv import ConfirmedContext, SavedInterpretation


class DeferredTargetProvider:
    """Explicitly injectable absent-context provider for isolated CV tests."""
    async def context(self, bearer, identifier, version): return None
    async def selected_context(self, bearer): return None


def context_identity(context):
    if context is None: return None
    return {'id': context.id, 'version': context.version, 'selection_version': context.selection_version,
            'type': context.type}


def prepared_snapshot(document, context):
    return {**context_identity(context), 'extraction_version': document['extraction_version']}


def matching_conditions(item, context, uncertainty):
    if uncertainty not in {'qualification', 'date', 'claim'}: return []
    text = normalized_name(' '.join([item['title'], item['description']] + [e['excerpt'] for e in item['evidence']]))
    result = []
    for condition in context.conditions:
        if item['kind'] not in condition.item_kinds: continue
        if uncertainty != 'claim' and uncertainty != condition.kind: continue
        if any(re.search(r'(?<!\w)' + re.escape(normalized_name(term)) + r'(?!\w)', text) for term in condition.match_terms):
            result.append(condition)
    return result


def relevant(item, context, uncertainty):
    if uncertainty in {'qualification', 'date'}: return bool(matching_conditions(item, context, uncertainty))
    return bool(set(item['skill_ids']) & set(context.skill_ids) or matching_conditions(item, context, uncertainty))


def envelope(document, raw_context=None):
    context = ConfirmedContext.model_validate(raw_context) if raw_context is not None else None
    ready = document['operation']['status'] == 'ready'
    prepared = bool(context and ready and document.get('prepared_context') == prepared_snapshot(document, context))
    items = {item['id']: item for item in effective_items(document)}
    questions = []
    for question in document['clarifications']:
        # Saved explanations and skip history remain facts about this source.
        if question['status'] in {'answered', 'skipped'}:
            questions.append(question)
            continue
        item = items.get(question['item_id'])
        if (context and ready and item and not item['removed'] and not question.get('reconciliation_required')
                and question['uncertainty'] in item.get('uncertainties', [])
                and relevant(item, context, question['uncertainty'])):
            questions.append(question)
    reason = None
    if context is None:
        reason = 'Confirm and select a Career target to prepare relevant questions. Saved answers and skips are retained.'
    elif not ready:
        reason = 'Wait for this CV to finish processing before preparing clarifications.'
    elif not prepared:
        reason = 'Prepare clarifications for your current confirmed Career target.'
    return {'questions': questions, 'deferred': context is None, 'reason': reason,
            'cv_version': document['version'], 'context': context.model_dump(mode='json') if context else None,
            'prepared': prepared}


def prepare(service, owner, identifier, mutation, raw_context):
    if raw_context is None:
        document = service.get(owner, identifier)
        if document['version'] != mutation.expected_version: raise Conflict()
        return envelope(document)
    context = ConfirmedContext.model_validate(raw_context)
    if context.id != mutation.career_target_id or context.version != mutation.career_target_version:
        raise Conflict('The confirmed career context changed. Refresh it before preparing questions.')
    if (mutation.career_target_selection_version is not None
            and context.selection_version != mutation.career_target_selection_version):
        raise Conflict('Your selected Career target changed. Refresh before preparing questions.')
    def transform(document):
        document['prepared_context'] = prepared_snapshot(document, context)
        existing = {question['uncertainty_key']: question for question in document['clarifications']}
        for item in effective_items(document):
            if item['removed']: continue
            source_questions = [q for q in document['clarifications'] if q['item_id'] == item['id']]
            # Explicitly changed evidence must be reconciled before its statements
            # can be reused. An unanswered old key is never silently recycled.
            if any(q.get('reconciliation_required') for q in source_questions): continue
            if any(q.get('interpretation_status') in {'pending', 'failed'} for q in source_questions): continue
            uncertainties = list(item.get('uncertainties', []))
            attribution = 'personal_contribution' if item['kind'] == 'project' else 'responsibility' if item['kind'] == 'experience' else None
            if attribution in uncertainties and not source_questions: uncertainties = [attribution]
            for uncertainty in uncertainties:
                if not relevant(item, context, uncertainty): continue
                key = digest({'item_id': item['id'], 'uncertainty': uncertainty})
                if key in existing: continue
                # An explicit inability to clarify ends this line of questioning.
                # Other previously prepared questions remain voluntarily available.
                if any(q.get('resolution') == 'unanswerable' for q in source_questions): continue
                kind = 'project' if item['kind'] == 'project' else 'work' if item['kind'] == 'experience' else 'other'
                descriptions = {
                    'personal_contribution': 'What did you personally contribute, and what did teammates or guidance cover?',
                    'responsibility': 'What did you personally do in this responsibility, including any assistance or supervision?',
                    'proficiency': 'How would you describe your current familiarity with this skill? Unknown is fine.',
                    'duration': 'What, if anything, can you clarify about the time you personally spent using this skill?',
                    'qualification': 'What can you clarify about this qualification? Partial knowledge or “I do not know” is fine.',
                    'date': 'What dates can you clarify for this item? A year, month, partial answer or “I do not know” is fine.',
                    'claim': 'What can you clarify about this claim? Partial knowledge or “I do not know” is fine.'}
                parent = next((q for q in reversed(source_questions) if q.get('resolution') == 'partial'), None)
                question = {'id': key[:32], 'item_id': item['id'], 'kind': kind,
                    'question': descriptions[uncertainty], 'uncertainty_key': key, 'uncertainty': uncertainty,
                    'status': 'unanswered', 'answer': None, 'career_target_id': context.id,
                    'career_target_version': context.version, 'career_target_type': context.type,
                    'extraction_version': document['extraction_version'], 'reconciliation_required': False,
                    'answer_revision': 0, 'answer_sequence': 0, 'interpretation_status': 'not_requested',
                    'interpretation_error': None, 'resolution': 'unresolved', 'interpretation': None,
                    'followup_of': parent['id'] if parent else None}
                document['clarifications'].append(question)
                existing[key] = question
    document = service.mutate(owner, identifier, mutation, 'prepare', transform)
    return envelope(document, context)


def _question(document, question_id):
    question = next((q for q in document['clarifications'] if q['id'] == question_id), None)
    if question is None: raise Missing()
    item = next((item for item in effective_items(document) if item['id'] == question['item_id']), None)
    if not item or item['removed'] or question.get('reconciliation_required'):
        raise Conflict('The source item changed. Keep your draft and review that item before answering.')
    return question, item


def _interpret(service, owner, identifier, question_id, saved, interpreter):
    question, item = _question(saved, question_id)
    acquired = False
    try:
        acquired = service.interpretation_slots.acquire(blocking=False)
        if not acquired:
            raise ValueError('Interpretation is busy. Your answer is saved; retry interpretation shortly.')
        if interpreter is None: raise ValueError('Interpretation is not configured. Your answer is saved; retry after configuration.')
        payload, metadata = interpreter.interpret(item, question, question['answer'], question['answer_revision'])
        result = validate_interpretation(payload, item, question)
        result.update(metadata=metadata, applied_sequence=question['answer_sequence'],
                      extraction_version=saved['extraction_version'])
        result = SavedInterpretation.model_validate(result).model_dump(mode='json')
        error = None
    except ValidationError:
        result, error = None, 'Interpretation returned an invalid structure. Your answer is saved; retry interpretation.'
    except ValueError as exc:
        result, error = None, str(exc)[:1000]
    except Exception:
        result, error = None, 'Interpretation could not finish. Your answer is saved; retry interpretation.'
    finally:
        if acquired: service.interpretation_slots.release()
    current = service.get(owner, identifier)
    latest, _ = _question(current, question_id)
    if (current['version'] != saved['version'] or current['extraction_version'] != saved['extraction_version']
            or latest.get('answer_revision') != question['answer_revision']
            or latest.get('interpretation_token') != question.get('interpretation_token')
            or latest.get('interpretation_lease_until', 0) <= now()
            or latest.get('answer') != question['answer'] or latest.get('interpretation_status') != 'pending'):
        raise Conflict('Your answer is saved, but its source or a newer edit changed while interpretation ran. Review the saved state and retry interpretation.')
    document = deepcopy(current)
    updated, _ = _question(document, question_id)
    before = effective_fingerprint(document)
    updated['interpretation_token'] = None
    updated['interpretation_lease_until'] = 0
    if error:
        updated.update(interpretation_status='failed', interpretation_error=error, resolution='unresolved')
    else:
        updated.update(interpretation_status='ready', interpretation_error=None,
                       interpretation=result, resolution=result['resolution'])
    after = effective_fingerprint(document)
    if before != after: document['effective_version'] += 1
    document['history'].append({'version': current['version'], 'effective_version': current['effective_version'],
        'operation': 'interpret:' + question_id, 'clarifications': deepcopy(current['clarifications']),
        'overlays': deepcopy(current['overlays']), 'at': now()})
    bump(document)
    return service.repository.replace(current, document)


def answer(service, owner, identifier, question_id, mutation, interpreter=None):
    previous = service.get(owner, identifier)
    replay = str(mutation.mutation_id) in previous['receipts']
    changed_answer = False
    invocation_token = str(uuid4())
    def transform(document):
        nonlocal changed_answer
        question, item = _question(document, question_id)
        if mutation.action == 'skip':
            if question['status'] in {'answered', 'skipped'}: return
            question['status'] = 'skipped'
            return
        if question['status'] == 'answered' and question['answer'] == mutation.answer: return
        changed_answer = True
        question.update(status='answered', answer=mutation.answer,
            answer_revision=question.get('answer_revision', 0) + 1, answer_sequence=document['version'] + 1,
            interpretation_status='pending', interpretation_error=None, resolution='unresolved',
            interpretation_token=invocation_token, interpretation_lease_until=now() + 90)
    saved = service.mutate(owner, identifier, mutation, 'answer:' + question_id, transform)
    # Receipt replay never reruns a provider. Pending/failed answers have a separate
    # retry mutation, which also recovers after a process dies between these writes.
    if replay or not changed_answer: return saved
    # A same-key CAS loser may receive the winner's saved document from mutate.
    # Only the call whose private token actually won may perform provider work.
    if _question(saved, question_id)[0].get('interpretation_token') != invocation_token:
        return service.get(owner, identifier)
    return _interpret(service, owner, identifier, question_id, saved, interpreter)


def retry_interpretation(service, owner, identifier, question_id, mutation, interpreter=None):
    previous = service.get(owner, identifier)
    replay = str(mutation.mutation_id) in previous['receipts']
    requested = False
    invocation_token = str(uuid4())
    def transform(document):
        nonlocal requested
        question, _ = _question(document, question_id)
        if question['status'] != 'answered' or not question.get('answer'):
            raise Conflict('Save an explanation before interpreting it.')
        if question.get('interpretation_status') == 'ready': return
        if question.get('interpretation_status') == 'pending' and question.get('interpretation_lease_until', 0) > now():
            raise Conflict('This answer is still being interpreted. Wait briefly before retrying; interrupted work becomes retryable after 90 seconds.')
        requested = True
        question.update(interpretation_status='pending', interpretation_error=None, resolution='unresolved',
                        answer_revision=max(1, question.get('answer_revision', 0)),
                        answer_sequence=document['version'] + 1, interpretation_token=invocation_token,
                        interpretation_lease_until=now() + 90)
    saved = service.mutate(owner, identifier, mutation, 'interpretation-retry:' + question_id, transform)
    if replay or not requested: return saved
    if _question(saved, question_id)[0].get('interpretation_token') != invocation_token:
        return service.get(owner, identifier)
    return _interpret(service, owner, identifier, question_id, saved, interpreter)

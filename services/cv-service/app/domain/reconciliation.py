"""Explicit source reconciliation; no automatic name-based transfer of statements."""
from copy import deepcopy
from uuid import uuid4
from app.domain.capabilities import digest, effective_items, effective_fingerprint
from app.domain.errors import Conflict, Missing
from app.domain.service import bump, now
from app.schemas.cv import validate_item_dates
from app.domain.answer_capacity import release as release_answer_capacity


def affected_sources(source, items):
    retained = set(source['overlays']) | {q['item_id'] for q in source['clarifications']}
    old = {item['id']: item for item in source['original_items']}
    new = {item['id']: item for item in items}
    fields = ('kind', 'skill_ids', 'supporting_item_ids', 'start_date', 'end_date', 'ongoing',
              'proficiency', 'experience_months')
    def field_value(item, field):
        return item.get(field, False if field == 'ongoing' else None)
    return sorted(identifier for identifier in retained if identifier not in new or identifier not in old
                  or any(field_value(old[identifier], field) != field_value(new[identifier], field) for field in fields))


def candidate_for(document, items, metadata, notices, source=None):
    source = source or document
    old_ids = set(source['overlays']) | {q['item_id'] for q in source['clarifications']}
    affected = sorted(old_ids) if source['_id'] != document['_id'] else affected_sources(source, items)
    return {'id': str(uuid4()), 'source_cv_id': source['_id'], 'source_version': source['version'],
            'items': deepcopy(items), 'extraction': deepcopy(metadata), 'notices': list(notices),
            'previous_items': effective_items(source), 'overlays': deepcopy(source['overlays']),
            'clarifications': deepcopy(source['clarifications']), 'affected_item_ids': affected,
            'created_at': now()}


def view(document):
    candidate = document.get('candidate')
    if not candidate: return None
    return {'cv_id': document['_id'], 'cv_version': document['version'],
            'candidate_id': candidate['id'], 'source_cv_id': candidate['source_cv_id'],
            'previous_items': candidate['previous_items'], 'candidate_items': candidate['items'],
            'affected_item_ids': candidate['affected_item_ids'],
            'previous_answers': candidate['clarifications'], 'extraction': candidate['extraction'],
            'notices': candidate['notices']}


def compare_source(service, owner, identifier, mutation):
    if identifier == mutation.source_cv_id: raise Conflict('Choose a different saved CV to compare.')
    source = service.get(owner, mutation.source_cv_id)
    if source['version'] != mutation.source_version or source['operation']['status'] != 'ready':
        raise Conflict('The previous source changed or is not ready. Refresh before comparing.')
    def transform(document):
        if document.get('candidate'): raise Conflict('Resolve the existing source comparison first.')
        if document['overlays'] or document['clarifications']:
            raise Conflict('Compare a replacement before editing or answering it. Existing statements remain saved.')
        document['candidate'] = candidate_for(document, document['original_items'], document['extraction'], document.get('notices', []), source)
        document['reconciliation'] = [{'item_id': item_id, 'reason': 'Review the previous source and explicitly choose whether its statement belongs on this replacement.'}
                                      for item_id in document['candidate']['affected_item_ids']]
    return service.mutate(owner, identifier, mutation, 'compare_source', transform)


def resolve(service, owner, identifier, mutation):
    previous = service.get(owner, identifier)
    fingerprint = digest({'operation': 'reconcile', 'data': mutation.model_dump(mode='json')})
    key = str(mutation.mutation_id)
    if key in previous['receipts']:
        if previous['receipts'][key] != fingerprint: raise Conflict('This request key was used for another change.')
        return previous
    candidate = previous.get('candidate')
    if previous['version'] != mutation.expected_version or not candidate or candidate['id'] != mutation.candidate_id:
        raise Conflict('The comparison changed. Your choices are retained; refresh the source comparison.')
    if previous['operation']['status'] not in {'ready', 'failed'}:
        raise Conflict('Wait for processing to finish before resolving this comparison.')
    if previous['operation']['status'] == 'failed' and previous['operation'].get('error', {}).get('code') != 'reconciliation_required':
        raise Conflict('Resolve the processing failure before changing the source.')
    # A replacement comparison captures immutable statements; newer source edits
    # must be compared explicitly rather than silently transferring an older copy.
    if mutation.action == 'accept_candidate' and candidate['source_cv_id'] != identifier:
        source = service.get(owner, candidate['source_cv_id'])
        if source['version'] != candidate['source_version']:
            raise Conflict('The previous CV changed after comparison. Keep this result and compare it again.')
    document = deepcopy(previous)
    before = effective_fingerprint(document)
    if mutation.action == 'accept_candidate':
        choices = {choice.item_id: choice.target_item_id for choice in mutation.choices}
        if set(choices) != set(candidate['affected_item_ids']):
            raise Conflict('Choose whether to archive or reapply every affected source statement.')
        by_id = {item['id']: item for item in candidate['items']}
        old_items = {item['id']: item for item in candidate['previous_items']}
        for old, target in choices.items():
            if target and (target not in by_id or old not in old_items or old_items[old]['kind'] != by_id[target]['kind']):
                raise Conflict('Reapply a statement only to an explicitly reviewed item of the same kind.')
            retained_targets = (set(document['overlays']) | {q['item_id'] for q in document['clarifications']}) - set(choices)
            if target and target in retained_targets:
                raise Conflict('That new item already has a retained statement. Choose a separate source or archive the old statement.')
        same_source = candidate['source_cv_id'] == identifier
        overlays = {key: deepcopy(value) for key, value in document['overlays'].items() if key in by_id and key not in choices} if same_source else {}
        questions = [deepcopy(q) for q in document['clarifications'] if q['item_id'] in by_id and q['item_id'] not in choices] if same_source else []
        transferred = [q for q in candidate['clarifications'] if choices.get(q['item_id']) and q.get('answer')]
        if len({q['id'] for q in transferred}) != len(transferred):
            raise Conflict('The source contains ambiguous answer identities. Keep its history and review the original source before reapplying answers.')
        identities = {q['id']: digest({'source_cv_id': candidate['source_cv_id'], 'question_id': q['id'],
            'target_cv_id': identifier, 'target_item_id': choices[q['item_id']]}) for q in transferred}
        retained_ids = {q['id'] for q in questions}
        if len(retained_ids) != len(questions):
            raise Conflict('The retained source contains ambiguous answer identities. Review or archive those source statements before accepting this comparison.')
        for old, target in choices.items():
            if target is None: continue
            patch = candidate['overlays'].get(old, {})
            if patch.get('provenance') == 'user_corrected':
                overlays[target] = deepcopy(patch)
                overlays[target]['_field_sequences'] = {field: document['version'] + 1
                    for field in patch if field != '_field_sequences'}
            for old_question in candidate['clarifications']:
                if old_question['item_id'] != old or not old_question.get('answer'): continue
                question = deepcopy(old_question)
                release_answer_capacity(question)
                identity = identities[old_question['id']]
                if identity[:32] in retained_ids:
                    raise Conflict('Those source mappings produce duplicate answer identities. Review the chosen source mappings.')
                retained_ids.add(identity[:32])
                question.update(id=identity[:32], uncertainty_key=identity, item_id=target,
                    extraction_version=document['extraction_version'] + int(same_source),
                    status='answered', answer_revision=1, interpretation_status='failed',
                    resolution='unresolved', interpretation=None,
                    interpretation_error='Source changed. Retry interpretation against the reviewed evidence.',
                    interpretation_token=None, interpretation_lease_until=0,
                    reconciliation_required=False,
                    followup_of=identities[old_question['followup_of']][:32]
                        if old_question.get('followup_of') in identities else None,
                    reconciled_from={'cv_id': candidate['source_cv_id'], 'item_id': old, 'question_id': old_question['id']})
                questions.append(question)
        document.update(original_items=deepcopy(candidate['items']), overlays=overlays,
                        clarifications=questions, extraction=deepcopy(candidate['extraction']),
                        notices=candidate['notices'], prepared_context=None)
        try:
            for item in effective_items(document):
                validate_item_dates(item)
        except ValueError as exc:
            raise Conflict('Those statements conflict with the replacement dates. Keep the current result or archive the affected statement, then correct the replacement.') from exc
        if same_source: document['extraction_version'] += 1
    document['history'].append({'operation': 'reconcile', 'action': mutation.action,
        'version': previous['version'], 'extraction_version': previous['extraction_version'],
        'effective_version': previous['effective_version'], 'original_items': deepcopy(previous['original_items']),
        'overlays': deepcopy(previous['overlays']), 'clarifications': deepcopy(previous['clarifications']),
        'candidate': deepcopy(candidate), 'choices': [choice.model_dump() for choice in mutation.choices], 'at': now()})
    document.pop('candidate', None)
    document['reconciliation'] = []
    document['operation'].update(status='ready', error=None, lease_token=None, lease_until=0)
    if before != effective_fingerprint(document): document['effective_version'] += 1
    document['receipts'][key] = fingerprint
    bump(document)
    try: return service.repository.replace(previous, document)
    except Conflict:
        latest = service.get(owner, identifier)
        if latest['receipts'].get(key) == fingerprint: return latest
        raise

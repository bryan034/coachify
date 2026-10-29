"""Immutable reviewed target content, explicit confirmation and fenced selection."""
import base64
import binascii
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5
from fastapi import HTTPException
from app.schemas.targets import Target, canonical_skill_id, normalized_text


def conflict(message='Your target changed elsewhere. Reload before trying again.'):
    return HTTPException(409, message)


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def present(document):
    return Target.model_validate({key: document[key] for key in Target.model_fields if key in document}).model_dump()


def has_requirements(document):
    return bool(document['skills'] or document.get('conditions'))


def selection_view(document):
    return {key: document[key] for key in ('career_target_id', 'career_target_version', 'version')}


def get_target(repository, owner, identifier):
    document = repository.get(owner, identifier)
    if not document: raise HTTPException(404, 'This career target is unavailable.')
    return document


def create(repository, owner, request):
    # Source is used only for validation by TargetCreate. Neither records nor
    # mutation fingerprints contain the full source (including on retries).
    structured = request.model_dump(exclude={'mutation_id', 'reviewed_source_text'})
    origin = 'user_reviewed_jd' if request.target_type == 'specific_job' else 'user_guidance'
    timestamp = datetime.now(timezone.utc).isoformat()
    identifier = str(uuid5(NAMESPACE_URL, owner + ':career-target:' + request.mutation_id))
    document = {**structured, '_id': identifier, 'id': identifier, 'user_id': owner,
        'version': 1, 'status': 'draft', 'requirements_source': origin, 'generation_version': 'manual-v1',
        'created_at': timestamp, 'updated_at': timestamp, 'confirmed_at': None,
        'create_key': request.mutation_id, 'create_fingerprint': fingerprint({key: value for key, value in structured.items() if key != 'conditions' or value}),
        'confirm_key': None, 'confirm_fingerprint': None}
    document['skills'] = [{**skill, 'skill_id': canonical_skill_id(skill['name']), 'origin': origin} for skill in structured['skills']]
    document['conditions'] = [{**condition, 'id': str(uuid5(UUID(identifier), condition['kind'] + ':' + normalized_text(condition['label']))),
        'origin': origin} for condition in structured['conditions']]
    return present(repository.insert(document))


def confirm(repository, owner, identifier, request):
    document = get_target(repository, owner, identifier)
    digest = fingerprint(request.model_dump())
    if document['confirm_key'] == request.mutation_id:
        if document['confirm_fingerprint'] != digest: raise conflict('This request key was used for different changes.')
        return present(document)
    if document['version'] != request.expected_version: raise conflict()
    if document['status'] == 'confirmed': return present(document)
    if not has_requirements(document): raise HTTPException(422, 'Add at least one reviewed skill or qualification/date condition before confirming this target. Create a new target with its requirements.')
    timestamp = datetime.now(timezone.utc).isoformat()
    updated = {**document, 'status': 'confirmed', 'version': document['version'] + 1, 'confirmed_at': timestamp,
               'updated_at': timestamp, 'confirm_key': request.mutation_id, 'confirm_fingerprint': digest}
    try: return present(repository.confirm(document, updated))
    except HTTPException as exc:
        if exc.status_code != 409: raise
        latest = get_target(repository, owner, identifier)
        if latest['confirm_key'] == request.mutation_id and latest['confirm_fingerprint'] == digest: return present(latest)
        raise


def select(repository, owner, request):
    digest = fingerprint(request.model_dump())
    for attempt in range(3):
        previous = repository.selection(owner)
        receipt = previous['receipts'].get(request.mutation_id)
        if receipt:
            if receipt != digest: raise conflict('This request key was used for a different selection.')
            return selection_view(previous)
        if previous['version'] != request.expected_version: raise conflict('Your selected target changed. Reload before selecting again.')
        target = get_target(repository, owner, request.career_target_id)
        if target['version'] != request.career_target_version or target['status'] != 'confirmed' or not has_requirements(target):
            raise conflict('Select a confirmed target with reviewed requirements at its current version.')
        if len(previous['receipts']) >= 10000: raise HTTPException(422, 'The target selection history has reached its limit.')
        changed = previous['career_target_id'] != target['id'] or previous['career_target_version'] != target['version']
        candidate = deepcopy(previous)
        candidate.update(career_target_id=target['id'], career_target_version=target['version'],
            version=previous['version'] + int(changed), revision=previous['revision'] + 1)
        candidate['receipts'][request.mutation_id] = digest
        try: return selection_view(repository.select(previous, candidate))
        except HTTPException as exc:
            if exc.status_code != 409 or attempt == 2: raise
    raise conflict()


def selected_context(repository, owner, identifier=None, version=None):
    selection = repository.selection(owner)
    if identifier is None:
        identifier, version = selection['career_target_id'], selection['career_target_version']
        if identifier is None: return None
    target = get_target(repository, owner, identifier)
    if (target['version'] != version or target['status'] != 'confirmed' or not has_requirements(target) or
        selection['career_target_id'] != identifier or selection['career_target_version'] != version):
        raise conflict('The confirmed target selection changed. Refresh before continuing.')
    # Confirmed documents never mutate. Reading the selection fence again rejects
    # a switch during this read, including switch-away-and-back at a new version.
    if repository.selection(owner)['version'] != selection['version']:
        raise conflict('The selected target changed while it was being read. Please retry.')
    return {'id': target['id'], 'version': target['version'], 'type': target['target_type'], 'confirmed': True,
        'skill_ids': [skill['skill_id'] for skill in target['skills']], 'selection_version': selection['version'],
        'conditions': target.get('conditions', []),
        'role': target['role'], 'field': target['field']}


def encode_cursor(document):
    payload = json.dumps({'created_at': document['created_at'], 'id': document['id']}, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip('=')


def decode_cursor(value):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 512:
            raise ValueError
        # Reject alternate alphabets, padding and non-canonical opaque encodings.
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        if base64.urlsafe_b64encode(raw).decode().rstrip('=') != value: raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'created_at', 'id'}: raise ValueError
        date, identifier = data['created_at'], data['id']
        if not isinstance(date, str) or not isinstance(identifier, str) or len(date) > 64 or len(identifier) != 36:
            raise ValueError
        timestamp = datetime.fromisoformat(date)
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0 or timestamp.isoformat() != date:
            raise ValueError
        if str(UUID(identifier)) != identifier: raise ValueError
        return data
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(422, 'This target history cursor is invalid. Reload the target list.') from exc


def list_targets(repository, owner, cursor=None):
    after = decode_cursor(cursor) if cursor is not None else None
    if after is not None:
        anchor = repository.get(owner, after['id'])
        if anchor is None or anchor['created_at'] != after['created_at']:
            raise HTTPException(422, 'This target history cursor is invalid. Reload the target list.')
    documents = repository.list(owner, after)
    selection = repository.selection(owner)
    selected = get_target(repository, owner, selection['career_target_id']) if selection['career_target_id'] else None
    page = documents[:20]
    return {'targets': [present(doc) for doc in page], 'selection': selection_view(selection),
        'next_cursor': encode_cursor(page[-1]) if len(documents) > 20 else None,
        'selected_target': present(selected) if selected else None}

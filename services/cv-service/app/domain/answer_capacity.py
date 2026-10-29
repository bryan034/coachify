"""Bounded private reservations for publishing already accepted explanations."""
from copy import deepcopy
from bson import BSON
from app.domain.errors import CvError


# Covers the UTF-8/BSON maximum of SavedInterpretation plus publication metadata.
RESULT_BYTES = 512 * 1024
RETRY_BYTES = 64 * 1024
RETRY_CLAIM_BYTES = 1024
CAPACITY_MESSAGE = ('This CV has reached its saved history limit for another complete explanation. '
                    'Keep your answer and this source for history, and use a new saved CV.')


def snapshot(document):
    return {'clarifications': document['clarifications'], 'overlays': document['overlays'],
            'prepared_context': document.get('prepared_context')}


def active(question):
    return (not question.get('reconciliation_required') and question.get('interpretation_status') == 'pending'
            and question.get('_capacity_token') and question.get('_capacity_token') == question.get('interpretation_token'))


def reserved_bytes(document):
    pending = [q for q in document.get('clarifications', []) if active(q)]
    if not pending: return 0
    remaining = [q.get('_capacity_retry_bytes') for q in pending]
    if any(type(value) is not int or not 0 <= value <= RETRY_BYTES for value in remaining):
        raise CvError('Saved interpretation capacity needs review. Your existing answers are retained.', 409)
    count = len(pending)
    # Each result adds one full clarification/overlay snapshot. Earlier results
    # also enlarge the snapshots needed by later pending results; reserve that
    # triangular growth instead of counting only today's snapshot size.
    return count * len(BSON.encode(snapshot(document))) + RESULT_BYTES * count * (count + 1) // 2 + sum(remaining)


def reserve(question, token, *, retry=False):
    remaining = RETRY_BYTES
    if retry and active(question):
        remaining = question['_capacity_retry_bytes'] - RETRY_CLAIM_BYTES
        if remaining < 0: return False
    question['_capacity_token'] = token
    question['_capacity_retry_bytes'] = remaining
    return True


def release(question):
    question.pop('_capacity_token', None)
    question.pop('_capacity_retry_bytes', None)


def preview_chat_answer(document, question_id, text, maximum):
    """Check both question creation and answer admission before publishing either."""
    candidate = deepcopy(document)
    question = next(q for q in candidate['clarifications'] if q['id'] == question_id)
    question.update(status='answered', answer=text, answer_revision=1, answer_sequence=2 ** 53,
                    interpretation_status='pending', interpretation_token='0' * 36,
                    interpretation_lease_until=1.0)
    reserve(question, question['interpretation_token'])
    # These are conservative copies of the two pre-answer snapshots. Real writes
    # use the earlier, smaller states. The private padding covers two receipts,
    # history labels and version fields and is never persisted.
    for _ in range(2): candidate['history'].append(deepcopy(snapshot(document)))
    candidate['_admission_padding'] = 'x' * 4096
    if len(BSON.encode(candidate)) + reserved_bytes(candidate) > maximum:
        raise CvError(CAPACITY_MESSAGE + ' Your chat message remains saved.', 409)

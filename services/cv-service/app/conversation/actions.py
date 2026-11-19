"""Lookup helpers for the actions saved on conversation messages."""
from uuid import uuid5, NAMESPACE_URL
from app.domain.errors import Missing

LEASE_SECONDS = 90
OUTSTANDING = {'pending', 'awaiting_confirmation', 'needs_source', 'failed'}


def key(value): return str(uuid5(NAMESPACE_URL, 'elo-cv-chat:' + value))


def action_in(document, identifier):
    for message in document['messages']:
        for action in message.get('actions', []):
            if action['id'] == identifier: return action
    raise Missing()


def action_message(document, identifier):
    return next(m for m in document['messages'] if any(a['id'] == identifier for a in m.get('actions', [])))


def has_outstanding(document):
    return any(a['status'] in OUTSTANDING for m in document['messages'] for a in m.get('actions', []))


def apply_requested_purpose(document):
    """An upgrade requested while actions were outstanding applies once they have all settled."""
    requested = document.get('requested_purpose')
    if requested and not has_outstanding(document):
        document['purpose'] = requested
        document.pop('requested_purpose')

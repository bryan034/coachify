"""Opaque, owner-scoped keyset position; never a database query supplied by callers."""
import base64
import json
import math
import re
from uuid import UUID
from app.domain.errors import CvError


def decode_cursor(value):
    if value is None: return None
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', value): raise ValueError
        decoded = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        if not isinstance(decoded, list) or len(decoded) != 2: raise ValueError
        timestamp, identifier = decoded
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0: raise ValueError
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier: raise ValueError
        return timestamp, identifier
    except (ValueError, TypeError, OverflowError) as exc:
        raise CvError('The saved CV page cursor is invalid. Refresh the list.', 422) from exc


def encode_cursor(document):
    position = json.dumps([document['created_at'], document['_id']], separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(position).decode().rstrip('=')

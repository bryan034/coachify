import hashlib
import hmac
import json
from datetime import datetime, timezone


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def now():
    return datetime.now(timezone.utc)


def keyed(secret, *parts):
    message = json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

"""Keep internal evidence references out of assistant prose, not source records."""
import re

_UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
_OPAQUE = rf'(?:{_UUID}|[a-f0-9]{{32,64}})'
_REFERENCE = rf'(?:(?:fact|evidence|source|item):[a-f0-9]{{24,64}}|answer:{_UUID}|{_OPAQUE})'
_LABEL = r'(?:(?:evidence|source|item|experience|ref)(?:[_ ](?:ids?|refs?))?\s*[:=]?\s*)?'
_LONG_GROUP = rf'{_LABEL}{_REFERENCE}(?:\s*[,;]\s*{_REFERENCE})*'
_SHORT_GROUP = r'(?:evidence|source|item|ref)(?:[_ ](?:ids?|refs?))?\s*[:=]?\s*b\d+'
_GROUP = rf'(?:{_LONG_GROUP}|{_SHORT_GROUP})'


def review_reply(text):
    text = re.sub(rf'\s*\[\s*{_GROUP}\s*\]', '', text, flags=re.I)
    text = re.sub(rf'\s*\(\s*{_GROUP}\s*\)', '', text, flags=re.I)
    text = re.sub(r'\s*\[\s*b\d+\s*\]', '', text)
    text = re.sub(rf'\b(?:evidence|source|item)[_ ](?:ids?|refs?)\s*[:=]\s*(?:{_REFERENCE}|b\d+)', '', text, flags=re.I)
    text = re.sub(rf'\b(?:(?:fact|evidence|source|item):[a-f0-9]{{24,64}}|answer:{_UUID})\b', '', text, flags=re.I)
    text = re.sub(r'\s*[\[(]\s*[\])]', '', text)
    return re.sub(r' +([,.;:!?])', r'\1', re.sub(r' {2,}', ' ', text)).strip()

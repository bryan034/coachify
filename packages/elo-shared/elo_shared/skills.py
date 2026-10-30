"""One bundled registry for all producers. Unknown names never acquire guessed IDs."""
import json
import unicodedata
from pathlib import Path
REGISTRY = json.loads(Path(__file__).with_name('skills.json').read_text())
MAPPING_VERSION = REGISTRY['version']
def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
ALIASES = {}
for entry in REGISTRY['skills']:
    for name in entry['names']:
        ALIASES.setdefault(normalize(name), set()).add(entry['id'])
def resolve(name, category=None):
    candidates = ALIASES.get(normalize(name), set())
    return next(iter(candidates)) if len(candidates) == 1 else None
def identity(name, category=None):
    return {'canonical_skill_id': resolve(name, category), 'skill_registry_version': MAPPING_VERSION}

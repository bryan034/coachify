"""The validated facts behind each CV item, including legacy CV claims."""
from copy import deepcopy
from app.domain.names import normalized_name
from app.schemas.interview_evidence import fact_key, unique_facts


def evidence_for(item):
    """Derive the current ledger from validated facts, including legacy CV claims."""
    facts = deepcopy(unique_facts(item.get('review_evidence', [])))
    keys = {fact_key(f) for f in facts}
    for claim in item.get('skill_claims', []):
        refs = [{'source_id': e['id'], 'quote': e['excerpt']} for e in claim.get('evidence', [])][:3]
        if not refs: continue
        for field, attribute in [('personal_contribution', 'attribution'), ('assistance', 'assistance')]:
            value = claim.get(attribute)
            key = (field, normalized_name(claim['name']))
            if key not in keys and value not in {None, 'unknown'} and (field != 'personal_contribution' or claim.get('evidence_type') == 'user_clarified'):
                facts.append({'field': field, 'skill_name': claim['name'], 'status': 'supported',
                              'value': value, 'evidence': refs, 'attribution': claim.get('attribution')})
                keys.add(key)
    return facts

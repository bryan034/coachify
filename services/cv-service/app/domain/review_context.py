"""Derive clarification needs from CV evidence without inventing new facts."""
from copy import deepcopy
import re
from app.domain.capabilities import normalized_name
from app.schemas.interview_evidence import fact_key, fact_groups, unique_facts, facts_closed

_RELEVANT_REVIEW_FIELDS = {'personal_contribution', 'responsibilities', 'task_scope',
                           'skill_use', 'assistance', 'complexity', 'problem_solving'}
_UNCERTAINTY_FIELDS = {
    'personal_contribution': ('personal_contribution',),
    'responsibility': ('responsibilities',),
    'claim': ('personal_contribution', 'responsibilities'),
}


def evidence_for(item):
    """Derive the current ledger from validated facts, including legacy CV claims."""
    facts = deepcopy(unique_facts(item.get('review_evidence', [])))
    keys = {fact_key(f) for f in facts}
    for claim in item.get('skill_claims', []):
        # Legacy extraction/interpretation already validated these attributes.
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




def review_target_skipped(item, field, skill_name=None):
    return any(target['field'] == field and
        (normalized_name(target.get('skill_name') or '') == normalized_name(skill_name or '')
         or not target.get('skill_name'))
        for target in item.get('_review_skips', []))


def clarification_context(item, facts=None, *, include_baseline=True):
    facts = item.get('review_evidence', []) if facts is None else facts
    groups = fact_groups(facts)
    general = {f['field'] for f in facts if not f.get('skill_name')}
    gaps = {}
    def add(field, skill_name=None, reason='ambiguous_cv_claim'):
        if review_target_skipped(item, field, skill_name): return
        key = field, normalized_name(skill_name or '')
        if facts_closed(groups.get(key, [])): return
        gaps[key] = {'field': field, 'skill_name': skill_name, 'reason': reason}
    for fact in facts:
        if fact['status'] in {'partial', 'conflicting'} and fact['field'] in _RELEVANT_REVIEW_FIELDS:
            add(fact['field'], fact.get('skill_name'), fact['status'])
    for uncertainty in item.get('uncertainties', []):
        for field in _UNCERTAINTY_FIELDS.get(uncertainty, ()):
            add(field)
    # Team wording identifies an ambiguity, never an inferred personal skill.
    source = ' '.join(e['excerpt'] for e in item.get('evidence', []))
    if re.search(r'\b(team|collaborated|collaboration|jointly)\b', source, re.I):
        if 'personal_contribution' not in general:
            add('personal_contribution', reason='personal_vs_team_boundary')
    if include_baseline and item['kind'] in {'project', 'experience'}:
        from app.domain.baseline import baseline_targets
        for target in baseline_targets(item):
            add(target['field'], target['skill_name'], target['reason'])
    return {'review_dispositions': item.get('_review_skips', []),
            'known_fields': list(dict.fromkeys(f['field'] for f in facts if f['status'] == 'supported')),
            'clarification_targets': list(gaps.values()),
            'listed_skills': item.get('skill_names', []) or [c['name'] for c in item.get('skill_claims', [])]}


def prepare_review_items(items):
    """Remove superseded review flags while keeping legacy target uncertainties."""
    result = deepcopy(items)
    for item in result:
        gaps = {g['field'] for g in clarification_context(item, include_baseline=False)['clarification_targets']}
        item['uncertainties'] = [u for u in item.get('uncertainties', [])
            if u not in _UNCERTAINTY_FIELDS or gaps.intersection(_UNCERTAINTY_FIELDS[u])]
    return result

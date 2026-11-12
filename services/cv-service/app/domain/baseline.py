"""Source-specific CV baseline estimates, never practical assessment results."""
from app.domain.capabilities import digest, normalized_name
from app.domain.review_context import evidence_for


def skill_facts(item, name):
    return [f for f in evidence_for(item)
            if not f.get('skill_name') or normalized_name(f['skill_name']) == normalized_name(name)]


def estimate_skill(item, claim):
    facts = skill_facts(item, claim['name'])
    supported = {}
    for fact in facts:
        if fact['status'] == 'supported': supported.setdefault(fact['field'], []).append(fact)
    conflicts = any(f['status'] == 'conflicting' and f['field'] in
                    {'personal_contribution', 'assistance', 'skill_use'} for f in facts)
    ordered = sorted(facts, key=lambda f: (f['field'] not in {'personal_contribution', 'assistance', 'skill_use', 'complexity', 'problem_solving'}, f['status'] != 'supported'))
    refs = ['fact:' + digest({'item': item['id'], 'fact': f})[:24] for f in ordered]
    if not refs:
        refs = ['source:' + digest({'item': item['id'], 'evidence': e})[:24] for e in item.get('evidence', [])]
    personal = claim.get('attribution') == 'personal'
    assistance = claim.get('assistance', 'unknown')
    # Typed ownership and exact assistance values in source-validated review facts
    # may establish the same rubric as the structured claim attributes.
    use = [f for f in supported.get('skill_use', []) if f.get('skill_name')]
    if claim.get('attribution', 'unknown') == 'unknown' and use:
        personal = all(f.get('attribution') == 'personal' for f in use)
    help_values = {f['value'] for f in supported.get('assistance', [])
                   if f.get('value') in {'independent', 'assisted', 'supervised'}}
    conflicts |= len(help_values) > 1
    if assistance == 'unknown' and len(help_values) == 1:
        assistance = next(iter(help_values))
    required = {'personal_contribution', 'assistance', 'skill_use'} <= supported.keys()
    level = 'insufficient_evidence'
    if personal and required and not conflicts:
        if assistance in {'assisted', 'supervised'}: level = 'guided_application'
        elif assistance == 'independent':
            complex_skill = all(any(normalized_name(f.get('skill_name') or '') == normalized_name(claim['name']) for f in supported.get(field, []))
                                for field in ('complexity', 'problem_solving'))
            level = 'complex_application' if complex_skill else 'independent_application'
    explanation = {
        'insufficient_evidence': 'The saved CV and review do not establish a supported personal application level for this skill. Missing details remain unknown.',
        'guided_application': 'The saved evidence describes personal application with guidance or supervision.',
        'independent_application': 'The saved evidence describes personal application with explicit independence.',
        'complex_application': 'The saved evidence describes independent application with concrete complexity and problem solving.',
    }[level]
    return {'item_id': item['id'], 'skill_name': claim['name'], 'level': level,
            'explanation': explanation, 'evidence_refs': refs[:12]}


def baseline_estimates(items):
    result = []
    for item in items:
        if item.get('removed') or item['kind'] not in {'project', 'experience'}: continue
        claims = item.get('skill_claims') or [{'name': name} for name in item.get('skill_names', [])]
        for claim in claims:
            estimate = estimate_skill(item, claim)
            if estimate['evidence_refs']: result.append(estimate)
    return result


def baseline_targets(item):
    """Prioritize relevant project gaps, not every absent rubric field at once."""
    result, owner_missing = [], False
    claims = item.get('skill_claims') or [{'name': name} for name in item.get('skill_names', [])]
    for claim in claims:
        facts=skill_facts(item,claim['name'])
        if claim.get('attribution') not in {'team','observed','denied'} and not any(f['field']=='self_rating' for f in facts):
            result.append({'field':'self_rating','skill_name':claim['name'],'reason':'self_reported_baseline'})
        if estimate_skill(item, claim)['level'] != 'insufficient_evidence': continue
        if claim.get('attribution') in {'team', 'observed', 'denied'}: continue
        if any(f['status'] in {'unknown', 'skipped', 'not_applicable'} and f['field'] in
               {'personal_contribution', 'assistance', 'skill_use'} for f in facts): continue
        supported = {f['field'] for f in facts if f['status'] == 'supported'}
        owner_missing |= 'personal_contribution' not in supported
        # Establish a concrete relevant application before probing its support.
        # Related skills can be covered by one responsibility/example question.
        if 'skill_use' not in supported:
            result.append({'field': 'skill_use', 'skill_name': claim['name'], 'reason': 'baseline_skill_evidence'})
        elif 'assistance' not in supported:
            result.append({'field': 'assistance', 'skill_name': claim['name'], 'reason': 'baseline_skill_evidence'})
    if owner_missing:
        result.insert(0, {'field': 'personal_contribution', 'skill_name': None, 'reason': 'project_personal_responsibility'})
    return result


def visible_baseline_estimates(estimates):
    """Public views show supported estimates; diagnostic gaps remain internal."""
    return [estimate for estimate in estimates if estimate['level'] != 'insufficient_evidence']

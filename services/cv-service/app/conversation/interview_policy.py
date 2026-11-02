"""Validate agent questions, completion and skill estimates against saved evidence."""
from copy import deepcopy
from app.domain.capabilities import digest, normalized_name
from app.schemas.interview import InterviewDecision
from app.schemas.interview_evidence import fact_key
from app.conversation.interview_memory import evidence_for, target_key, MAX_TARGET_ATTEMPTS


def validate_decision(decision, context, memory, *, user_stop=False, max_attempts=MAX_TARGET_ATTEMPTS):
    """Enforce evidence coverage and repetition rules without selecting a question."""
    decision = InterviewDecision.model_validate(decision)
    sources = {i['id']: i for i in context['sources']}
    index = context['evidence_index']
    coverage = deepcopy(memory['coverage'])
    focused = context.get('focused_source')
    for item in decision.coverage:
        if item.item_id not in sources: raise ValueError('Coverage refers to an unavailable experience.')
        refs = [index.get(ref) for ref in item.evidence_refs]
        if any(ref is None or ref['item_id'] != item.item_id for ref in refs):
            raise ValueError('Coverage must cite evidence for that exact experience.')
        if item.status == 'reviewed':
            if focused and focused['id'] == item.item_id and any(f['status'] == 'conflicting' and f['field'] in {'personal_contribution', 'responsibilities'} for f in evidence_for(focused)):
                raise ValueError('Conflicting ownership evidence requires reviewed-with-gaps or clarification.')
            fields = {r['field'] for r in refs if r['status'] == 'supported'}
            personal = any(r['field'] == 'personal_contribution' and r['status'] == 'supported'
                           and r.get('attribution') in {'personal', 'shared'} for r in refs)
            if not personal or not fields & {'task_scope', 'skill_use', 'responsibilities'}:
                raise ValueError('Reviewed requires personal ownership and concrete task evidence; acknowledge gaps instead.')
        elif not user_stop and not any(q['item_id'] == item.item_id and (q.get('answer_status') in {'answered', 'skipped'} or q.get('skipped')) for q in memory['questions']):
            raise ValueError('Discuss an experience before deferring it or acknowledging its gaps.')
        coverage[item.item_id] = item.model_dump(mode='json')
    if decision.action == 'recall':
        raise ValueError('Recall requests must be resolved before publishing a reply.')
    if decision.recall_ids: raise ValueError('Only recall actions may request earlier answers.')
    if decision.action == 'ask':
        if decision.item_id not in sources or not decision.targets:
            raise ValueError('A question needs an available source and explicit evidence targets.')
        if not focused or focused['id'] != decision.item_id:
            raise ValueError('Inspect the selected source before asking about it.')
        facts = {fact_key(f): f for f in evidence_for(focused)}
        open_targets = []
        for target in decision.targets:
            key = target_key(decision.item_id, target.field, target.skill_name)
            fact = facts.get((target.field, normalized_name(target.skill_name or '')))
            if fact and fact['status'] in {'supported', 'unknown', 'skipped', 'not_applicable'}:
                continue
            signature = digest(fact) if fact else 'missing'
            attempt = memory['attempts'].get(key, {})
            if attempt.get('declined') or (attempt.get('signature') == signature and attempt.get('count', 0) >= max_attempts):
                continue
            open_targets.append(target)
        if not open_targets:
            raise ValueError('These targets are already known, declined, or repeatedly unproductive. Choose a distinct remaining gap or move on.')
        if len(open_targets) != len(decision.targets):
            raise ValueError('Remove known or exhausted targets; ask only the distinct remaining gap.')
    elif decision.targets or decision.item_id:
        raise ValueError('Only questions may select an active source and targets.')
    if decision.action == 'finish' and not user_stop:
        missing = [s['id'] for s in sources.values() if s['kind'] in {'project', 'experience'} and s['id'] not in coverage]
        if missing: raise ValueError('Unvisited work/projects remain. Explore them or acknowledge their gaps after discussion.')
    for estimate in decision.estimates:
        if not focused or estimate.item_id != focused['id'] or normalized_name(estimate.skill_name) not in {normalized_name(c['name']) for c in focused.get('skill_claims', [])}:
            raise ValueError('A skill estimate must refer to a known skill on the focused experience.')
        refs = [index.get(ref) for ref in estimate.evidence_refs]
        if any(r is None or r['item_id'] != estimate.item_id or
               (r.get('skill_name') and normalized_name(r['skill_name']) != normalized_name(estimate.skill_name)) for r in refs):
            raise ValueError('A skill estimate must cite matching source and skill evidence.')
        fields = {r['field']: r for r in refs if r['status'] == 'supported'}
        if estimate.level != 'insufficient_evidence':
            if any(f['status'] == 'conflicting' and f['field'] in {'personal_contribution', 'assistance', 'skill_use'} and (not f.get('skill_name') or normalized_name(f['skill_name']) == normalized_name(estimate.skill_name)) for f in evidence_for(focused)):
                raise ValueError('Conflicting skill evidence must be clarified before a supported level can be estimated.')
            claims = (focused or {}).get('skill_claims', [])
            personal = next((c for c in claims if normalized_name(c['name']) == normalized_name(estimate.skill_name)), None)
            if not personal or personal['attribution'] != 'personal' or not {'personal_contribution', 'assistance', 'skill_use'} <= fields.keys():
                raise ValueError('A personal skill estimate requires attributed personal work and concrete skill use.')
            if estimate.level == 'guided_application' and personal.get('assistance') not in {'assisted', 'supervised'}:
                raise ValueError('Guided application requires explicit assistance evidence.')
            if estimate.level in {'independent_application', 'complex_application'} and personal.get('assistance') != 'independent':
                raise ValueError('Independent skill estimates require explicit independence.')
            if estimate.level == 'complex_application' and not {'complexity', 'problem_solving'} <= fields.keys():
                raise ValueError('Complex application requires complexity and problem-solving evidence.')
    return decision, coverage

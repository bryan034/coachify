"""What the CV review changed, derived on read from the saved CV so every page agrees after a review."""
from app.domain.capabilities import effective_items, skills_for

NOTE_LIMIT = 240


def review_summary(document, items):
    """Counts and per-skill notes. Nothing is stored; the answers and corrections are the source."""
    answered = [q for q in document.get('clarifications', [])
                if q.get('status') == 'answered' and not q.get('reconciliation_required')]
    # The same CV with no review answers or corrections applied: what the extraction alone said.
    before = {s['skill_id']: s for s in skills_for(effective_items(
        {**document, 'clarifications': [], 'overlays': {}, 'history': []}))}
    after = {s['skill_id']: s for s in skills_for(items)}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    corrected = sorted(i for i in set(before) & set(after)
        if any(before[i][field] != after[i][field] for field in ('proficiency', 'experience_months')))
    notes = {}
    for question in sorted(answered, key=lambda q: (q.get('interpretation') or {}).get('applied_sequence', 0)):
        for claim in ((question.get('interpretation') or {}).get('claims') or []):
            excerpt = (claim.get('evidence_excerpt') or '').strip()
            if claim.get('attribution') == 'personal' and excerpt and claim['skill_id'] in after:
                notes[claim['skill_id']] = excerpt[:NOTE_LIMIT]
    return {'answered_questions': len(answered), 'experiences': len({q['item_id'] for q in answered}),
            'skills_added': len(added), 'skills_corrected': len(corrected), 'skills_removed': len(removed),
            'added_skill_ids': added, 'skill_notes': notes}

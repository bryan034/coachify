"""Review-time skill levels: the model rates each skill by itself from the CV and review answers.

Levels use the shared 1-10 competence scale and are read pessimistically: a skill the review
did not clarify is assumed guided or not competent rather than left unrated. Only conflicting
or unverified evidence is labelled uncertain. This is independent of any career goal. Reviews are stored beside the CV and overlaid on read,
so they never change effective evidence, fingerprints or interview memory. A review applies only
while the evidence it was judged from is unchanged.
"""
from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field
from elo_shared.competence_scale import GUIDED_CEILING, MIN_LEVEL, clamp_level
from app.domain.capabilities import digest, evidence_matches, level_ceiling, skill_id
from app.schemas.interview_evidence import ReviewQuote, SkillLevel

BATCH = 6
EXCLUDED = {'team', 'observed', 'denied'}


class ReviewedSkillLevel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(min_length=1, max_length=100)
    skill_name: str = Field(min_length=1, max_length=200)
    # null only when the evidence conflicts or is unverified; missing evidence gets a low level instead.
    level: SkillLevel | None
    rationale: str = Field(min_length=1, max_length=400)
    evidence: list[ReviewQuote] = Field(default_factory=list, max_length=3)


class SkillLevelReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    levels: list[ReviewedSkillLevel] = Field(default_factory=list, max_length=120)


def _answers(document, item_id):
    return [{'id': 'answer:' + q['id'], 'question': q['question'], 'answer': q['answer']}
            for q in document.get('clarifications', [])
            if q['item_id'] == item_id and q.get('status') == 'answered' and q.get('answer')
            and not q.get('reconciliation_required')]


def review_source(document, item, status=None):
    """The model input for one item, with the exact texts its quotations may come from."""
    claims = [c for c in item.get('skill_claims', []) if c['attribution'] not in EXCLUDED]
    answers = _answers(document, item['id'])
    model = {'id': item['id'], 'kind': item['kind'], 'title': item['title'], 'description': item['description'],
        'start_date': item.get('start_date'), 'end_date': item.get('end_date'), 'ongoing': item.get('ongoing', False),
        'cv_unverified': bool(item.get('validation_issue')),
        'cv_evidence': [{'source_id': e['id'], 'text': e['excerpt']} for e in item.get('evidence', [])],
        'skills': [{'name': c['name'], 'attribution': c['attribution'], 'assistance': c['assistance'],
                    'stated_proficiency': c.get('proficiency'), 'experience_months': c.get('experience_months')} for c in claims],
        'review_facts': [{'field': f['field'], 'skill_name': f.get('skill_name'), 'status': f['status'], 'value': f.get('value'),
                          'attribution': f.get('attribution'), 'quotes': [r['quote'] for r in f.get('evidence', [])]}
                         for f in item.get('review_evidence', [])],
        'review_answers': answers}
    if status: model['review_status'] = status
    texts = {'description': item['description']}
    for e in item.get('evidence', []): texts[e['id']] = texts.get(e['id'], '') + '\n' + e['excerpt']
    for fact in item.get('review_evidence', []):
        for ref in fact.get('evidence', []): texts[ref['source_id']] = texts.get(ref['source_id'], '') + '\n' + ref['quote']
    for answer in answers: texts[answer['id']] = texts.get(answer['id'], '') + '\n' + answer['answer']
    return {'item_id': item['id'], 'model': model, 'texts': texts, 'kind': item['kind'],
            'skills': {c['skill_id']: c['name'] for c in claims},
            'ceilings': {c['skill_id']: level_ceiling(item, c) for c in claims},
            'fingerprint': digest({key: value for key, value in model.items() if key != 'review_status'})}


def ratable(item):
    # Every skill the person may have used is rated, even a bare mention (at the bottom of the scale).
    return not item.get('removed') and any(c['attribution'] not in EXCLUDED for c in item.get('skill_claims', []))


def pending_sources(document, items, statuses=None):
    saved = document.get('skill_level_reviews', {})
    result = []
    for item in items:
        if not ratable(item): continue
        source = review_source(document, item, (statuses or {}).get(item['id']))
        if saved.get(item['id'], {}).get('fingerprint') != source['fingerprint']: result.append(source)
    return result


def assumed_level(source, identifier):
    """The worst reasonable reading when the model gave no usable rating for a skill."""
    if source['model']['cv_unverified'] and not source['model']['review_answers']:
        return {'skill_id': identifier, 'level': None, 'rationale': 'The CV evidence is unverified and no review answer supports it.',
                'evidence': []}
    described = source['kind'] in {'project', 'experience'}
    level = clamp_level(GUIDED_CEILING - 1 if described else MIN_LEVEL, source['ceilings'][identifier])
    first = source['model']['cv_evidence'][:1]
    return {'skill_id': identifier, 'level': level, 'assumed': True,
        'rationale': ('Used in this work, but nothing shows it was done independently, so guided use is assumed.' if described
                      else 'Only named, with no described use.'),
        'evidence': [{'id': e['source_id'], 'excerpt': e['text'], 'location': 'Your CV'} for e in first]}


def validate_level_review(raw, sources):
    """One entry per skill: the model's supported level under its evidence ceiling, an explicit
    uncertain label, or the pessimistic assumption when the rating is missing or unsupported."""
    review = raw if isinstance(raw, SkillLevelReview) else SkillLevelReview.model_validate(raw)
    result = {}
    for source in sources:
        judged_by_skill = {}
        for judged in review.levels:
            if judged.item_id == source['item_id']: judged_by_skill.setdefault(skill_id(judged.skill_name), judged)
        levels = []
        for identifier in source['skills']:
            judged = judged_by_skill.get(identifier)
            if judged is None:
                levels.append(assumed_level(source, identifier)); continue
            if judged.level is None:
                levels.append({'skill_id': identifier, 'level': None, 'rationale': judged.rationale, 'evidence': []}); continue
            quotes = [ref for ref in judged.evidence
                      if ref.source_id in source['texts'] and evidence_matches(ref.quote, source['texts'][ref.source_id])]
            if not quotes or len(quotes) != len(judged.evidence):
                levels.append(assumed_level(source, identifier)); continue
            levels.append({'skill_id': identifier, 'level': clamp_level(judged.level, source['ceilings'][identifier]),
                'rationale': judged.rationale,
                'evidence': [{'id': ref.source_id, 'excerpt': ref.quote,
                              'location': 'Your review answer' if ref.source_id.startswith('answer:') else 'Your CV'} for ref in quotes]})
        result[source['item_id']] = {'fingerprint': source['fingerprint'], 'levels': levels}
    return result


def coverage(items):
    """Share of the person's own skills with a level, for the 90% target after a finished review."""
    claims = [c for item in items if not item.get('removed') for c in item.get('skill_claims', []) if c['attribution'] not in EXCLUDED]
    rated = sum(1 for c in claims if (c.get('skill_level') or {}).get('level') is not None)
    return {'skills': len(claims), 'rated': rated, 'share': rated / len(claims) if claims else 1.0}


def apply_skill_level_reviews(document, items):
    """Overlay current review levels on effective items; a review of changed evidence is ignored."""
    saved = document.get('skill_level_reviews') or {}
    finished = document.get('profile_reviewed_effective_version') is not None and document.get('profile_reviewed_effective_version') == document.get('effective_version')
    for item in items:
        if item.get('removed'): continue
        source = review_source(document, item)
        review = saved.get(item['id'])
        if review and source['fingerprint'] == review['fingerprint']:
            levels = {level['skill_id']: level for level in review['levels']}
        elif finished:
            # A completed review can outlive a failed provider call. Show conservative
            # assumptions without persisting them, so the model can still retry later.
            levels = {claim['skill_id']: assumed_level(source, claim['skill_id'])
                      for claim in item.get('skill_claims', [])
                      if claim['skill_id'] in source['skills'] and not claim.get('skill_level')}
        else:
            continue
        for claim in item.get('skill_claims', []):
            level = levels.get(claim['skill_id'])
            if level and claim['attribution'] not in EXCLUDED:
                claim['skill_level'] = {'rationale': level['rationale'], 'source': 'review', 'evidence': deepcopy(level['evidence']),
                    'level': None if level['level'] is None else clamp_level(level['level'], level_ceiling(item, claim)),
                    'status': 'uncertain' if level['level'] is None else 'rated'}
    return items

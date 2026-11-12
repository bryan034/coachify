from copy import deepcopy
import calendar
import hashlib
import json
import re
import unicodedata
from app.schemas.cv import Extraction, InterpretationOutput, validate_item_dates, date_bounds
from app.domain.extraction_errors import EvidenceValidationError
from app.schemas.interview_evidence import ReviewFact, fact_key, fact_statement, unique_facts
from pydantic import ValidationError
from elo_shared.competence_scale import GUIDED_CEILING, INDEPENDENT_LEVEL, MAX_LEVEL, MENTION_CEILING, clamp_level


def normalized_name(name):
    return ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()


def skill_id(name): return 'skill:' + normalized_name(name)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


# A hyphen ending a PDF line ("proof-of-\nconcept", "evi-\ndence") becomes
# "word- word" once whitespace collapses. Only a hyphen attached to the
# preceding word counts, so spaced separators such as "Python - SQL" stay.
_WRAPPED_HYPHEN = re.compile(r'(?<=\w)- (?=\w)')


def evidence_matches(excerpt, source):
    # Preserve words and meaningful punctuation (e.g. C++ versus C#), while
    # tolerating PDF line wraps, spacing, case and Unicode presentation forms.
    if excerpt in source: return True
    excerpt, source = normalized_name(excerpt), normalized_name(source)
    if excerpt in source: return True
    # A quotation may rejoin a line-wrapped hyphenated compound or word.
    excerpt = _WRAPPED_HYPHEN.sub('-', excerpt)
    return excerpt in _WRAPPED_HYPHEN.sub('-', source) or excerpt in _WRAPPED_HYPHEN.sub('', source)


def _validate_review_quote(ref, source, item_index, review_index, quote_index):
    indexes = {'review_index': review_index, 'quote_index': quote_index}
    if ref['source_id'] not in source:
        raise EvidenceValidationError('Interview evidence cited an unknown CV passage. Retry this upload.',
                                      'review_source', item_index, **indexes)
    if not evidence_matches(ref['quote'], source[ref['source_id']]):
        raise EvidenceValidationError('An interview evidence quotation does not match its cited CV passage. Retry this upload.',
                                      'review_quote', item_index, **indexes)


def evidence_requiring_semantic_check(payload, blocks):
    if not isinstance(payload, dict): return []
    source = {block['id']: block['text'] for block in blocks}
    refs = []
    items = payload.get('items', [])
    if isinstance(items, list):
        for item_index, item in enumerate(items):
            if isinstance(item, dict) and isinstance(item.get('evidence'), list):
                refs.extend(item['evidence'])
                review_facts = item.get('review_evidence', [])
                for review_index, fact in enumerate(review_facts if isinstance(review_facts, list) else []):
                    try:
                        fact = ReviewFact.model_validate(fact).model_dump(mode='json')
                    except ValidationError:
                        continue  # Ordinary schema validation/repair handles malformed facts.
                    for quote_index, ref in enumerate(fact['evidence']):
                        _validate_review_quote(ref, source, item_index, review_index, quote_index)
                    if fact.get('evidence'):
                        # The factual interpretation still needs semantic support.
                        refs.append({'block_id': fact['evidence'][0].get('source_id'), 'excerpt': fact_statement(fact)})
    if isinstance(payload.get('other_information'), list): refs.extend(payload['other_information'])
    pending = []
    for ref in refs:
        if not isinstance(ref, dict): continue
        block_id, excerpt = ref.get('block_id'), ref.get('excerpt')
        if not isinstance(block_id, str) or not isinstance(excerpt, str): continue
        if block_id not in source:
            raise EvidenceValidationError('The model cited an unknown source block. Retry this upload.', 'source_excerpt')
        if not evidence_matches(excerpt, source[block_id]):
            value = {'block_id': block_id, 'excerpt': excerpt}
            if value not in pending: pending.append(value)
    if len(pending) > 1120:
        raise ValueError('The extraction exceeds the evidence verification limit. Retry this upload.')
    return pending


def validate_extraction(payload, blocks, cv_id, semantic_support=frozenset()):
    extraction = Extraction.model_validate(payload)
    source = {block['id']: block for block in blocks}
    source_text = {key: block['text'] for key, block in source.items()}
    validate_other_information(extraction.other_information, blocks, semantic_support)
    items = []
    # Item IDs depend on source evidence and section, never display names or model order.
    # Exact duplicated evidence is rejected; repeated titles on distinct evidence remain separate.
    for index, item in enumerate(extraction.items):
        evidence = []
        for ref in item.evidence:
            block = source.get(ref.block_id)
            if not block or (not evidence_matches(ref.excerpt, block['text']) and (ref.block_id, ref.excerpt) not in semantic_support):
                raise EvidenceValidationError('The model returned unsupported source evidence. Retry this upload.', 'source_excerpt', index)
            evidence.append({'id': ref.block_id, 'location': block['location'], 'excerpt': ref.excerpt})
        identity = digest({'cv': cv_id, 'kind': item.kind, 'evidence': sorted(evidence, key=lambda e: (e['id'], e['excerpt']))})[:32]
        names_by_id = {}
        for name in item.skill_names + ([item.title] if item.kind == 'skill' else []):
            names_by_id.setdefault(skill_id(name), name)
        names = list(names_by_id.values())
        # A purported explicit skill needs that exact name in its evidence; inferred
        # skills remain distinctly labelled and can be narrowed by the user.
        if item.explicit:
            text = normalized_name(' '.join(source[e['id']]['text'] for e in evidence))
            if any(normalized_name(name) not in text for name in names):
                raise EvidenceValidationError('The model labelled an unsupported skill as explicit. Retry this upload.', 'literal_skill', index)
        # A valid calendar value is not evidence that the source stated it. Keep
        # each excerpt separate so components cannot be combined across citations.
        for field in ('start_date', 'end_date'):
            value = getattr(item, field)
            if value and not any(_stated_date(ref['excerpt'], value) for ref in evidence):
                setattr(item, field, None)
        if item.ongoing and not any(re.search(
                r'\b(present|ongoing|currently|still|continuing)\b', normalized_name(ref['excerpt']))
                for ref in evidence):
            item.ongoing = False
        review_facts = [fact.model_dump(mode='json') for fact in item.review_evidence]
        for review_index, fact in enumerate(review_facts):
            if fact.get('skill_name') and skill_id(fact['skill_name']) not in names_by_id:
                raise EvidenceValidationError('Skill evidence must refer to a skill on that exact source.',
                                              'review_skill', index, review_index=review_index)
            for quote_index, ref in enumerate(fact['evidence']):
                _validate_review_quote(ref, source_text, index, review_index, quote_index)
            first = fact['evidence'][0]['source_id']
            if (first, fact_statement(fact)) not in semantic_support and not evidence_matches(fact_statement(fact), source[first]['text']):
                raise EvidenceValidationError('Interview evidence is not supported by the CV.',
                                              'review_support', index, review_index=review_index)
        review_facts = unique_facts(review_facts)
        # A skill level is optional model judgement. One that cannot be tied to a
        # listed skill and a real CV quotation is dropped, never a reason to lose the item.
        skill_levels = []
        for judged in item.skill_levels:
            level_id = skill_id(judged.skill_name)
            quotes = [{'id': ref.source_id, 'location': source[ref.source_id]['location'], 'excerpt': ref.quote}
                      for ref in judged.evidence if ref.source_id in source and evidence_matches(ref.quote, source_text[ref.source_id])]
            if level_id in names_by_id and len(quotes) == len(judged.evidence) and not any(l['skill_id'] == level_id for l in skill_levels):
                skill_levels.append({'skill_id': level_id, 'level': judged.level, 'rationale': judged.rationale, 'evidence': quotes})
        items.append({'review_evidence': review_facts, 'skill_levels': skill_levels, 'id': identity, 'kind': item.kind, 'title': item.title, 'description': item.description,
                      'provenance': 'explicit' if item.explicit else 'inferred', 'evidence': evidence,
                      'skill_ids': [skill_id(name) for name in names], 'skill_names': names,
                      'category': item.category or 'unspecified', 'proficiency': item.proficiency,
                      'experience_months': item.experience_months, 'context': item.context,
                      'start_date': item.start_date, 'end_date': item.end_date, 'ongoing': item.ongoing,
                      'removed': False, 'supporting_item_ids': [], 'uncertainties': item.uncertainties})
    if len({item['id'] for item in items}) != len(items):
        raise EvidenceValidationError('The model duplicated a source claim. Retry this upload.', 'duplicate_claim')
    for index, parsed in enumerate(extraction.items):
        if any(ref < 0 or ref >= len(items) or ref == index for ref in parsed.supporting_items):
            raise EvidenceValidationError('The model returned an invalid source relationship. Retry this upload.', 'source_relationship', index)
        items[index]['supporting_item_ids'] = [items[ref]['id'] for ref in parsed.supporting_items]
    by_id = {item['id']: item for item in items}
    completed, active = set(), set()
    def visit(identifier):
        if identifier in completed: return
        if identifier in active:
            raise EvidenceValidationError('The model returned circular source relationships. Retry this upload.', 'circular_relationship')
        active.add(identifier)
        for parent in by_id[identifier]['supporting_item_ids']: visit(parent)
        active.remove(identifier)
        completed.add(identifier)
    for item in items: visit(item['id'])
    return items


def validate_other_information(refs, blocks, semantic_support=frozenset()):
    source = {block['id']: block for block in blocks}
    result = []
    for ref in refs:
        block = source.get(ref.block_id)
        if not block or (not evidence_matches(ref.excerpt, block['text']) and (ref.block_id, ref.excerpt) not in semantic_support):
            raise EvidenceValidationError('The model returned unsupported source evidence. Retry this upload.', 'source_excerpt')
        value = {'id': ref.block_id, 'location': block['location'], 'excerpt': ref.excerpt}
        if value not in result:
            result.append(value)
    return result


def level_ceiling(item, claim):
    """The highest level this source can support, read pessimistically.

    Project or work use counts as guided unless the person's own independent work is stated.
    A skill that is only named cannot rise above basic exposure.
    """
    facts = [f for f in item.get('review_evidence', []) if f['status'] == 'supported'
             and (not f.get('skill_name') or skill_id(f['skill_name']) == claim['skill_id'])]
    if item['kind'] in {'project', 'experience'}:
        independent = claim.get('assistance') == 'independent' or any(
            f['field'] == 'assistance' and f.get('value') == 'independent' for f in facts)
        personal = claim.get('attribution') == 'personal' or any(
            f['field'] in {'skill_use', 'personal_contribution'} and f.get('attribution') == 'personal' for f in facts)
        return MAX_LEVEL if independent and personal else GUIDED_CEILING
    described = claim.get('proficiency') or claim.get('experience_months') is not None or facts
    return INDEPENDENT_LEVEL if described else MENTION_CEILING


def cap_skill_level(item, claim):
    judged = claim.get('skill_level')
    if judged and judged.get('level') is not None:
        judged['level'] = clamp_level(judged['level'], level_ceiling(item, claim))


def _base_claims(item):
    result = {}
    for index, identifier in enumerate(item['skill_ids']):
        names = item.get('skill_names', [])
        result[identifier] = {'skill_id': identifier, 'name': names[index] if index < len(names) else item['title'],
            'attribution': 'unknown', 'assistance': 'unknown', 'proficiency': item.get('proficiency'),
            'experience_months': item.get('experience_months'), 'evidence': deepcopy(item['evidence']),
            'evidence_type': item['provenance'], 'support_uncertain': item.get('support_uncertain', False)}
    for judged in item.get('skill_levels', []):
        # Omitted, not null, when absent so existing fingerprints are unchanged.
        if judged['skill_id'] in result:
            result[judged['skill_id']]['skill_level'] = {'level': judged['level'], 'rationale': judged['rationale'],
                                                          'source': 'cv', 'evidence': deepcopy(judged['evidence'])}
    return result


def _correction_events(document):
    """Order corrected fields independently, including older saved overlays."""
    missing = object()
    history = [entry for entry in document.get('history', []) if 'overlays' in entry]
    history.sort(key=lambda entry: entry.get('version', 0))
    for identifier, overlay in document.get('overlays', {}).items():
        if overlay.get('provenance') == 'user_clarified': continue
        grouped = {}
        for field, value in overlay.items():
            if field in {'_field_sequences', 'provenance'}: continue
            sequence = overlay.get('_field_sequences', {}).get(field)
            if sequence is None:
                # Existing snapshots preserve the last visible field transition.
                # With no chronology at all, retain the former correction priority.
                previous = missing
                for entry in history:
                    recorded = entry['overlays'].get(identifier, {}).get(field, missing)
                    if recorded != previous:
                        sequence = entry.get('version', 0) if recorded is not missing else None
                        previous = recorded
                if history and value != previous:
                    sequence = document.get('version', history[-1].get('version', 0))
                if sequence is None: sequence = float('inf')
            grouped.setdefault(sequence, {})[field] = deepcopy(value)
        for sequence, patch in grouped.items():
            yield sequence, 1, identifier, patch


def _apply_correction(item, patch):
    item.update(patch)
    item['provenance'] = 'user_corrected'
    if 'skill_ids' in patch:
        previous = item['_claims']
        item['_claims'] = {identifier: {**previous[identifier], 'name': claim['name']}
                           if identifier in previous else claim
                           for identifier, claim in _base_claims(item).items()}
    # A display-name change must not rebuild facts already clarified for the
    # same canonical skill. Explicit value or source corrections still apply.
    corrected_claim = bool(set(patch) & {'proficiency', 'experience_months', 'support_uncertain'})
    if corrected_claim or ('evidence' in patch and 'skill_ids' not in patch):
        for claim in item['_claims'].values():
            for field in ('proficiency', 'experience_months'):
                if field in patch: claim[field] = patch[field]
            if patch.get('support_uncertain'):
                claim.update(support_uncertain=True, attribution='unknown')
            claim['evidence_type'] = 'user_corrected'
            if 'evidence' in patch: claim['evidence'] = deepcopy(patch['evidence'])


def effective_items(document):
    """Project field corrections and interpretations in order, then dependencies."""
    items = deepcopy(document.get('original_items', []))
    by_id = {item['id']: item for item in items}
    for item in items:
        item.setdefault('start_date', None)
        item.setdefault('end_date', None)
        item.setdefault('ongoing', False)
        item.setdefault('support_uncertain', False)
        # Old literal-answer overlays remain readable, without automatic backfill.
        overlay = document.get('overlays', {}).get(item['id'], {})
        if overlay.get('provenance') == 'user_clarified': item.update(deepcopy(overlay))
        item.setdefault('review_evidence', [])
        item['_claims'] = _base_claims(item)
    events = [(q['interpretation'].get('applied_sequence', 0), 0, q['item_id'], q)
              for q in document.get('clarifications', [])
              if q.get('interpretation') and not q.get('reconciliation_required')]
    events.extend(_correction_events(document))
    events.sort(key=lambda event: event[:2])
    for _, correction, identifier, payload in events:
        item = by_id.get(identifier)
        if not item: continue
        if correction:
            _apply_correction(item, payload)
            continue
        question = payload
        result = question['interpretation']
        # A stored successful interpretation remains the last valid projection
        # while a newer answer is pending; admission separately rejects that state.
        item['provenance'] = 'user_clarified'
        for patch in result['claims']:
            claim = item['_claims'].setdefault(patch['skill_id'], {'skill_id': patch['skill_id'], 'name': patch['name'],
                'attribution': 'unknown', 'assistance': 'unknown', 'proficiency': None, 'experience_months': None,
                'evidence': [], 'evidence_type': 'user_clarified', 'support_uncertain': True})
            for field in patch['changed_fields']:
                if field == 'skill_level':
                    claim['skill_level'] = {'level': patch['skill_level'], 'rationale': patch['skill_level_rationale'],
                                            'source': 'review', 'evidence': [{'id': 'answer:' + question['id'],
                                            'location': 'Your clarification', 'excerpt': patch['evidence_excerpt']}]}
                else: claim[field] = patch[field]
            if 'attribution' in patch['changed_fields']:
                claim['support_uncertain'] = patch['attribution'] == 'unknown'
            claim['evidence_type'] = 'user_clarified'
            if patch.get('evidence_excerpt'):
                claim['evidence'] = [{'id': 'answer:' + question['id'], 'location': 'Your clarification',
                                     'excerpt': patch['evidence_excerpt']}]
        for fact in result.get('review_evidence', []):
            retained = [f for f in item['review_evidence'] if fact_key(f) != fact_key(fact)]
            grounded = deepcopy(fact)
            for ref in grounded['evidence']: ref['source_id'] = 'answer:' + question['id']
            item['review_evidence'] = retained + [grounded]
        if result.get('dates'):
            for field in result['dates']['changed_fields']: item[field] = result['dates'][field]
        resolved = set(result['resolved_uncertainties'])
        item['uncertainties'] = [u for u in item.get('uncertainties', []) if u not in resolved]
        for uncertainty in result['remaining_uncertainties']:
            if uncertainty not in item['uncertainties']: item['uncertainties'].append(uncertainty)
        if result.get('statement_excerpt'):
            item['description'] = result['statement_excerpt']
            item['evidence'] = [{'id': 'answer:' + question['id'], 'location': 'Your clarification',
                                 'excerpt': result['statement_excerpt']}]
    # Extraction is acyclic. Recursion makes propagation independent of item order
    # and narrows only the matching derived skill, never every skill on the item.
    done = set()
    def propagate(item):
        if item['id'] in done: return
        parents = []
        for parent_id in item.get('supporting_item_ids', []):
            parent = by_id.get(parent_id)
            if parent is None: continue
            propagate(parent)
            parents.append(parent)
        for identifier, claim in item['_claims'].items():
            support_states = []
            for parent in parents:
                support = parent['_claims'].get(identifier)
                if parent.get('removed') or (support and support['attribution'] in {'team', 'observed', 'denied'}):
                    support_states.append('denied')
                elif support and support['support_uncertain']:
                    support_states.append('uncertain')
                elif support:
                    support_states.append('supported')
                elif parent.get('support_uncertain'):
                    support_states.append('uncertain')
                else:
                    # Some non-skill source items substantiate a derived claim;
                    # retain that explicitly recorded relationship until changed.
                    support_states.append('supported')
            if support_states and 'supported' not in support_states:
                claim.update(attribution='denied' if all(s == 'denied' for s in support_states) else 'unknown',
                             support_uncertain=True)
        done.add(item['id'])
    for item in items: propagate(item)
    # A declined question is a review disposition, not fabricated factual evidence.
    # Rebuild from the durable skip receipt; corrections/reconciliation fence it.
    for question in document.get('clarifications', []):
        if (question.get('status') != 'skipped' or question.get('reconciliation_required') or question.get('reopened')
                or question.get('extraction_version') != document.get('extraction_version')): continue
        item = by_id.get(question['item_id'])
        if not item: continue
        for target in question.get('_interview_targets', []):
            item.setdefault('_review_skips', []).append({**target, 'status': 'reviewed_with_gaps', 'question_id': question['id']})
    for item in items:
        claims = list(item.pop('_claims').values())
        item.pop('_field_sequences', None)
        item['skill_claims'] = claims
        for claim in claims: cap_skill_level(item, claim)
        active = [claim for claim in claims if claim['attribution'] not in {'team', 'observed', 'denied'}]
        item['skill_ids'], item['skill_names'] = [c['skill_id'] for c in active], [c['name'] for c in active]
        item['support_uncertain'] = any(claim['support_uncertain'] for claim in active)
        # The user's own explanation or correction resolves an unverified section.
        if item['provenance'] in {'user_clarified', 'user_corrected'}: item.pop('validation_issue', None)
        # The item-wide legacy fields only describe a single skill unambiguously.
        if len(active) == 1:
            item['proficiency'], item['experience_months'] = active[0]['proficiency'], active[0]['experience_months']
        elif claims:
            item['proficiency'], item['experience_months'] = None, None
    return items


def skills_for(items):
    groups = {}
    for item in items:
        if item['removed']: continue
        for claim in item.get('skill_claims', list(_base_claims(item).values())):
            if claim['attribution'] in {'team', 'observed', 'denied'}: continue
            identifier, name = claim['skill_id'], claim['name']
            uncertain = claim['support_uncertain']
            skill = groups.setdefault(identifier, {'skill_id': identifier, 'name': name,
                'category': item.get('category', 'unspecified'), 'proficiency': None, 'experience_months': None,
                'context': item.get('context'), 'evidence': [], 'evidence_type': 'uncertain',
                'explicit': False, 'item_ids': [], 'sources': [], 'conflicting_fields': []})
            skill['item_ids'].append(item['id'])
            source = {'item_id': item['id'], 'evidence_type': 'uncertain' if uncertain else claim['evidence_type'],
                      'explicit': not uncertain and claim['evidence_type'] == 'explicit', 'support_uncertain': uncertain,
                      **{field: claim[field] for field in ('attribution', 'assistance', 'proficiency', 'experience_months', 'evidence')}}
            if claim.get('skill_level'): source['skill_level'] = claim['skill_level']
            skill['sources'].append(source)
            # Retain source-level uncertainty even when another independent source
            # supports the same skill. Never turn repetition into stronger proof.
            if not uncertain:
                skill['explicit'] = skill['explicit'] or source['explicit']
                types = {s['evidence_type'] for s in skill['sources'] if not s['support_uncertain']}
                skill['evidence_type'] = next(iter(types)) if len(types) == 1 else 'mixed'
            for evidence in claim['evidence']:
                if evidence not in skill['evidence']: skill['evidence'].append(evidence)
    for skill in groups.values():
        for field in ('proficiency', 'experience_months'):
            values = {source[field] for source in skill['sources'] if not source['support_uncertain'] and source[field] is not None}
            skill[field] = next(iter(values)) if len(values) == 1 else None
            if len(values) > 1: skill['conflicting_fields'].append(field)
        # A skill's level legitimately differs between sources; report the highest rated one
        # (each is already capped by its own evidence), preferring the review on a tie.
        judged = [s['skill_level'] for s in skill['sources'] if s.get('skill_level')]
        rated = [j for j in judged if j.get('level') is not None]
        if rated: skill['skill_level'] = max(rated, key=lambda j: (j['level'], j['source'] == 'review'))
        elif judged: skill['skill_level'] = judged[0]
    return list(groups.values())


def effective_fingerprint(document):
    # Rewording an explanation, retry metadata and receipt state are history, not
    # changed capability facts. Ordinary corrected description changes still count.
    facts = []
    originals = {item['id']: item for item in document.get('original_items', [])}
    for item in effective_items(document):
        value = {key: item.get(key) for key in ('id', 'kind', 'title', 'removed', 'start_date', 'end_date', 'ongoing')}
        overlay = document.get('overlays', {}).get(item['id'], {})
        value['description'] = overlay.get('description', originals[item['id']]['description'])
        statements = [q['interpretation']['statement_excerpt'] for q in document.get('clarifications', [])
            if q['item_id'] == item['id'] and not q.get('reconciliation_required')
            and q.get('interpretation') and q['interpretation'].get('statement_excerpt')]
        if statements: value['clarified_statements'] = [normalized_name(text) for text in statements]
        value['claims'] = [{key: claim[key] for key in ('skill_id', 'attribution', 'assistance',
            'proficiency', 'experience_months', 'support_uncertain')} for claim in item['skill_claims']]
        for fingerprinted, claim in zip(value['claims'], item['skill_claims']):
            if claim.get('skill_level'): fingerprinted['skill_level'] = claim['skill_level']['level']
        value['claims'].sort(key=lambda claim: claim['skill_id'])
        value['review_evidence'] = sorted([{k: f.get(k) for k in ('field', 'skill_name', 'status', 'value', 'attribution')} for f in item.get('review_evidence', [])], key=lambda f: fact_key(f))
        value['uncertainties'] = sorted(item.get('uncertainties', []))
        facts.append(value)
    return digest(facts)


def _stated_months(excerpt, months):
    text = normalized_name(excerpt)
    if re.search(r'\b(about|around|roughly|approximately|maybe|at least|more than|less than)\b', text): return False
    words = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
             'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'zero': 0}
    for number, unit in re.findall(r'\b(\d+(?:\.\d+)?|' + '|'.join(words) + r')\s+(months?|years?)\b', text):
        value = words[number] if number in words else float(number)
        if value * (12 if unit.startswith('year') else 1) == months: return True
    return False


def _stated_date(excerpt, value):
    text = normalized_name(excerpt)
    parts = value.split('-')
    if not re.search(r'(?<!\d)' + parts[0] + r'(?!\d)', text): return False
    if len(parts) == 1: return True
    if re.search(r'(?<!\d)' + re.escape(value) + r'(?!\d)', text): return True
    month = int(parts[1])
    names = [calendar.month_name[month].casefold(), calendar.month_abbr[month].casefold()]
    month_text = r'(?:' + '|'.join(names) + r')\.?'
    year = re.escape(parts[0])
    separators = r'[\s,]+'
    if len(parts) == 2:
        expressions = [month_text + separators + year, year + separators + month_text,
            month_text + r'\s+\d{1,2}(?:st|nd|rd|th)?' + separators + year,
            r'\d{1,2}(?:st|nd|rd|th)?\s+' + month_text + separators + year]
    else:
        day = '0?' + str(int(parts[2])) + r'(?:st|nd|rd|th)?'
        expressions = [day + r'\s+' + month_text + separators + year,
            month_text + r'\s+' + day + separators + year,
            year + separators + month_text + r'\s+' + day]
    # All stated components must occur in one date expression. Do not combine
    # June 2025 with the day from a separate July 2026 date elsewhere in the answer.
    return any(re.search(r'(?<!\w)' + expression + r'(?!\w)', text) for expression in expressions)


def interpretation_semantic_checks(payload, question, item=None):
    """Separate semantic claims from exact evidence anchors and numeric validation."""
    result = InterpretationOutput.model_validate(payload)
    blocks, refs, fields = [], [], []
    for claim in result.claims:
        if not claim.evidence_excerpt: continue
        if claim.evidence_excerpt not in question['answer']:
            raise ValueError('Interpretation cited text not present in the answer.')
        for field in claim.changed_fields:
            value = getattr(claim, field)
            if field == 'experience_months' or value in (None, 'unknown'): continue
            statement = (f"For {claim.name}, attribution is {value}. Personal means the user actually performed it; team means teammates only; observed means watching only; denied means explicitly not personally performed."
                if field == 'attribution' else f"For the user's {claim.name} work, {field} is {value}.")
            block_id = str(len(blocks))
            blocks.append({'id': block_id, 'text': claim.evidence_excerpt,
                'reference_context': {'source_title': (item or {}).get('title'),
                    'existing_skills': (item or {}).get('skill_names', []),
                    'question': question.get('question')}})
            refs.append({'block_id': block_id, 'excerpt': statement})
            fields.append((claim.skill_id, field))
    for fact in result.review_evidence:
        data = fact.model_dump(mode='json')
        if any(ref.source_id != 'answer' or ref.quote not in question['answer'] for ref in fact.evidence):
            raise ValueError('Interview evidence must quote this answer exactly.')
        block_id = str(len(blocks))
        blocks.append({'id': block_id, 'text': '\n'.join(ref.quote for ref in fact.evidence),
            'reference_context': {'source_title': (item or {}).get('title'), 'question': question.get('question')}})
        refs.append({'block_id': block_id, 'excerpt': fact_statement(data)})
        fields.append(('review', fact_key(data)))
        previous = [f for f in (item or {}).get('review_evidence', []) if fact_key(f) == fact_key(data) and f['status'] == 'supported']
        if any(f.get('value') != fact.value for f in previous) and fact.status == 'supported':
            # A quotation proving the new claim is not permission to silently
            # erase an incompatible earlier claim. Check their relationship too.
            block_id = str(len(blocks))
            blocks.append({'id': block_id, 'text': 'Earlier supported account: ' + '\n'.join(str(f.get('value')) for f in previous) +
                '\nLatest user statement: ' + '\n'.join(ref.quote for ref in fact.evidence)})
            refs.append({'block_id': block_id, 'excerpt': 'The latest statement refines the earlier account without contradiction, or explicitly corrects that earlier account.'})
            fields.append(('review-consistency', fact_key(data)))
    return blocks, refs, fields


def validate_review_interpretation(payload, item, question):
    """Review statements are user declarations, not claims to prove against a CV.

    Topic admission happens in the interview router. Retain structural/source
    checks here; the literal answer and prior CV remain in versioned history.
    """
    result = InterpretationOutput.model_validate(payload)
    if result.item_id != item['id'] or result.answer_revision != question['answer_revision']:
        raise ValueError('Interpretation refers to a different source or answer.')
    claimed = [claim.skill_id for claim in result.claims]
    if len(set(claimed)) != len(claimed):
        raise ValueError('Interpretation duplicated a skill claim.')
    for claim in result.claims:
        if skill_id(claim.name) != claim.skill_id or len(set(claim.changed_fields)) != len(claim.changed_fields):
            raise ValueError('Interpretation returned an invalid skill or field identity.')
    facts = [fact_key(f.model_dump(mode='json')) for f in result.review_evidence]
    if len(set(facts)) != len(facts):
        raise ValueError('Interview evidence duplicated a field.')
    if len([f for f in item.get('review_evidence', []) if fact_key(f) not in set(facts)]) + len(facts) > 240:
        raise ValueError('This experience has reached its review evidence limit.')
    if set(result.resolved_uncertainties) & set(result.remaining_uncertainties):
        raise ValueError('Interpretation returned conflicting uncertainty states.')
    data = result.model_dump(mode='json')
    data['summary'] = 'Updated your experience from your review answer.'
    return data


def validate_interpretation(payload, item, question, semantic_support=frozenset()):
    result = InterpretationOutput.model_validate(payload)
    if result.item_id != item['id'] or result.answer_revision != question['answer_revision']:
        raise ValueError('Interpretation refers to a different source or answer.')
    answer = question['answer']
    existing = set(item['skill_ids']) | {c['skill_id'] for c in item.get('skill_claims', [])}
    claimed = [claim.skill_id for claim in result.claims]
    if len(set(claimed)) != len(claimed): raise ValueError('Interpretation duplicated a skill claim.')
    if question['uncertainty'] in {'personal_contribution', 'responsibility'} and not existing.issubset(claimed):
        raise ValueError('Interpretation did not account for every source skill attribution.')
    for claim in result.claims:
        if skill_id(claim.name) != claim.skill_id: raise ValueError('Interpretation returned an invalid skill identity.')
        fields = set(claim.changed_fields)
        if len(fields) != len(claim.changed_fields): raise ValueError('Interpretation duplicated a field.')
        excerpt = claim.evidence_excerpt
        if excerpt is None:
            if (question['uncertainty'] not in {'personal_contribution', 'responsibility'} or
                    claim.skill_id not in existing or claim.attribution != 'unknown' or fields != {'attribution'}):
                raise ValueError('A changed personal claim requires answer evidence.')
        elif excerpt not in answer:
            raise ValueError('Interpretation cited text not present in the answer.')
        if claim.skill_id not in existing and (claim.attribution != 'personal' or 'attribution' not in fields or
                not excerpt or (not re.search(r'(?<!\w)' + re.escape(normalized_name(claim.name)) + r'(?!\w)', normalized_name(excerpt))
                                and (claim.skill_id, 'attribution') not in semantic_support)):
            raise ValueError('A new skill requires an explicit personal mention in the answer.')
        for field, declared in (('proficiency', 'proficiency'), ('experience_months', 'experience_months'),
                                ('skill_level', 'skill_level'), ('skill_level_rationale', 'skill_level')):
            if getattr(claim, field) is not None and declared not in fields:
                raise ValueError('Interpretation supplied an attribute outside its declared changes.')
        if 'skill_level' in fields:
            existing_claim = next((c for c in item.get('skill_claims', []) if c['skill_id'] == claim.skill_id), None)
            personal = claim.attribution == 'personal' if 'attribution' in fields else bool(existing_claim and existing_claim['attribution'] == 'personal')
            if claim.skill_level is None or not claim.skill_level_rationale or not excerpt:
                raise ValueError('A skill level needs its rationale and the supporting answer excerpt.')
            if not personal:
                raise ValueError('A skill level requires the user’s personal work with that skill.')
        if claim.proficiency is not None and (not excerpt or (normalized_name(claim.proficiency) not in normalized_name(excerpt)
                and (claim.skill_id, 'proficiency') not in semantic_support)):
            raise ValueError('Proficiency must preserve the user’s wording.')
        if claim.experience_months is not None and (not excerpt or not _stated_months(excerpt, claim.experience_months)):
            raise ValueError('Known skill duration must be explicitly stated without invented precision.')
        if 'assistance' in fields and claim.assistance != 'unknown':
            indicators = {'independent': r'\b(independently|on my own|without (?:any )?(?:help|guidance|supervision))\b',
                'assisted': r'\b(assist(?:ed|ing)?|help(?:ed|ing)?|guidance|guided)\b',
                'supervised': r'\b(supervis(?:ed|ion|or)|mentor|tutor|guidance|guided)\b'}
            if not excerpt or (not re.search(indicators[claim.assistance], normalized_name(excerpt))
                               and (claim.skill_id, 'assistance') not in semantic_support):
                raise ValueError('Assistance or independence must be stated, not inferred.')
    changed_fact_keys = {fact_key(f.model_dump(mode='json')) for f in result.review_evidence}
    if len([f for f in item.get('review_evidence', []) if fact_key(f) not in changed_fact_keys]) + len(result.review_evidence) > 240:
        raise ValueError('This experience has reached its review evidence limit. Existing answers are retained; use a new saved source for more evidence.')
    seen = set()
    for fact in result.review_evidence:
        data = fact.model_dump(mode='json')
        identity = fact_key(data)
        if fact.skill_name and skill_id(fact.skill_name) not in existing | set(claimed):
            raise ValueError('Skill evidence must refer to an existing or personally supported new skill.')
        if identity in seen: raise ValueError('Interview evidence duplicated a field.')
        seen.add(identity)
        if any(ref.source_id != 'answer' or ref.quote not in answer for ref in fact.evidence):
            raise ValueError('Interview evidence cited a different answer.')
        if ('review', identity) not in semantic_support:
            raise ValueError('Interview evidence requires semantic support.')
        previous = [f for f in item.get('review_evidence', []) if fact_key(f) == identity and f['status'] == 'supported']
        if any(f.get('value') != fact.value for f in previous) and fact.status == 'supported' and ('review-consistency', identity) not in semantic_support:
            raise ValueError('A conflicting earlier account must be retained or explicitly corrected.')
    resolved, remaining = set(result.resolved_uncertainties), set(result.remaining_uncertainties)
    if resolved & remaining or len(resolved) != len(result.resolved_uncertainties) or len(remaining) != len(result.remaining_uncertainties):
        raise ValueError('Interpretation returned conflicting uncertainty states.')
    if question['uncertainty'] not in resolved | remaining:
        raise ValueError('Interpretation did not state whether this uncertainty remains.')
    if result.resolution == 'resolved' and remaining: raise ValueError('Resolved interpretation cannot contain unresolved facts.')
    if result.resolution != 'resolved' and not remaining: raise ValueError('Partial or unanswerable interpretation must retain uncertainty.')
    if result.resolution == 'unanswerable' and resolved: raise ValueError('Inability to clarify cannot resolve a factual uncertainty.')
    supported_fields = {field for claim in result.claims if claim.evidence_excerpt
        for field in claim.changed_fields if (
            (field == 'attribution' and claim.attribution != 'unknown') or
            (field == 'assistance' and claim.assistance != 'unknown') or
            (field == 'proficiency' and claim.proficiency is not None) or
            (field == 'experience_months' and claim.experience_months is not None))}
    for uncertainty in resolved:
        required = {'personal_contribution': 'attribution', 'responsibility': 'attribution',
                    'proficiency': 'proficiency', 'duration': 'experience_months'}.get(uncertainty)
        if required and required not in supported_fields:
            raise ValueError('A resolved uncertainty requires a supported change to that fact.')
        if uncertainty == 'qualification' and not result.statement_excerpt:
            raise ValueError('A resolved qualification requires the user’s supported statement.')
        if uncertainty == 'date' and (not result.dates or not any(
                getattr(result.dates, field) is not None and getattr(result.dates, field) is not False
                for field in result.dates.changed_fields)):
            raise ValueError('A resolved date requires explicitly stated date information.')
    if resolved & {'personal_contribution', 'responsibility'} and any(
            claim.attribution == 'unknown' and 'attribution' in claim.changed_fields for claim in result.claims):
        raise ValueError('Unknown personal attribution must remain unresolved.')
    if result.dates:
        if result.dates.evidence_excerpt not in answer: raise ValueError('Date evidence is not in the answer.')
        if len(set(result.dates.changed_fields)) != len(result.dates.changed_fields): raise ValueError('Date changes were duplicated.')
        merged = {field: item.get(field) for field in ('start_date', 'end_date', 'ongoing')}
        for field in result.dates.changed_fields: merged[field] = getattr(result.dates, field)
        validate_item_dates(merged)
        for field in ('start_date', 'end_date'):
            value = getattr(result.dates, field)
            if value and (field not in result.dates.changed_fields or not _stated_date(result.dates.evidence_excerpt, value)):
                raise ValueError('A clarified date must retain its explicitly stated precision and scope.')
        if result.dates.ongoing and ('ongoing' not in result.dates.changed_fields or not re.search(
                r'\b(present|ongoing|currently|still|continuing)\b', normalized_name(result.dates.evidence_excerpt))):
            raise ValueError('An ongoing date must be explicitly stated.')
    if result.statement_excerpt is not None and result.statement_excerpt not in answer:
        raise ValueError('The clarified statement is not present in the answer.')
    if not result.claims and not result.dates and not result.statement_excerpt and not result.review_evidence and resolved:
        raise ValueError('Resolving a factual claim requires a supported interpretation.')
    data = result.model_dump()
    labels = {'personal': 'personal contribution', 'team': 'team contribution only',
              'observed': 'observation only', 'denied': 'not personally performed', 'unknown': 'personal contribution remains unknown'}
    summaries = [f"{claim.name}: {labels[claim.attribution]}" if 'attribution' in claim.changed_fields
        else f"{claim.name}: clarified {', '.join(claim.changed_fields).replace('_', ' ')}" for claim in result.claims]
    if result.review_evidence: summaries.append('Retained your role and skill evidence')
    if result.dates: summaries.append('Updated explicitly stated dates')
    if result.statement_excerpt: summaries.append('Retained your clarified statement')
    data['summary'] = '; '.join(summaries)[:2000] or 'The relevant facts remain unknown.'
    return data

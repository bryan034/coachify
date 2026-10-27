from copy import deepcopy
import calendar
import hashlib
import json
import re
import unicodedata
from app.schemas.cv import Extraction, InterpretationOutput, validate_item_dates, date_bounds


def normalized_name(name):
    return ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()


def skill_id(name): return 'skill:' + normalized_name(name)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def validate_extraction(payload, blocks, cv_id):
    extraction = Extraction.model_validate(payload)
    source = {block['id']: block for block in blocks}
    items = []
    # Item IDs depend on source evidence and section, never display names or model order.
    # Exact duplicated evidence is rejected; repeated titles on distinct evidence remain separate.
    for item in extraction.items:
        evidence = []
        for ref in item.evidence:
            block = source.get(ref.block_id)
            if not block or ref.excerpt not in block['text']:
                raise ValueError('The model returned unsupported source evidence. Retry this upload.')
            evidence.append({'id': ref.block_id, 'location': block['location'], 'excerpt': ref.excerpt})
        identity = digest({'cv': cv_id, 'kind': item.kind, 'evidence': sorted(evidence, key=lambda e: (e['id'], e['excerpt']))})[:32]
        names_by_id = {}
        for name in item.skill_names + ([item.title] if item.kind == 'skill' else []):
            names_by_id.setdefault(skill_id(name), name)
        names = list(names_by_id.values())
        # A purported explicit skill needs that exact name in its evidence; inferred
        # skills remain distinctly labelled and can be narrowed by the user.
        if item.explicit:
            text = normalized_name(' '.join(e['excerpt'] for e in evidence))
            if any(normalized_name(name) not in text for name in names):
                raise ValueError('The model labelled an unsupported skill as explicit. Retry this upload.')
        # A valid calendar value is not evidence that the source stated it. Keep
        # each excerpt separate so components cannot be combined across citations.
        for value in (item.start_date, item.end_date):
            if value and not any(_stated_date(ref['excerpt'], value) for ref in evidence):
                raise ValueError('The model returned an unsupported date or invented date precision. Retry this upload.')
        if item.ongoing and not any(re.search(
                r'\b(present|ongoing|currently|still|continuing)\b', normalized_name(ref['excerpt']))
                for ref in evidence):
            raise ValueError('The model returned an ongoing date not stated in the source. Retry this upload.')
        items.append({'id': identity, 'kind': item.kind, 'title': item.title, 'description': item.description,
                      'provenance': 'explicit' if item.explicit else 'inferred', 'evidence': evidence,
                      'skill_ids': [skill_id(name) for name in names], 'skill_names': names,
                      'category': item.category or 'unspecified', 'proficiency': item.proficiency,
                      'experience_months': item.experience_months, 'context': item.context,
                      'start_date': item.start_date, 'end_date': item.end_date, 'ongoing': item.ongoing,
                      'removed': False, 'supporting_item_ids': [], 'uncertainties': item.uncertainties})
    if len({item['id'] for item in items}) != len(items):
        raise ValueError('The model duplicated a source claim. Retry this upload.')
    for index, parsed in enumerate(extraction.items):
        if any(ref < 0 or ref >= len(items) or ref == index for ref in parsed.supporting_items):
            raise ValueError('The model returned an invalid source relationship. Retry this upload.')
        items[index]['supporting_item_ids'] = [items[ref]['id'] for ref in parsed.supporting_items]
    by_id = {item['id']: item for item in items}
    completed, active = set(), set()
    def visit(identifier):
        if identifier in completed: return
        if identifier in active: raise ValueError('The model returned circular source relationships. Retry this upload.')
        active.add(identifier)
        for parent in by_id[identifier]['supporting_item_ids']: visit(parent)
        active.remove(identifier)
        completed.add(identifier)
    for item in items: visit(item['id'])
    return items


def _base_claims(item):
    result = {}
    for index, identifier in enumerate(item['skill_ids']):
        names = item.get('skill_names', [])
        result[identifier] = {'skill_id': identifier, 'name': names[index] if index < len(names) else item['title'],
            'attribution': 'unknown', 'assistance': 'unknown', 'proficiency': item.get('proficiency'),
            'experience_months': item.get('experience_months'), 'evidence': deepcopy(item['evidence']),
            'evidence_type': item['provenance'], 'support_uncertain': item.get('support_uncertain', False)}
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
        item['_claims'] = _base_claims(item)
    events = [(q['interpretation'].get('applied_sequence', 0), 0, q['item_id'], q)
              for q in document.get('clarifications', []) if q.get('interpretation')]
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
            for field in patch['changed_fields']: claim[field] = patch[field]
            if 'attribution' in patch['changed_fields']:
                claim['support_uncertain'] = patch['attribution'] == 'unknown'
            claim['evidence_type'] = 'user_clarified'
            if patch.get('evidence_excerpt'):
                claim['evidence'] = [{'id': 'answer:' + question['id'], 'location': 'Your clarification',
                                     'excerpt': patch['evidence_excerpt']}]
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
    for item in items:
        claims = list(item.pop('_claims').values())
        item.pop('_field_sequences', None)
        item['skill_claims'] = claims
        active = [claim for claim in claims if claim['attribution'] not in {'team', 'observed', 'denied'}]
        item['skill_ids'], item['skill_names'] = [c['skill_id'] for c in active], [c['name'] for c in active]
        item['support_uncertain'] = any(claim['support_uncertain'] for claim in active)
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
            if q['item_id'] == item['id'] and q.get('interpretation') and q['interpretation'].get('statement_excerpt')]
        if statements: value['clarified_statements'] = [normalized_name(text) for text in statements]
        value['claims'] = [{key: claim[key] for key in ('skill_id', 'attribution', 'assistance',
            'proficiency', 'experience_months', 'support_uncertain')} for claim in item['skill_claims']]
        value['claims'].sort(key=lambda claim: claim['skill_id'])
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


def validate_interpretation(payload, item, question):
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
                not excerpt or not re.search(r'(?<!\w)' + re.escape(normalized_name(claim.name)) + r'(?!\w)', normalized_name(excerpt))):
            raise ValueError('A new skill requires an explicit personal mention in the answer.')
        for field in ('proficiency', 'experience_months'):
            if getattr(claim, field) is not None and field not in fields:
                raise ValueError('Interpretation supplied an attribute outside its declared changes.')
        if claim.proficiency is not None and (not excerpt or normalized_name(claim.proficiency) not in normalized_name(excerpt)):
            raise ValueError('Proficiency must preserve the user’s wording.')
        if claim.experience_months is not None and (not excerpt or not _stated_months(excerpt, claim.experience_months)):
            raise ValueError('Known skill duration must be explicitly stated without invented precision.')
        if 'assistance' in fields and claim.assistance != 'unknown':
            indicators = {'independent': r'\b(independently|on my own|without (?:any )?(?:help|guidance|supervision))\b',
                'assisted': r'\b(assist(?:ed|ing)?|help(?:ed|ing)?|guidance|guided)\b',
                'supervised': r'\b(supervis(?:ed|ion|or)|mentor|tutor|guidance|guided)\b'}
            if not excerpt or not re.search(indicators[claim.assistance], normalized_name(excerpt)):
                raise ValueError('Assistance or independence must be stated, not inferred.')
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
    if not result.claims and not result.dates and not result.statement_excerpt and resolved:
        raise ValueError('Resolving a factual claim requires a supported interpretation.')
    data = result.model_dump()
    labels = {'personal': 'personal contribution', 'team': 'team contribution only',
              'observed': 'observation only', 'denied': 'not personally performed', 'unknown': 'personal contribution remains unknown'}
    summaries = [f"{claim.name}: {labels[claim.attribution]}" if 'attribution' in claim.changed_fields
        else f"{claim.name}: clarified {', '.join(claim.changed_fields).replace('_', ' ')}" for claim in result.claims]
    if result.dates: summaries.append('Updated explicitly stated dates')
    if result.statement_excerpt: summaries.append('Retained your clarified statement')
    data['summary'] = '; '.join(summaries)[:2000] or 'The relevant facts remain unknown.'
    return data

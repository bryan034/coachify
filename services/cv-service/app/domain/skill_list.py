"""Merge CV skills, chat-built Skills Profile skills and manual capabilities into one list per skill identity."""
from elo_shared.skill_groups import skill_groups, skill_subgroups
from app.domain.names import normalized_name

APPLICATION_ORDER = ['guided_application', 'independent_application', 'complex_application']
LEVEL_ORDER = {'rated': 3, 'assumed': 2, 'uncertain': 1}
BASIS_ORDER = ['none', 'declared', 'draft', 'described', 'proficiency', 'application', 'level']


def _strength(entry):
    level = entry.get('level') or {}
    application = entry.get('application')
    return (LEVEL_ORDER.get(level.get('status'), 0) if level.get('level') is not None else 0, level.get('level') or 0,
            APPLICATION_ORDER.index(application) + 1 if application else 0, BASIS_ORDER.index(entry['basis']))


def _strongest_application(estimates, name):
    levels = [e['level'] for e in estimates if normalized_name(e['skill_name']) == normalized_name(name) and e['level'] in APPLICATION_ORDER]
    return max(levels, key=APPLICATION_ORDER.index) if levels else None


def cv_entries(cv):
    if not cv: return []
    items = {item['id']: item for item in cv['items']}
    review = cv.get('review_summary') or {}
    result = []
    for skill in cv['skills']:
        application = _strongest_application(cv.get('skill_estimates', []), skill['name'])
        level = skill.get('skill_level')
        basis = ('level' if level and level.get('level') is not None else 'application' if application
                 else 'proficiency' if skill.get('proficiency') else 'none')
        sources = []
        for source in skill.get('sources') or []:
            item = items.get(source['item_id'])
            sources.append({'kind': 'cv', 'id': source['item_id'], 'title': item['title'] if item else None,
                'item_kind': item['kind'] if item else None, 'attribution': source['attribution'], 'assistance': source['assistance'],
                'evidence': [{'quote': e['excerpt'], 'location': e.get('location')} for e in source['evidence']]})
        result.append({'canonical_skill_id': skill.get('canonical_skill_id'), 'name': skill['name'], 'category': skill.get('category'),
            'level': level, 'application': application, 'proficiency': skill.get('proficiency'), 'basis': basis,
            'added_in_review': skill['skill_id'] in review.get('added_skill_ids', []),
            'note': review.get('skill_notes', {}).get(skill['skill_id']), 'sources': sources})
    return result


def chat_entries(profile):
    if not profile: return []
    draft = profile['status'] == 'draft'
    return [{'canonical_skill_id': skill.get('canonical_skill_id'), 'name': skill['name'], 'category': None,
             'level': None, 'application': None, 'proficiency': None, 'basis': 'draft' if draft else 'described',
             'added_in_review': False, 'note': None,
             'sources': [{'kind': 'chat', 'id': entry['id'], 'title': entry['title'], 'item_kind': entry['kind'], 'draft': draft,
                          'description': skill['description'],
                          'facts': [{'field': field, 'value': value.get('value'), 'status': value['status']} for field, value in skill['dimensions'].items()],
                          'evidence': [{'quote': e['quote'], 'location': None} for e in skill['evidence']]}]}
            for entry in profile['entries'] for skill in entry['skills']]


def declaration_entries(declarations):
    if not declarations: return []
    result = []
    for declaration in declarations['declarations']:
        extra = [c['description'] for c in declaration.get('contributions') or [] if c['description'] != declaration['description']]
        result.append({'canonical_skill_id': declaration.get('canonical_skill_id'), 'name': declaration['name'], 'category': None,
            'level': None, 'application': None, 'proficiency': None, 'basis': 'declared', 'added_in_review': False, 'note': None,
            'sources': [{'kind': 'declaration', 'id': declaration['id'], 'description': '\n\n'.join([declaration['description'], *extra])}]})
    return result


def merge(entries):
    """One entry per skill: the canonical ID when the registry knows the skill, otherwise its normalised name.

    An unresolved source joins a same-name canonical skill only when the name identifies a single skill.
    """
    names = {}
    for entry in entries:
        if entry['canonical_skill_id']:
            names.setdefault(normalized_name(entry['name']), set()).add(entry['canonical_skill_id'])
    merged = {}
    for entry in entries:
        name = normalized_name(entry['name'])
        matches = names.get(name, set())
        resolved = next(iter(matches)) if len(matches) == 1 else None
        key = entry['canonical_skill_id'] or resolved or 'name:' + name
        current = merged.get(key)
        if current is None:
            merged[key] = {**entry, 'key': key, 'sources': list(entry['sources'])}
            continue
        if _strength(entry) > _strength(current):
            current.update({field: entry[field] for field in ('level', 'application', 'proficiency', 'basis')})
        current['canonical_skill_id'] = current['canonical_skill_id'] or entry['canonical_skill_id']
        current['category'] = current['category'] or entry['category']
        current['added_in_review'] = current['added_in_review'] or entry['added_in_review']
        current['note'] = current['note'] or entry['note']
        current['sources'].extend(entry['sources'])
    return list(merged.values())


def skill_list(cv, profile, declarations, unavailable):
    skills = merge([*cv_entries(cv), *chat_entries(profile), *declaration_entries(declarations)])
    pairs = [(skill['name'], skill['category']) for skill in skills]
    for skill in skills: skill.pop('category')
    return {'cv_id': cv['id'] if cv else None, 'cv_version': cv['version'] if cv else None,
            'profile_version': profile['version'] if profile else None,
            'declarations_version': declarations['version'] if declarations else None,
            'unavailable': unavailable, 'skills': skills,
            'skill_groups': skill_groups(pairs), 'skill_subgroups': skill_subgroups(pairs)}

"""Application-owned item identities and conservative, explicit skill mapping."""
import json
from pathlib import Path
from uuid import uuid4
from app.domain.skills import canonical_skill_id
from app.repositories.goals import GoalError
from app.schemas.jd import JDExtraction

REGISTRY = json.loads((Path(__file__).parents[1] / 'data' / 'skill-registry.json').read_text())
MAPPING_VERSION = REGISTRY['version']
ALIASES = {(category.casefold(), name.casefold()): skill['id'] for skill in REGISTRY['skills']
           for category in skill['categories'] for name in skill['names']}
METADATA = ('role', 'field', 'company', 'location', 'seniority_level', 'job_url')


def prepare(content, previous=None, *, extracted=False, map_skills=True):
    data = content.model_dump(mode='json')
    old = {}
    if previous:
        old = {s.item_id: s.model_dump(mode='json') for s in previous.skills}
        old.update({r.requirement_id: r.model_dump(mode='json') for r in previous.non_skill_requirements})
    ids, groups, names, mapped_ids = set(), {}, set(), set()
    for kind in ('skills', 'non_skill_requirements'):
        for item in data[kind]:
            key = 'item_id' if kind == 'skills' else 'requirement_id'
            item[key] = str(uuid4()) if extracted or not item.get(key) else item[key]
            if item[key] in ids:
                raise GoalError('Each skill or condition needs a distinct item identity.', 422)
            ids.add(item[key])
            item['source_urls'] = old[item[key]].get('source_urls',[]) if item[key] in old and not extracted else [data['job_url']] if data['job_url'] else []
            if item.get('group_id'):
                group = item['group_id']
                if group in groups and groups[group] != item['group_operator']:
                    raise GoalError('Items in one alternatives group must use the same AND/OR rule.', 422)
                groups[group] = item['group_operator']
            if kind == 'skills':
                name = (' '.join(item['name'].casefold().split()), ' '.join(item['category'].casefold().split()))
                if name in names:
                    raise GoalError('Combine duplicate skill entries before saving.', 422)
                names.add(name)
                if map_skills:
                    previous_item=old.get(item[key],{})
                    if previous_item.get('skill_id') and (item['name'],item['category']) == (previous_item.get('name'),previous_item.get('category')):
                        item['skill_id']=previous_item['skill_id']
                    else:
                        try: item['skill_id'] = canonical_skill_id(item['name'], item['category'], ALIASES)
                        except ValueError: item['skill_id'] = None
                if item.get('skill_id') in mapped_ids:
                    item['skill_id']=None  # Keep ambiguous duplicate mentions for review, never invent an identity.
                if item.get('skill_id'): mapped_ids.add(item['skill_id'])
                if item['origin'] == 'employer' and item['priority'] == 'suggested':
                    raise GoalError('Label inferred skills as suggested guidance.', 422)
                if item['origin'] == 'generated_guidance' and (item['priority'] != 'suggested' or item['evidence'] is not None):
                    raise GoalError('Guidance must be suggested and cannot claim employer evidence.', 422)
            elif item['origin'] == 'generated_guidance' and item['priority'] != 'suggested':
                raise GoalError('Exploration guidance is not an employer condition.', 422)
            comparable = {k: v for k, v in item.items() if k != 'correction'}
            original = {k: v for k, v in old.get(item[key], {}).items() if k != 'correction'}
            item['correction'] = 'extracted' if extracted else old.get(item[key], {}).get('correction', 'user') if comparable == original else 'user'
    return JDExtraction.model_validate(data)

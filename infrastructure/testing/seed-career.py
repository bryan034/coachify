"""Seed labelled canonical goals in an explicitly disposable browser-test stack.

This script has no HTTP route and is mounted only by compose.test.yaml. Confirmation
still goes through the real owner-authenticated Career API after fixture setup.
"""
import json
import os
import re
import sys
from datetime import timedelta
from uuid import UUID

from bson import ObjectId
from pymongo import MongoClient
from app.repositories.goals import GoalStore, now
from app.schemas.analysis import CareerGoal


def main():
    if os.getenv('COACHIFY_SYNTHETIC_TEST_FIXTURES') != '1':
        raise RuntimeError('Canonical seeding is available only in the disposable test override.')
    raw = sys.stdin.read(65537)
    if len(raw.encode()) > 65536:
        raise ValueError('Synthetic fixture exceeds its limit.')
    body = json.loads(raw)
    owner = str(UUID(body['owner']))
    if owner != body['owner'] or not body.get('role', '').startswith('Synthetic '):
        raise ValueError('Use a labelled synthetic owner and role.')
    if os.environ.get('MONGODB_DATABASE') != 'coachify_career':
        raise ValueError('Unexpected disposable database name.')
    client = MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000)
    try:
        store = GoalStore(client['coachify_career'])
        stamp = now()
        if body.get('goal_id'):
            goal = store.goals.find_one({'_id': ObjectId(body['goal_id']), 'user_id': owner})
            if not goal or not goal.get('role', '').startswith('Synthetic '):
                raise ValueError('Synthetic goal was not found for this owner.')
            goal = CareerGoal.model_validate({k: v for k, v in goal.items() if k in CareerGoal.model_fields or k == '_id'})
        else:
            exploration = body.get('target_type') == 'career_exploration'
            origin = 'user_declaration' if exploration else 'employer'
            skills = []
            for index, skill in enumerate(body.get('skills', [])):
                name = skill['name']
                slug = re.sub(r'[^a-z0-9]+', '_', name.casefold()).strip('_')
                skills.append({'skill_id': 'fixture.' + (slug or str(index)), 'name': name,
                    'category': skill.get('category', 'synthetic'), 'priority': 'preferred' if exploration else 'required',
                    'origin': origin, 'evidence': skill.get('evidence') or 'Synthetic personal guidance for ' + name + '.'})
            requirements = []
            for index, condition in enumerate(body.get('conditions', [])):
                category = str(condition.get('category', 'qualification')).casefold()
                if category == 'qualifications': category = 'qualification'
                requirements.append({'requirement_id': 'fixture-condition-' + str(index), 'category': category,
                    'description': condition['description'], 'priority': 'preferred' if exploration else 'required',
                    'evidence': condition.get('evidence') or condition['description'], 'origin': origin})
            goal = CareerGoal.model_validate({'_id': str(ObjectId()), 'user_id': owner, 'version': 1,
                'created_at': stamp, 'updated_at': stamp, 'skill_mapping_version': 'synthetic-fixture-v1',
                'target_type': 'career_exploration' if exploration else 'specific_job', 'role': body['role'],
                'field': body.get('field', 'Synthetic field'), 'company': body.get('company'), 'skills': skills,
                'non_skill_requirements': requirements, 'requirements_source': 'career_exploration' if exploration else 'pasted_jd',
                'readiness': 'ready' if skills else 'pending', 'generation_version': 'synthetic-fixture-v1',
                'generation': {'provider': 'fixture', 'model': 'fixture-model', 'prompt_version': 'synthetic-fixture-v1',
                    'schema_version': 'analysis-v1', 'generated_at': stamp}})
            store.persist_target(goal)
        store.state.update_one({'_id': owner}, {'$set': {'goal_id': ObjectId(goal.id),
            'dependent_results_need_review': True,
            'workspace': {'session_id': goal.id, 'kind': 'exploration' if goal.target_type == 'career_exploration' else 'jd',
                'review_id': goal.id, 'revision': goal.version, 'run_id': str(ObjectId()), 'phase': 'ready',
                'coverage': [], 'expires_at': stamp + timedelta(hours=24), 'updated_at': stamp}},
            '$inc': {'version': 1}, '$unset': {'cv_confirmation': ''}}, upsert=True)
        current = store.current(owner)
        print(json.dumps({'id': goal.id, 'version': goal.version, 'selection_version': current['selection_version']}))
    finally:
        client.close()


if __name__ == '__main__':
    main()

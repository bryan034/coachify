"""One-off rewrite of records saved in shapes the service no longer reads."""
from bson import ObjectId
from bson.codec_options import CodecOptions
from app.repositories.question_memory import VERIFIED_EVIDENCE
from app.schemas.opportunity import CATEGORIES, FIELDS, SUMMARY_UNAVAILABLE, CategoryResult

RETIRED_GOAL_INDEXES = ('user_id_1_create_key_1', 'user_id_1_created_at_-1__id_-1')
RETIRED_INTRODUCTIONS = (
    "Hi, I’m elo’s Career Discovery assistant. This chat helps you choose a career "
    "direction and build a recommended skill set backed by research.\n\n"
    "To start, tell me a field or role you’re interested in, or describe the kind of work "
    "you enjoy. You can keep it broad—no CV, specific vacancy or specialisation is required.\n\n"
    "I’ll ask one focused question at a time when useful, then research representative roles "
    "once your direction is clear. You can ask questions or refine the results, and you’ll "
    "review and confirm before saving your goal.",
    "Hi, I’m elo’s Career Discovery assistant. This chat helps you choose a career "
    "direction and build a recommended skill set backed by research.\n\n"
    "To start, tell me a field or role you’re interested in, or describe the kind of work "
    "you enjoy. You can keep it broad—no CV, specific vacancy or specialisation is required.\n\n"
    "I will ask questions to understand your interests and personalise your goal for you, then "
    "research representative roles once we have enough context. You can ask questions or refine "
    "the results, and you’ll review and confirm before saving your goal.",
    "Hi, I’m elo’s career guidance assistant. I can help you explore career paths, "
    "compare roles, or talk through questions about jobs and internships.\n\n"
    "Tell me what’s on your mind, a field you’re curious about, or the kind of work you enjoy. "
    "You don’t need a CV or a clear direction to start. You can also ask how this chat works.\n\n"
    "As we talk, I’ll ask questions to understand your interests and preferences. "
    "Once we have enough context, I’ll research representative roles and suggest a skill set "
    "for your direction. You’ll review and confirm before saving your career goal.",
    "Hi, I’m elo’s career guidance assistant. I can help you explore career paths, "
    "compare roles, or talk through questions about jobs and internships.\n\n"
    "Tell me what’s on your mind, a field you’re curious about, or the kind of work you enjoy. "
    "You don’t need a CV or a clear direction to start. You can also ask how this chat works.\n\n"
    "As we talk, I’ll ask questions to understand your interests and preferences. "
    "Once we have enough context, I’ll research representative roles and suggest a skill set "
    "for your direction. Your career goal updates automatically as we refine your direction together.",
)
UNANSWERED = (None, 'unanswered', 'unsure', 'skipped')


def current_understanding(understanding):
    """Fold the removed broad_exploration and industry answers into the current fields."""
    value = dict(understanding)
    broad = value.pop('broad_exploration', None)
    value.pop('industry', None)
    role = value.get('role_family_or_work') or {}
    field = value.get('field') or {}
    if (isinstance(broad, dict) and broad.get('status') == 'known' and broad.get('value') == 'yes'
            and (role.get('status') in UNANSWERED or role.get('value') == field.get('value'))):
        value['role_family_or_work'] = {'status': 'known', 'value': 'keep it broad', 'evidence': broad.get('evidence')}
    return value


class StoredShapes:
    def __init__(self, database):
        db = database.with_options(codec_options=CodecOptions(tz_aware=True))
        self.goals, self.state, self.contexts, self.research = db.career_goals, db.career_state, db.research_contexts, db.interview_research

    def retired_goal_indexes(self, apply):
        names = [name for name in self.goals.index_information() if name in RETIRED_GOAL_INDEXES]
        if apply:
            for name in names:
                self.goals.drop_index(name)
        return len(names)

    def goal_storage_keys(self, apply):
        query = {'_id': {'$type': 'objectId'}, 'create_key': {'$exists': True}}
        if not apply:
            return self.goals.count_documents(query)
        return self.goals.update_many(query, {'$unset': {'create_key': ''}}).modified_count

    def review_baselines(self, apply):
        query = {'$or': [{'baseline': {'$exists': True}}, {'baseline_origins': {'$exists': True}}]}
        if not apply:
            return self.goals.count_documents(query)
        return self.goals.update_many(query, {'$unset': {'baseline': '', 'baseline_origins': ''}}).modified_count

    def discovery_introductions(self, apply):
        stored = {'role': 'assistant', 'content': {'$in': list(RETIRED_INTRODUCTIONS)}}
        query = {'kind': 'career_discovery', 'messages': {'$elemMatch': stored}}
        if not apply:
            return self.contexts.count_documents(query)
        return self.contexts.update_many(query, {'$pull': {'messages': stored}}).modified_count

    def discovery_understanding(self, apply):
        query = {'kind': 'career_discovery', '$or': [{'decision.understanding.broad_exploration': {'$exists': True}},
                                                     {'decision.understanding.industry': {'$exists': True}}]}
        rows = list(self.contexts.find(query, {'decision.understanding': 1}))
        changed = 0
        for row in rows:
            old = row['decision']['understanding']
            if apply:
                changed += self.contexts.update_one({'_id': row['_id'], 'decision.understanding': old},
                    {'$set': {'decision.understanding': current_understanding(old)}}).modified_count
        return changed if apply else len(rows)

    def active_discoveries(self, apply):
        owners = self.contexts.distinct('owner', {'kind': 'career_discovery'})
        adopted = 0
        for owner in owners:
            state = self.state.find_one({'_id': owner}) or {}
            if 'active_discovery' in state:
                continue
            latest = self.contexts.find_one({'owner': owner, 'kind': 'career_discovery'}, sort=[('created_at', -1)])
            goal = self.goals.find_one({'_id': state['goal_id'], 'user_id': owner}) if state.get('goal_id') else None
            same_chat = bool(goal and (goal.get('discovery') or {}).get('research_id', '').split(':')[0] == latest['_id'])
            if goal and not same_chat and goal['updated_at'] > latest['created_at']:
                continue
            adopted += 1
            if apply:
                self.state.update_one({'_id': owner}, {'$setOnInsert': {'version': 0, 'goal_id': None, 'receipts': []}}, upsert=True)
                self.state.update_one({'_id': owner, 'active_discovery': {'$exists': False}}, {'$set': {'active_discovery': latest['_id']}})
        return adopted

    def first_opportunity_reports(self, apply):
        query = {'intelligence.schema_version': 1}
        if not apply:
            return self.research.count_documents(query)
        return self.research.update_many(query, {'$unset': {'intelligence': ''}}).modified_count

    def summary_flags(self, apply):
        query = {'intelligence.warnings': SUMMARY_UNAVAILABLE, 'intelligence.summary_unavailable': {'$exists': False}}
        if not apply:
            return self.research.count_documents(query)
        return self.research.update_many(query, {'$set': {'intelligence.summary_unavailable': True}}).modified_count

    def unfinished_opportunity_jobs(self, apply):
        query = {'kind': 'opportunity_job', 'finished': False,
                 '$or': [{f'categories.{category}': {'$exists': False}} for category in CATEGORIES]}
        rows = list(self.contexts.find(query))
        for job in rows:
            missing = [k for k in CATEGORIES if k not in job['categories']]
            updates = {f'categories.{k}': CategoryResult().model_dump(mode='json') for k in missing}
            for category, result in job['categories'].items():
                kept = [f for f in result.get('findings', []) if f['field'] in FIELDS.get(category, ())]
                if len(kept) != len(result.get('findings', [])):
                    updates.update({f'categories.{category}': {**result, 'findings': kept, 'status': 'pending', 'error_code': None},
                                    f'evaluated.{category}': [], f'evaluation_complete.{category}': False})
            updates.update(requested=list(dict.fromkeys([*job.get('requested', []), *missing])), queries_planned=False, prefetched=True)
            if apply:
                self.contexts.update_one({'_id': job['_id'], 'finished': False}, {'$set': updates})
        return len(rows)

    def unverified_question_results(self, apply):
        pointers = list(self.contexts.find({'kind': 'question_result'}, {'research_id': 1}))
        ids = [ObjectId(p['research_id']) for p in pointers if ObjectId.is_valid(p.get('research_id'))]
        verified = {str(row['_id']) for row in self.research.find(
            {'_id': {'$in': ids}, 'generation.prompt_version': VERIFIED_EVIDENCE}, {'_id': 1})}
        stale = [p['_id'] for p in pointers if str(p.get('research_id')) not in verified]
        if apply and stale:
            self.contexts.delete_many({'_id': {'$in': stale}, 'kind': 'question_result'})
        return len(stale)

    def upgrade(self, apply=False):
        steps = (self.retired_goal_indexes, self.goal_storage_keys, self.review_baselines, self.discovery_introductions,
                 self.discovery_understanding, self.active_discoveries, self.first_opportunity_reports,
                 self.summary_flags, self.unfinished_opportunity_jobs, self.unverified_question_results)
        return {step.__name__: step(apply) for step in steps}

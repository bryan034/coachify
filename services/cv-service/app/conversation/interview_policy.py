"""Validate agent questions, completion and skill estimates against saved evidence."""
from copy import deepcopy
import logging
from app.domain.capabilities import normalized_name
from app.schemas.interview import InterviewDecision
from app.domain.review_context import clarification_context
from app.conversation.interview_memory import evidence_for, target_availability, topic_question_count, topic_discussed, MAX_TOPIC_QUESTIONS, MAX_TARGET_ATTEMPTS


logger = logging.getLogger(__name__)


class DecisionRejected(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def unproven_reason(item_id, refs, index):
    """Name the first unmet `reviewed` condition; content-free so it is safe to log."""
    if any(f['item_id'] == item_id and f['status'] == 'conflicting'
           and f['field'] in {'personal_contribution', 'responsibilities'} for f in index.values()):
        return 'conflict'
    if not any(r['field'] == 'personal_contribution' and r['status'] == 'supported'
               and r.get('attribution') in {'personal', 'shared'} for r in refs):
        return 'no_personal_ownership'
    if not {r['field'] for r in refs if r['status'] == 'supported'} & {'task_scope', 'skill_use', 'responsibilities'}:
        return 'no_task_evidence'
    return None


def validate_decision(decision, context, memory, *, user_stop=False, max_attempts=MAX_TARGET_ATTEMPTS):
    """Enforce evidence coverage and repetition rules without selecting a question."""
    decision = InterviewDecision.model_validate(decision)
    sources = {i['id']: i for i in context['sources']}
    index = context['evidence_index']
    coverage = deepcopy(memory['coverage'])
    focused = context.get('focused_source')
    previous = memory.get('focus_item_id')
    leaving = previous if decision.action == 'ask' and previous != decision.item_id else None
    if decision.action == 'ask':
        # A follow-up keeps the whole topic open, even if the model proposes
        # coverage for some of the fields it has just learned.
        coverage.pop(decision.item_id, None)
    for item in decision.coverage:
        if decision.action != 'finish' and item.item_id != leaving: continue
        if item.item_id not in sources: raise DecisionRejected('coverage_source', 'Coverage refers to an unavailable experience.')
        # Only open review topics take a new label. A closed topic keeps its saved
        # label: its facts are no longer in evidence_index, so it cannot be re-cited.
        if item.item_id in memory['coverage'] or item.item_id not in memory.get('topic_ids', sources):
            continue
        skipped_ownership = (any(t['field'] in {'personal_contribution', 'responsibilities'}
                                 for t in sources[item.item_id].get('review_dispositions', []))
                             or any(f['field'] in {'personal_contribution', 'responsibilities'}
                                    and f['status'] in {'unknown', 'skipped', 'not_applicable'}
                                    for f in sources[item.item_id].get('fields', [])))
        # Unusable citations prove nothing, so they are dropped rather than blocking the turn.
        valid_refs = [ref for ref in item.evidence_refs if index.get(ref, {}).get('item_id') == item.item_id]
        item = item.model_copy(update={'evidence_refs': valid_refs})
        if item.status == 'reviewed':
            # `reviewed` is an optional navigation label and never feeds skill estimates.
            # Without proof the topic closes with uncertainty; the next step stands.
            reason = 'skipped_ownership' if skipped_ownership else unproven_reason(item.item_id, [index[r] for r in valid_refs], index)
            if reason:
                logger.warning('CV interview coverage downgraded reason=%s action=%s', reason, decision.action)
                item = item.model_copy(update={'status': 'reviewed_with_gaps', 'evidence_refs': []})
        if item.status != 'reviewed' and not user_stop and not topic_discussed(memory, item.item_id):
            raise DecisionRejected('coverage_unvisited', 'Discuss an experience before deferring it or acknowledging its gaps.')
        coverage[item.item_id] = item.model_dump(mode='json')
    if (leaving in memory.get('topic_ids', []) and leaving not in coverage
            and topic_discussed(memory, leaving)):
        # Moving on closes a discussed topic; omitted coverage makes no claim
        # that all evidence is known or that the user has mastered a skill.
        coverage[leaving] = {'item_id': leaving, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
    if decision.action == 'recall':
        raise DecisionRejected('recall_unresolved', 'Recall requests must be resolved before publishing a reply.')
    if decision.recall_ids: raise DecisionRejected('unexpected_recall', 'Only recall actions may request earlier answers.')
    if decision.action == 'ask':
        if decision.item_id not in sources or not decision.targets:
            raise DecisionRejected('question_source', 'A question needs an available source and explicit evidence targets.')
        if not focused or focused['id'] != decision.item_id:
            raise DecisionRejected('question_unhydrated', 'Inspect the selected source before asking about it.')
        if not clarification_context(focused, evidence_for(focused))['clarification_targets']:
            raise DecisionRejected('question_no_ambiguity', 'This source has no material clarification remaining. Use its CV context and move to an ambiguous topic or finish.')
        if topic_question_count(memory, decision.item_id) >= MAX_TOPIC_QUESTIONS:
            raise DecisionRejected('question_topic_limit', 'This topic already has three questions. Move to another topic with questions remaining, or finish with gaps if all topics are covered.')
        open_targets = [target for target in decision.targets
                        if target_availability(focused, memory, target.field, target.skill_name,
                                               max_attempts=max_attempts) == 'open']
        if not open_targets:
            raise DecisionRejected('question_targets_closed', 'These targets are already known, declined, or repeatedly unproductive. Choose a distinct remaining gap or move on.')
        if len(open_targets) != len(decision.targets):
            raise DecisionRejected('question_targets_mixed', 'Remove known or exhausted targets; ask only the distinct remaining gap.')
    elif decision.targets or decision.item_id:
        raise DecisionRejected('unexpected_targets', 'Only questions may select an active source and targets.')
    if decision.action == 'finish' and not user_stop:
        for item_id in memory.get('topic_ids', []):
            # A user skip is accepted as a gap even if the planner omits this topic's coverage.
            skipped = any(q['item_id'] == item_id and (q.get('answer_status') == 'skipped' or q.get('skipped'))
                          for q in memory.get('questions', []))
            if item_id not in coverage and (skipped or (topic_question_count(memory, item_id) >= MAX_TOPIC_QUESTIONS
                                                        and topic_discussed(memory, item_id))):
                coverage[item_id] = {'item_id': item_id, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
        missing = [s['id'] for s in sources.values() if s['id'] in memory.get('topic_ids', [i['id'] for i in sources.values() if i['kind'] in {'project', 'experience'}]) and s['id'] not in coverage]
        if missing: raise DecisionRejected('finish_unvisited', 'Unvisited work/projects remain. Explore them or acknowledge their gaps after discussion.')
    for estimate in decision.estimates:
        if not focused or estimate.item_id != focused['id'] or normalized_name(estimate.skill_name) not in {normalized_name(c['name']) for c in focused.get('skill_claims', [])}:
            raise DecisionRejected('estimate_skill', 'A skill estimate must refer to a known skill on the focused experience.')
        refs = [index.get(ref) for ref in estimate.evidence_refs]
        if any(r is None or r['item_id'] != estimate.item_id or
               (r.get('skill_name') and normalized_name(r['skill_name']) != normalized_name(estimate.skill_name)) for r in refs):
            raise DecisionRejected('estimate_evidence', 'A skill estimate must cite matching source and skill evidence.')
        fields = {r['field']: r for r in refs if r['status'] == 'supported'}
        if estimate.level != 'insufficient_evidence':
            if any(f['status'] == 'conflicting' and f['field'] in {'personal_contribution', 'assistance', 'skill_use'} and (not f.get('skill_name') or normalized_name(f['skill_name']) == normalized_name(estimate.skill_name)) for f in evidence_for(focused)):
                raise DecisionRejected('estimate_conflict', 'Conflicting skill evidence must be clarified before a supported level can be estimated.')
            claims = (focused or {}).get('skill_claims', [])
            personal = next((c for c in claims if normalized_name(c['name']) == normalized_name(estimate.skill_name)), None)
            if not personal or personal['attribution'] != 'personal' or not {'personal_contribution', 'assistance', 'skill_use'} <= fields.keys():
                raise DecisionRejected('estimate_ownership', 'A personal skill estimate requires attributed personal work and concrete skill use.')
            if estimate.level == 'guided_application' and personal.get('assistance') not in {'assisted', 'supervised'}:
                raise DecisionRejected('estimate_guidance', 'Guided application requires explicit assistance evidence.')
            if estimate.level in {'independent_application', 'complex_application'} and personal.get('assistance') != 'independent':
                raise DecisionRejected('estimate_independence', 'Independent skill estimates require explicit independence.')
            if estimate.level == 'complex_application' and not {'complexity', 'problem_solving'} <= fields.keys():
                raise DecisionRejected('estimate_complexity', 'Complex application requires complexity and problem-solving evidence.')
    return decision, coverage

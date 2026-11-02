"""Explicit synthetic interview replies, never a production fallback."""
from copy import deepcopy

METADATA = {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': 'interview-1', 'schema_version': '1'}


class InterviewProvider:
    configured = True
    approve = True

    def __init__(self):
        self.calls = []
        self.evaluation = None
        self.plans = []
        self.before_plan = None

    def route(self, context):
        self.calls.append(deepcopy(context))
        if context['task'] == 'cv_interview_interpret':
            result = self.evaluation(context) if callable(self.evaluation) else self.evaluation
            return deepcopy(result or {'intent': 'side_question', 'reply': 'This helps distinguish your work from the team output.', 'actions': []}), METADATA
        if self.before_plan: self.before_plan(context)
        if self.plans:
            plan = self.plans.pop(0)
            return plan(context) if callable(plan) else deepcopy(plan), METADATA
        focus = context['focused_source']
        fields = {f['field']: f for f in focus.get('review_evidence', [])}
        declined = context['memory']['attempts'].get(focus['id'] + ':personal_contribution:', {}).get('declined')
        field = 'task_scope' if 'personal_contribution' in fields or declined else 'personal_contribution'
        return {'action': 'ask', 'reply': 'What did you personally build?' if field == 'personal_contribution' else 'What was the scope of your task?',
                'item_id': focus['id'], 'targets': [{'field': field}]}, METADATA

    def verify_evidence(self, blocks, refs, **kwargs):
        return frozenset((r['block_id'], r['excerpt']) for r in refs) if self.approve else frozenset()

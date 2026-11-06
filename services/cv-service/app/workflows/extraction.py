"""One extraction plus at most one repair. Each state change is saved, so an interrupted run resumes."""
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from pydantic import ValidationError
from app.domain.capabilities import validate_extraction, validate_other_information, evidence_requiring_semantic_check
from app.schemas.cv import Extraction
from app.domain.extraction_errors import ExtractionFailure
from app.domain.model_usage import ModelAdmissionError
from app.domain.extraction_feedback import feedback_for
from app.domain.review_context import prepare_review_items

WORKFLOW_VERSION = 'cv-extraction-5'


class ExtractionState(TypedDict, total=False):
    parsed: dict
    candidate: Any
    metadata: dict
    items: list
    other_information: list
    feedback: list
    needs_repair: bool
    repair_attempts: int


class ExtractionHarness:
    def __init__(self, cv_id, parse, call_model, observe, *, checkpointer, thread_id, verify_evidence=None, rewind_rejected=False):
        self.cv_id, self.parse, self.call_model, self.observe = cv_id, parse, call_model, observe
        self.thread_id, self.rewind_rejected = thread_id, rewind_rejected
        self.original = None
        self.verify_evidence = verify_evidence
        self.repair_attempted = False
        graph = StateGraph(ExtractionState)
        graph.add_node('parse', self._parse)
        graph.add_node('extract', self._extract)
        graph.add_node('validate', self._validate)
        graph.add_node('repair', self._repair)
        graph.add_node('prepare_review', self._prepare_review)
        graph.add_edge(START, 'parse')
        graph.add_edge('parse', 'extract')
        graph.add_edge('extract', 'validate')
        graph.add_conditional_edges('validate', self._next, {'repair': 'repair', 'done': 'prepare_review'})
        graph.add_edge('repair', 'validate')
        graph.add_edge('prepare_review', END)
        self.graph = graph.compile(checkpointer=checkpointer)

    def _parse(self, state):
        self.observe('document_parse')
        return {'parsed': self.parse(self.original)}  # The file itself stays in private storage, never in state.

    def _extract(self, state):
        self.observe('model_request')
        candidate, metadata = self.call_model(state['parsed']['blocks'], None, None)
        return {'candidate': candidate, 'metadata': metadata, 'repair_attempts': 0}

    def _validate(self, state):
        self.observe('extraction_validation')
        try:
            blocks = state['parsed']['blocks']
            pending = evidence_requiring_semantic_check(state['candidate'], blocks)
            support = self.verify_evidence(blocks, pending) if pending and self.verify_evidence else frozenset()
            # Approval is scoped to the exact source/summary pair, never a broad
            # permission to accept later model output or a different source.
            candidate = state['candidate']
            items = validate_extraction(candidate, blocks, self.cv_id, support)
            other = validate_other_information(Extraction.model_validate(candidate).other_information, blocks, support)
        except (ExtractionFailure, ModelAdmissionError):
            raise
        except (ValidationError, ValueError) as error:
            if state['repair_attempts'] >= 1: raise
            return {'feedback': feedback_for(error), 'needs_repair': True}
        return {'items': items, 'other_information': other, 'needs_repair': False}

    def _prepare_review(self, state):
        return {'items': prepare_review_items(state['items'])}

    def _next(self, state):
        return 'repair' if state.get('needs_repair') else 'done'

    def _repair(self, state):
        self.observe('model_repair')
        self.repair_attempted = True
        candidate, metadata = self.call_model(state['parsed']['blocks'], state['candidate'], state['feedback'])
        return {'candidate': candidate, 'metadata': metadata, 'repair_attempts': 1,
                'needs_repair': False, 'feedback': []}

    def run(self, original):
        self.original = original
        config = {'configurable': {'thread_id': self.thread_id}, 'recursion_limit': 8, 'callbacks': []}
        # Disable inherited callbacks as well as LangSmith tracing. Never stream
        # graph state or put private content into metadata.
        with tracing_context(enabled=False):
            saved = self.graph.get_state(config)
            if self.rewind_rejected and saved.next == ('validate',) and saved.values.get('repair_attempts'):
                # Output rejected after repair would only fail again. Keep the parsed
                # document and ask the model again, rather than repeating finished work.
                self.graph.update_state(config, {'candidate': None, 'feedback': [], 'needs_repair': False, 'repair_attempts': 0}, as_node='parse')
                saved = self.graph.get_state(config)
            self.repair_attempted = bool(saved.values.get('repair_attempts'))
            if saved.next:  # Interrupted: continue from the first unfinished step.
                result = self.graph.invoke(None, config=config, durability='sync')
            elif 'items' in saved.values:  # Finished but not yet published: no step needs repeating.
                result = dict(saved.values)
            else:
                result = self.graph.invoke({'repair_attempts': 0}, config=config, durability='sync')
        result['metadata'] = {**result['metadata'], 'workflow_version': WORKFLOW_VERSION,
                              'repair_attempts': result['repair_attempts']}
        return result

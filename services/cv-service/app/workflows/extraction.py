"""One extraction plus at most one repair, with no durable private graph state."""
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from pydantic import ValidationError
from app.domain.capabilities import validate_extraction, validate_other_information, normalize_extraction_evidence, evidence_requiring_semantic_check
from app.schemas.cv import Extraction
from app.domain.extraction_errors import ExtractionFailure
from app.domain.model_usage import ModelAdmissionError
from app.domain.extraction_feedback import feedback_for
from app.domain.review_context import prepare_review_items

WORKFLOW_VERSION = 'cv-extraction-4'


class ExtractionState(TypedDict, total=False):
    original: bytes
    parsed: dict
    candidate: Any
    metadata: dict
    items: list
    other_information: list
    feedback: list
    validation_error: Exception | None
    repair_attempts: int


class ExtractionHarness:
    def __init__(self, cv_id, parse, call_model, observe, verify_evidence=None):
        self.cv_id, self.parse, self.call_model, self.observe = cv_id, parse, call_model, observe
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
        self.graph = graph.compile()  # No checkpointer or store: CV text stays in memory.

    def _parse(self, state):
        self.observe('document_parse')
        return {'parsed': self.parse(state['original'])}

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
            candidate = normalize_extraction_evidence(state['candidate'], blocks, support)
            # Expand approvals only to the lossless parts of an approved summary.
            expanded = set(support)
            for ref in pending:
                if (ref['block_id'], ref['excerpt']) in support:
                    parts = normalize_extraction_evidence({'other_information': [ref]}, blocks, support)['other_information']
                    expanded.update((part['block_id'], part['excerpt']) for part in parts)
            items = validate_extraction(candidate, blocks, self.cv_id, expanded)
            other = validate_other_information(Extraction.model_validate(candidate).other_information, blocks, expanded)
        except (ExtractionFailure, ModelAdmissionError):
            raise
        except (ValidationError, ValueError) as error:
            if state['repair_attempts'] >= 1: raise
            return {'feedback': feedback_for(error), 'validation_error': error}
        return {'items': items, 'other_information': other, 'validation_error': None}

    def _prepare_review(self, state):
        return {'items': prepare_review_items(state['items'])}

    def _next(self, state):
        return 'repair' if state.get('validation_error') is not None else 'done'

    def _repair(self, state):
        self.observe('model_repair')
        self.repair_attempted = True
        candidate, metadata = self.call_model(state['parsed']['blocks'], state['candidate'], state['feedback'])
        return {'candidate': candidate, 'metadata': metadata, 'repair_attempts': 1,
                'validation_error': None, 'feedback': []}

    def run(self, original):
        # Disable inherited callbacks as well as LangSmith tracing. Never stream
        # graph state, attach a checkpointer, or put private content into metadata.
        with tracing_context(enabled=False):
            result = self.graph.invoke({'original': original}, config={'recursion_limit': 8, 'callbacks': []})
        result['metadata'] = {**result['metadata'], 'workflow_version': WORKFLOW_VERSION,
                              'repair_attempts': result['repair_attempts']}
        return result

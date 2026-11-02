"""One extraction plus at most one repair, with no durable private graph state."""
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from pydantic import ValidationError
from app.domain.capabilities import validate_extraction
from app.domain.extraction_feedback import feedback_for

WORKFLOW_VERSION = 'cv-extraction-1'


class ExtractionState(TypedDict, total=False):
    original: bytes
    parsed: dict
    candidate: Any
    metadata: dict
    items: list
    feedback: list
    validation_error: Exception | None
    repair_attempts: int


class ExtractionHarness:
    def __init__(self, cv_id, parse, call_model, observe):
        self.cv_id, self.parse, self.call_model, self.observe = cv_id, parse, call_model, observe
        self.repair_attempted = False
        graph = StateGraph(ExtractionState)
        graph.add_node('parse', self._parse)
        graph.add_node('extract', self._extract)
        graph.add_node('validate', self._validate)
        graph.add_node('repair', self._repair)
        graph.add_edge(START, 'parse')
        graph.add_edge('parse', 'extract')
        graph.add_edge('extract', 'validate')
        graph.add_conditional_edges('validate', self._next, {'repair': 'repair', 'done': END})
        graph.add_edge('repair', 'validate')
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
            items = validate_extraction(state['candidate'], state['parsed']['blocks'], self.cv_id)
        except (ValidationError, ValueError) as error:
            if state['repair_attempts'] >= 1: raise
            return {'feedback': feedback_for(error), 'validation_error': error}
        return {'items': items, 'validation_error': None}

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

"""Allowlisted extraction diagnostics; never carry provider prose or CV content."""
from typing import Literal

FailureStage = Literal['source_read', 'document_parse', 'model_request', 'model_repair',
                       'response_decode', 'content_decode', 'extraction_validation', 'publication']
FailureCategory = Literal['source_unavailable', 'invalid_document', 'not_configured',
    'model_admission', 'provider_http_error', 'timeout', 'connection_error', 'transport_error',
    'response_too_large', 'invalid_json', 'invalid_response', 'incomplete_output',
    'schema_validation', 'evidence_validation', 'unexpected_error', 'history_capacity', 'source_changed']
ProviderReason = Literal['schema_too_complex', 'schema_rejected', 'structured_output_unsupported',
    'unsupported_parameter', 'invalid_request', 'authentication_failed', 'permission_denied',
    'not_found', 'rate_limit_or_quota', 'provider_unavailable', 'http_error']
ProviderParameter = Literal['response_format', 'schema', 'model', 'reasoning_effort',
                            'temperature', 'max_tokens', 'messages']


class ExtractionFailure(ValueError):
    def __init__(self, message: str, stage: FailureStage, category: FailureCategory,
                 provider_status_code: int | None = None, *,
                 provider_reason: ProviderReason | None = None,
                 provider_parameter: ProviderParameter | None = None):
        super().__init__(message)
        self.stage, self.category = stage, category
        self.provider_status_code = provider_status_code
        self.provider_reason, self.provider_parameter = provider_reason, provider_parameter


class StaleExtraction(Exception):
    """The worker no longer owns the lease; do not call a model or publish."""


class EvidenceValidationError(ValueError):
    def __init__(self, message, rule, item_index=None):
        super().__init__(message)
        self.rule, self.item_index = rule, item_index

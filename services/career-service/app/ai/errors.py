"""Model-stage failure carrying only fixed codes and allow-listed field names."""
import math
import re
from app.ai.outputs import VALIDATION_FIELDS
from app.ai.rejections import safe_diagnostic

MAX_FIELD_PATH = 160
MAX_REPORTED = 12


class AIError(Exception):
    def __init__(self, code: str, retryable: bool = False, *, reason=None, fields=(), limit_scope=None, retry_after=None, input_count=None, violations=(), provider=None, provider_error=None):
        allowed={'schema_validation','source_quote','duplicate_skill','unexpected_origin','provider_json','json_syntax','response_envelope','provenance'}
        self.reason = reason if reason in allowed else None
        safe={'role','field','company','skills','name','category','priority','required_proficiency','required_experience_months','context','evidence','origin','employment_type','location','seniority_level','job_url','summary','responsibilities','non_skill_requirements'}
        safe |= VALIDATION_FIELDS
        self.violations = tuple({'field': v['field'], 'issue': v['issue']} for v in violations
            if isinstance(v,dict) and isinstance(v.get('field'),str) and len(v['field'])<=MAX_FIELD_PATH
            and all(part in safe or part.isdigit() or part=='$' for part in v['field'].split('.'))
            and isinstance(v.get('issue'),str) and re.fullmatch(r'[a-z_]{1,60}',v['issue']))[:MAX_REPORTED]
        self.fields = tuple(str(field) for field in fields if isinstance(field, str) and field in safe)[:MAX_REPORTED]
        self.provider=provider if provider=='compatible' else None
        self.provider_error=safe_diagnostic(provider_error)
        self.limit_scope = limit_scope if limit_scope in ('provider','user') else None
        self.input_count=input_count if type(input_count) is int and input_count>=0 else None
        self.retry_after = math.ceil(retry_after) if isinstance(retry_after, (int, float)) and math.isfinite(retry_after) and retry_after >= 0 else None
        self.code, self.retryable = code, retryable
        super().__init__(code)

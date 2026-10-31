"""Classify provider rejections without exposing provider prose, prompts or keys."""
import json
import re

CODES=frozenset({
    'model_not_found','model_decommissioned','json_validate_failed','context_length_exceeded',
    'unsupported_parameter','invalid_request_error','INVALID_ARGUMENT','NOT_FOUND',
    'PERMISSION_DENIED','UNAUTHENTICATED','FAILED_PRECONDITION','API_KEY_INVALID',
    'API_KEY_SERVICE_BLOCKED','API_KEY_HTTP_REFERRER_BLOCKED','API_KEY_IP_ADDRESS_BLOCKED',
    'API_KEY_ANDROID_APP_BLOCKED','API_KEY_IOS_APP_BLOCKED','SERVICE_DISABLED','BILLING_DISABLED',
})
FIELDS=frozenset({'model','messages','response_format','json_schema','schema','strict',
    'reasoning_effort','thinking','max_tokens','max_completion_tokens','temperature','top_p','tools','tool_choice'})
AUTH=frozenset({'API_KEY_INVALID','API_KEY_SERVICE_BLOCKED','API_KEY_HTTP_REFERRER_BLOCKED',
    'API_KEY_IP_ADDRESS_BLOCKED','API_KEY_ANDROID_APP_BLOCKED','API_KEY_IOS_APP_BLOCKED',
    'UNAUTHENTICATED','PERMISSION_DENIED'})


def safe_diagnostic(value):
    if not isinstance(value,dict) or type(value.get('http_status')) is not int or not 100<=value['http_status']<=599:return None
    result={'http_status':value['http_status'],'provider':value.get('provider') if value.get('provider') in ('gemini','deepseek','local','compatible') else 'other'}
    code=value.get('code')
    if isinstance(code,str) and code in CODES:result['code']=code
    fields=value.get('fields')
    result['fields']=sorted({v for v in fields[:20] if isinstance(v,str) and v in FIELDS})[:8] if isinstance(fields,(list,tuple)) else []
    return result


def classify(raw,status,provider):
    error={}
    try:
        payload=json.loads(raw)
        # Google's compatibility endpoint may wrap its native error in a list.
        # Only unwrap a single error envelope, never arbitrary nested content.
        if isinstance(payload,list) and len(payload)==1:payload=payload[0]
        if isinstance(payload,dict) and isinstance(payload.get('error'),dict):error=payload['error']
    except (ValueError,UnicodeError,TypeError,RecursionError):pass
    code=error.get('code')
    code=code if isinstance(code,str) and code in CODES else None
    native_status=error.get('status')
    if isinstance(native_status,str) and native_status in CODES:code=native_status
    fields=set()
    def field_path(value):
        if not isinstance(value,str) or len(value)>512:return
        for token in re.findall(r'[A-Za-z_]+',value):
            if token in FIELDS:fields.add(token)
            if token in ('response_schema','responseSchema'):fields.add('response_format')
            if token in ('thinking_config','thinkingConfig','thinking_level','thinkingLevel'):fields.add('reasoning_effort')
    field_path(error.get('param'))
    details=error.get('details')
    for item in details[:20] if isinstance(details,list) else []:
        if not isinstance(item,dict):continue
        reason=item.get('reason')
        if isinstance(reason,str) and reason in CODES:code=reason
        violations=item.get('fieldViolations',item.get('field_violations',[]))
        for violation in violations[:20] if isinstance(violations,list) else []:
            if isinstance(violation,dict):field_path(violation.get('field'))
    # Some compatibility errors identify rejected fields only in prose. Extract
    # names from fixed error forms; never return or log the rest of that prose.
    message=error.get('message')
    if isinstance(message,str):
        message=message[:8192]
        patterns=(r'Unknown name [\"\']([A-Za-z_]+)[\"\']',
            r'(?:Unsupported|Unrecognized) (?:parameter|field)(?: name)?[: ]+[\"\']?([A-Za-z_]+)',
            r'Invalid value at [\"\']([A-Za-z_.\[\]0-9]+)[\"\']')
        for pattern in patterns:
            for match in re.finditer(pattern,message,re.I):field_path(match.group(1))
    diagnostic=safe_diagnostic({'http_status':status,'provider':provider,'code':code,'fields':list(fields)})
    result='provider_configuration'
    if code in ('model_not_found','model_decommissioned'):result='model_unavailable'
    elif code=='json_validate_failed':result='invalid_output'
    elif code=='context_length_exceeded':result='context_limit'
    elif status in (401,403):result='provider_auth'
    elif provider=='local' and status==404:result='model_unavailable'
    if provider=='gemini':
        if code in AUTH:result='provider_auth'
        elif code in ('SERVICE_DISABLED','BILLING_DISABLED','FAILED_PRECONDITION'):result='provider_access'
        elif code=='NOT_FOUND':result='model_unavailable'
        elif fields & {'response_format','json_schema','schema','strict'}:result='provider_schema'
        elif 'model' in fields:result='model_unavailable'
        elif fields:result='provider_parameter'
    return result,diagnostic

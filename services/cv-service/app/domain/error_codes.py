"""Machine-readable codes for saved action and interpretation failures."""
from typing import Literal

ErrorCode = Literal['unsupported_interpretation', 'no_valid_next_step', 'interrupted']

_LEGACY_PREFIXES = {
    'Some interpreted skill details are not supported': 'unsupported_interpretation',
    'The interview could not choose a valid next step.': 'no_valid_next_step',
    'Processing was interrupted.': 'interrupted',
}


class CodedError(ValueError):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code


def legacy_error_code(message):
    """The code for a failure saved before codes were stored; new failures carry their own code."""
    if not isinstance(message, str): return None
    return next((code for prefix, code in _LEGACY_PREFIXES.items() if message.startswith(prefix)), None)


def error_code_of(action):
    return action.get('error_code') or legacy_error_code(action.get('error'))

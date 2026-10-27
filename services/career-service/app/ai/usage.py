"""Approximate request-size diagnostics; not a rate limiter or billing ledger."""
import json
import tiktoken

def input_tokens(payload):
    content={key:payload[key] for key in ('messages','response_format','tools') if key in payload}
    text=json.dumps(content,ensure_ascii=False,separators=(',',':'))
    return len(tiktoken.get_encoding('o200k_harmony').encode(text,disallowed_special=()))

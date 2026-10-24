import json
import subprocess
import sys
from fastapi import HTTPException


def run_preview(kind, data, extension=''):
    try:
        result = subprocess.run([sys.executable, '-m', 'app.workers.preview', kind, extension],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
        payload = json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, 'Processing took too long. Retry, paste the description or choose another document.') from exc
    except (subprocess.SubprocessError, ValueError) as exc:
        raise HTTPException(422, 'This source could not be processed within the limits. Paste the description or choose another document.') from exc
    if payload.get('error'):
        raise HTTPException(422, payload['error'])
    return payload['preview']

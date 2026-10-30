import json
import os
import signal
import tempfile
import time
from pathlib import Path
import subprocess
import sys
from fastapi import HTTPException
from app.schemas.preview import URL_WORKER_TIMEOUT,DOCUMENT_WORKER_TIMEOUT,URL_IMPORT_TIMEOUT


def run_preview(kind, data, extension=''):
    deadline=time.monotonic()+URL_IMPORT_TIMEOUT
    try:
        result = subprocess.run([sys.executable, '-m', 'app.workers.preview', kind, extension],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=URL_WORKER_TIMEOUT if kind=='url' else DOCUMENT_WORKER_TIMEOUT, check=True)
        payload = json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, 'Processing took too long. Retry, paste the description or choose another document.') from exc
    except (subprocess.SubprocessError, ValueError) as exc:
        raise HTTPException(422, 'This source could not be processed within the limits. Paste the description or choose another document.') from exc
    if kind=='url' and payload.get('render_url'):
        payload=run_browser_preview(payload['render_url'],deadline)
    if payload.get('error'):
        raise HTTPException(422, payload['error'])
    return payload['preview']


def run_browser_preview(url,deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise HTTPException(422,'The import timed out. Paste the description or upload a document.')
    # Parent owns the temporary profile directory and always kills the whole process
    # group before deleting it, including browser descendants after a hard timeout.
    with tempfile.TemporaryDirectory(prefix='elo-browser-') as directory:
        process=subprocess.Popen([sys.executable,'-m','app.workers.browser_preview',str(remaining)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            start_new_session=True,env={'PATH':os.defpath,'TMPDIR':directory,'HOME':directory,
                'PLAYWRIGHT_BROWSERS_PATH':os.environ.get('PLAYWRIGHT_BROWSERS_PATH','/opt/playwright')})
        try:
            output,_=process.communicate(input=url.encode('utf-8'),timeout=remaining)
            if process.returncode:raise ValueError
            payload=json.loads(output)
            if not isinstance(payload,dict):raise ValueError
            return payload
        except (subprocess.SubprocessError,ValueError):
            raise HTTPException(422,'The JavaScript preview could not be prepared within the import limits. Paste the description or upload a document.') from None
        finally:
            # Chromium creates its own process group. Include descendants before
            # terminating the supervisor group so detached browsers cannot survive.
            descendants=child_processes(process.pid)
            for child in reversed(descendants):
                try:os.kill(child,signal.SIGKILL)
                except ProcessLookupError:pass
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()


def child_processes(pid):
    """Linux process-tree IDs only; never inspect environments or command lines."""
    result=[]
    pending=[pid]
    seen={pid}
    while pending:
        parent=pending.pop()
        for children in Path(f'/proc/{parent}/task').glob('*/children'):
            try:ids=[int(value) for value in children.read_text().split()]
            except (OSError,ValueError):continue
            for child in ids:
                if child not in seen:
                    seen.add(child);result.append(child);pending.append(child)
    return result

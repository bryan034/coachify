import json
import subprocess
import sys


def isolated_parse(data, extension, max_file_bytes):
    try:
        result = subprocess.run([sys.executable, '-m', 'app.workers.parse', extension, str(max_file_bytes)],
                                input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=20, check=True)
        payload = json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Processing took too long. Export a simpler PDF or DOCX and retry.') from exc
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError('This CV could not be processed within the limits. Choose another file.') from exc
    if 'error' in payload: raise ValueError(payload['error'])
    return payload['result']

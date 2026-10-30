"""Isolated renderer entry point; receives one public URL over stdin, never model keys."""
import json
import logging
import sys
import time


def main():
    logging.disable(logging.CRITICAL)
    if sys.platform=='linux':
        import resource
        # Chromium reserves a very large virtual address space; the static parser's
        # RLIMIT_AS cannot apply here. Container memory/PID/tmp limits remain in force.
        resource.setrlimit(resource.RLIMIT_CPU,(12,12))
        resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))
    try:
        import fcntl
        # One renderer per service container, within the existing two-import admission.
        with open('/tmp/elo-browser-preview.lock','a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Another JavaScript preview is loading. Try again shortly, paste the description or upload a document.') from None
            from app.clients.job_browser import render_url
            preview=render_url(sys.stdin.buffer.read(8193).decode('utf-8'),time.monotonic()+float(sys.argv[1]))
            payload={'preview':preview}
    except ValueError as exc:payload={'error':str(exc)}
    except Exception:payload={'error':'The browser preview is unavailable. Paste the description or upload a document.'}
    sys.stdout.write(json.dumps(payload,ensure_ascii=True))


if __name__=='__main__':main()

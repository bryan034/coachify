"""Isolated renderer entry point; receives one public URL over stdin, never model keys."""
import json
import logging
import sys
import time
import resource
import fcntl
from app.clients.job_browser import render_url


def main():
    logging.disable(logging.CRITICAL)
    if sys.platform=='linux':
        resource.setrlimit(resource.RLIMIT_CPU,(12,12))
        resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))
    try:
        # One renderer per service container.
        with open('/tmp/elo-browser-preview.lock','a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Another JavaScript preview is loading. Try again shortly, paste the description or upload a document.') from None
            preview=render_url(sys.stdin.buffer.read(8193).decode('utf-8'),time.monotonic()+float(sys.argv[1]))
            payload={'preview':preview}
    except ValueError as exc:payload={'error':str(exc)}
    sys.stdout.write(json.dumps(payload,ensure_ascii=True))


if __name__=='__main__':main()

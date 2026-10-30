"""Short-lived preview process: no persistence, stdout is a private response pipe."""
import json
import logging
import sys


def main():
    logging.disable(logging.CRITICAL)
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        if sys.argv[1] == 'url':
            from app.clients.job_url import import_url,RenderRequired
            try:
                result = import_url(sys.stdin.buffer.read(8193).decode('utf-8'))
            except RenderRequired as exc:
                sys.stdout.write(json.dumps({'render_url':exc.url}))
                return
        else:
            from app.domain.documents import document_text
            from app.schemas.preview import MAX_FILE
            result = document_text(sys.stdin.buffer.read(MAX_FILE + 1), sys.argv[2])
        payload = {'preview': result}
    except ValueError as exc:
        payload = {'error': str(exc)}
    except Exception:
        payload = {'error': 'This source could not be read. Try again, paste the description or choose another document.'}
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))


if __name__ == '__main__':
    main()

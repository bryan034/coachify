"""Short-lived isolated parser. stdout is a private response pipe, never a log."""
import json
import logging
import sys


def main():
    logging.disable(logging.CRITICAL)
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    from app.parsing.documents import parse_document
    maximum = int(sys.argv[2])
    try:
        payload = {'result': parse_document(sys.stdin.buffer.read(maximum + 1), sys.argv[1], maximum)}
    except ValueError as exc:
        payload = {'error': str(exc)}
    except Exception:
        payload = {'error': 'This CV could not be read within processing limits. Export a simpler file.'}
    sys.stdout.write(json.dumps(payload))


if __name__ == '__main__': main()

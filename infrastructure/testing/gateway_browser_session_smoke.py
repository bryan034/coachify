"""Verify browser cookie authentication against isolated NGINX and synthetic upstreams."""
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MARKER = 'm' * 64
CREDENTIAL = 'a' * 64
UPSTREAM = '''from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        authenticated = self.headers.get('Authorization') == 'Bearer ' + 'a' * 64
        self.send_response(200 if authenticated else 401)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{}')
    do_POST = do_GET
    def log_message(self, *args):
        pass
HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
'''


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def verify(base):
    def request(path, headers, method='GET'):
        try:
            with urlopen(Request(base + path, headers=headers, method=method), timeout=3) as response:
                return response.status
        except HTTPError as error:
            return error.code

    for attempt in range(30):
        try:
            request('/api/v1/profile', {})
            break
        except (OSError, TimeoutError):
            if attempt == 29:
                raise
            time.sleep(0.2)
    cookie = {'Cookie': f'elo_session={MARKER}.{CREDENTIAL}'}
    browser = {'X-Elo-Browser': '1', 'X-Elo-Session': MARKER}
    for prefix in ['profile', 'career/', 'cv', 'assessments', 'roadmaps', 'dashboard', 'jobs']:
        path = '/api/v1/' + prefix
        assert request(path, cookie) == 401, f'{prefix}: cookie alone authenticated'
        assert request(path, browser) == 401, f'{prefix}: marker alone authenticated'
        assert request(path, {**browser, **cookie}) == 200, f'{prefix}: matched session failed'
        assert request(path, {**browser, **cookie, 'X-Elo-Session': 'n' * 64}) == 401, f'{prefix}: stale marker authenticated'
        assert request(path, {'Authorization': 'Bearer ' + CREDENTIAL}) == 200, f'{prefix}: explicit bearer failed'
        assert request(path, {**browser, 'Authorization': 'Bearer ' + CREDENTIAL}) == 401, f'{prefix}: browser bearer override authenticated'
        assert request(path, {**browser, **cookie}, 'POST') == 200, f'{prefix}: matched mutation failed'
    assert request('/internal/v1/private', {**browser, **cookie}) == 404


def main():
    name = 'elo-security-' + uuid4().hex[:10]
    network = name + '-network'
    containers = []
    try:
        docker('network', 'create', network)
        with tempfile.TemporaryDirectory(prefix='elo-gateway-security-') as directory:
            server = Path(directory) / 'server.py'
            server.write_text(UPSTREAM)
            aliases = [value for service in ['profile', 'career', 'cv', 'assessment', 'roadmap', 'dashboard', 'jobs']
                       for value in ['--network-alias', service + '-service']]
            upstream, gateway = name + '-upstream', name + '-gateway'
            docker('run', '-d', '--rm', '--name', upstream, '--network', network, *aliases,
                   '--network-alias', 'frontend', '-v', f'{server}:/server.py:ro', 'python:3.12-slim', 'python', '/server.py')
            containers.append(upstream)
            docker('run', '-d', '--rm', '--name', gateway, '--network', network, '-p', '127.0.0.1::80',
                   '-v', f'{ROOT / "infrastructure/gateway/nginx.conf"}:/etc/nginx/nginx.conf:ro', 'nginx:alpine')
            containers.append(gateway)
            port = docker('port', gateway, '80').split(':')[-1]
            verify('http://127.0.0.1:' + port)
            print('Passed 49 browser authentication checks and the private-route check.')
    finally:
        for container in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True, check=False)
        subprocess.run(['docker', 'network', 'rm', network], capture_output=True, check=False)


if __name__ == '__main__':
    main()

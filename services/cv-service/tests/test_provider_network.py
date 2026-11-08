"""Provider calls must traverse configured HTTPS proxies with verified TLS."""
import json
import ssl
import subprocess
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.clients.conversation import ConversationRouter
from app.clients.extractor import Extractor
from app.clients.interpretation import Interpreter
from app.domain.extraction_errors import ExtractionFailure
from fastapi.testclient import TestClient
from pydantic import BaseModel
from elo_shared.runtime import application, MemoryStore


OUTPUTS = {
    Extractor: {'items': []},
    ConversationRouter: {'reply': 'Please describe your contribution.', 'actions': []},
    Interpreter: {'item_id': 'item-1', 'answer_revision': 1, 'resolution': 'unanswerable',
                  'claims': [], 'resolved_uncertainties': [], 'remaining_uncertainties': ['proficiency']},
}


def invoke(provider_class):
    provider = provider_class()
    if provider_class is Extractor:
        return provider.extract([])[0]
    if provider_class is ConversationRouter:
        return provider.route({'message': 'What should I explain?'})[0].model_dump()
    return provider.interpret({'id': 'item-1'},
        {'id': 'question-1', 'uncertainty': 'proficiency', 'question': 'What did you do?'},
        'I do not know.', 1)[0]


@contextmanager
def serve(handler):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.fixture(scope='module')
def provider_certificate(tmp_path_factory):
    directory = tmp_path_factory.mktemp('synthetic-provider-tls')
    certificate, key = directory / 'certificate.pem', directory / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=provider.example.invalid', '-addext', 'subjectAltName=DNS:provider.example.invalid',
        '-keyout', str(key), '-out', str(certificate)], check=True, capture_output=True)
    return certificate, key


def handler_for(output, requests, tls=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def do_CONNECT(self):
            requests.append(('CONNECT', self.path, None))
            self.send_response(200, 'Connection established')
            self.end_headers()
            self.wfile.flush()
            try:
                self.connection = tls.wrap_socket(self.connection, server_side=True)
            except ssl.SSLError:
                self.close_connection = True
                return
            self.rfile = self.connection.makefile('rb')
            self.wfile = self.connection.makefile('wb')
            self.handle_one_request()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            requests.append(('POST', self.path, dict(self.headers)))
            assert body['model'] == 'synthetic-model'
            data = json.dumps({'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps(output)}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

    return Handler


def configure_proxy(monkeypatch, port):
    for name in ('HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        monkeypatch.setenv(name, f'http://127.0.0.1:{port}')
    for name in ('NO_PROXY', 'no_proxy'):
        monkeypatch.setenv(name, '')
    monkeypatch.setenv('CV_LLM_API_KEY', 'synthetic-provider-key')
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-model')


@pytest.mark.parametrize('provider_class', OUTPUTS)
def test_cloud_calls_use_https_proxy_and_its_trusted_ca(monkeypatch, provider_certificate, provider_class):
    certificate, key = provider_certificate
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    requests = []
    with serve(handler_for(OUTPUTS[provider_class], requests, tls)) as port:
        configure_proxy(monkeypatch, port)
        monkeypatch.setenv('SSL_CERT_FILE', str(certificate))
        monkeypatch.setenv('CV_LLM_BASE_URL', 'https://provider.example.invalid/v1')
        assert invoke(provider_class) == OUTPUTS[provider_class]
    assert [(method, path) for method, path, _ in requests] == [
        ('CONNECT', 'provider.example.invalid:443'), ('POST', '/v1/chat/completions')]
    assert requests[-1][2]['Authorization'] == 'Bearer synthetic-provider-key'


@pytest.mark.parametrize('provider_class', OUTPUTS)
def test_local_calls_bypass_proxy_and_do_not_send_cloud_keys(monkeypatch, provider_class):
    requests, proxy_requests = [], []
    with serve(handler_for({}, proxy_requests)) as proxy_port:
        with serve(handler_for(OUTPUTS[provider_class], requests)) as local_port:
            configure_proxy(monkeypatch, proxy_port)
            monkeypatch.setenv('APP_ENV', 'development')
            monkeypatch.setenv('CV_LLM_ALLOW_HTTP', 'true')
            monkeypatch.setenv('CV_LLM_BASE_URL', f'http://127.0.0.1:{local_port}/v1')
            assert invoke(provider_class) == OUTPUTS[provider_class]
    assert proxy_requests == []
    assert len(requests) == 1 and requests[0][:2] == ('POST', '/v1/chat/completions')
    assert 'Authorization' not in requests[0][2]


def test_cloud_calls_still_reject_an_untrusted_proxy_certificate(monkeypatch, provider_certificate):
    certificate, key = provider_certificate
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    requests = []
    with serve(handler_for(OUTPUTS[Extractor], requests, tls)) as port:
        configure_proxy(monkeypatch, port)
        monkeypatch.delenv('SSL_CERT_FILE', raising=False)
        monkeypatch.delenv('SSL_CERT_DIR', raising=False)
        monkeypatch.setenv('CV_LLM_BASE_URL', 'https://provider.example.invalid/v1')
        with pytest.raises(ExtractionFailure) as caught:
            Extractor().extract([])
    assert caught.value.category == 'connection_error'
    assert [(method, path) for method, path, _ in requests] == [('CONNECT', 'provider.example.invalid:443')]


@pytest.mark.parametrize('prefix', ['ASSESSMENT', 'ROADMAP'])
@pytest.mark.parametrize('local', [False, True])
def test_planning_service_uses_proxy_for_cloud_and_direct_client_for_local(monkeypatch, provider_certificate, prefix, local):
    class Answer(BaseModel):
        reply: str
    certificate, key = provider_certificate
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    requests = []
    with serve(handler_for({'reply': 'Synthetic answer'}, requests, None if local else tls)) as port:
        configure_proxy(monkeypatch, port)
        monkeypatch.setenv('SSL_CERT_FILE', str(certificate))
        monkeypatch.setenv('APP_ENV', 'development')
        monkeypatch.setenv(prefix + '_LLM_ALLOW_HTTP', 'true' if local else 'false')
        monkeypatch.setenv(prefix + '_LLM_BASE_URL', f'http://127.0.0.1:{port}/v1' if local else 'https://provider.example.invalid/v1')
        monkeypatch.setenv(prefix + '_LLM_MODEL', 'synthetic-model')
        monkeypatch.setenv(prefix + '_LLM_API_KEY', 'synthetic-provider-key')
        app = application('Synthetic planning service', prefix, store=MemoryStore(), upstream=object())
        with TestClient(app) as client:
            result = client.portal.call(app.state.model.generate, Answer, 'Answer in JSON.', {})
        assert result.reply == 'Synthetic answer'
    assert [method for method, _, _ in requests] == (['POST'] if local else ['CONNECT', 'POST'])
    assert ('Authorization' in requests[-1][2]) is not local

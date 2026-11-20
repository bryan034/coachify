"""Bounded retries and precise public URL failures, using synthetic requests only."""
import json
import ssl
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.clients import job_url, public_url
from app.domain.preview import run_preview
from app.schemas.preview import URL_NETWORK_TIMEOUT,URL_IMPORT_TIMEOUT,URL_WORKER_TIMEOUT,DOCUMENT_WORKER_TIMEOUT


def public_dns(host,port,**kwargs):return [(2,1,6,'',('93.184.216.34',port))]


@pytest.mark.parametrize('failure,expected',[
    (TimeoutError('private diagnostic'),'timed out while reading the webpage'),
    (ssl.SSLCertVerificationError('private diagnostic'),'TLS certificate could not be verified'),
    (ssl.SSLError('private diagnostic'),'secure TLS connection'),
    (ConnectionResetError('private diagnostic'),'could not be reached'),
])
def test_network_errors_are_distinct_and_sanitized(failure,expected):
    with patch('socket.getaddrinfo',public_dns),patch('socket.create_connection'),patch('ssl.create_default_context'),patch('http.client.HTTPConnection') as connection:
        connection.return_value.getresponse.side_effect=failure
        with pytest.raises(ValueError,match=expected) as raised:
            job_url.request_page('https://example.test/job',job_url.time.monotonic()+60)
        assert 'private diagnostic' not in str(raised.value)
        connection.return_value.close.assert_called_once()
        if isinstance(failure,TimeoutError):assert isinstance(raised.value,job_url.PageTimeout)


def test_five_second_network_cap_and_closed_response_body():
    class Response:
        status=200
        closed=False
        def getheaders(self):return [('Content-Type','text/html')]
        def read1(self,n):self.closed=True;return b'<main>Analyst</main>'
        def isclosed(self):return self.closed
        def close(self):self.closed=True
    response=Response()
    with patch('socket.getaddrinfo',public_dns),patch('socket.create_connection') as connect,patch('ssl.create_default_context') as tls,patch('http.client.HTTPConnection') as connection:
        connection.return_value.getresponse.return_value=response
        _,_,data=job_url.request_page('https://example.test/job',job_url.time.monotonic()+60)
        assert data==b'<main>Analyst</main>' and response.closed
        assert connect.call_args.kwargs['timeout']==URL_NETWORK_TIMEOUT==5
        assert all(call.args[0]<=5 for call in tls.return_value.wrap_socket.return_value.settimeout.call_args_list)


def test_page_timeout_retries_once_then_reads_job():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        if len(seen)==1:raise job_url.PageTimeout('timed out')
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['text']=='Analyst requires SQL.'
    assert seen==['https://example.test/job']*2


def test_user_requested_pages_never_consult_robots_txt():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        if url.endswith('/robots.txt'):pytest.fail('robots.txt must not be requested')
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['text']=='Analyst requires SQL.' and seen==['https://example.test/job']


def test_repeated_page_timeouts_fail_as_a_timeout():
    seen=[]
    def fetch(url,deadline):seen.append(url);raise job_url.PageTimeout('timed out')
    with patch('socket.getaddrinfo',public_dns),pytest.raises(job_url.PageTimeout):
        job_url.import_url('https://example.test/job',fetch)
    assert seen==['https://example.test/job']*2


@pytest.mark.parametrize('status',[401,403,429])
def test_server_refusals_block_with_the_paste_fallback(status):
    seen=[]
    def fetch(url,deadline):seen.append(url);return status,{},b''
    with patch('socket.getaddrinfo',public_dns),pytest.raises(job_url.AccessBlocked,match='Copy and paste the job description'):
        job_url.import_url('https://example.test/job',fetch)
    assert seen==['https://example.test/job']


@pytest.mark.parametrize('url,site',[('https://www.linkedin.com/jobs/view/1','LinkedIn'),('https://sg.indeed.com/viewjob?jk=1','Indeed'),
    ('https://www.glassdoor.sg/job-listing/x','Glassdoor'),('https://www.jobstreet.com.sg/job/1','JobStreet'),
    ('https://sg.jobstreet.com/job/1','JobStreet'),('https://LINKEDIN.COM/jobs/1','LinkedIn')])
def test_known_job_aggregators_are_blocked_before_any_network_request(url,site):
    with patch('socket.getaddrinfo') as dns,pytest.raises(job_url.AccessBlocked) as blocked:
        job_url.import_url(url,lambda *args:pytest.fail('no request expected'))
    dns.assert_not_called()
    message=str(blocked.value)
    assert message.startswith(public_url.BLOCKED_PREFIX)
    assert f'{site} does not allow its job listings to be read automatically' in message
    assert f'Open the job on {site}, copy the description and paste it here.' in message


def test_lookalike_hosts_are_not_treated_as_aggregators():
    assert not public_url.blocked_host('notlinkedin.com') and not public_url.blocked_host('indeed.com.example.test')


def test_access_restrictions_and_certificate_failures_are_not_retried():
    for failure in ('blocked','certificate'):
        seen=[]
        def fetch(url,deadline):
            seen.append(url)
            if failure=='certificate':raise ValueError('TLS certificate could not be verified')
            return 403,{},b''
        with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError):
            job_url.import_url('https://example.test/job',fetch)
        assert seen==['https://example.test/job']


def test_retry_cannot_exceed_the_overall_import_deadline():
    clock=[0];seen=[]
    def fetch(url,deadline):
        seen.append(url);assert deadline==URL_IMPORT_TIMEOUT
        clock[0]=deadline
        raise job_url.PageTimeout('timed out')
    with patch('socket.getaddrinfo',public_dns),patch('app.clients.job_url.time.monotonic',lambda:clock[0]),pytest.raises(job_url.PageTimeout):
        job_url.import_url('https://example.test/job',fetch)
    assert len(seen)==1


def test_redirect_destination_timeouts_get_one_retry():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        if url=='https://example.test/job':return 302,{'location':'https://other.test/job'},b''
        assert url=='https://other.test/job'
        if seen.count(url)==1:raise job_url.PageTimeout('timed out')
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['source_url']=='https://other.test/job'
    assert seen==['https://example.test/job','https://other.test/job','https://other.test/job']


@pytest.mark.parametrize('kind,expected',[('url',URL_WORKER_TIMEOUT),('document',DOCUMENT_WORKER_TIMEOUT)])
def test_url_worker_has_room_for_retry_but_document_limit_is_unchanged(kind,expected):
    with patch('app.domain.preview.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'preview':{}}))) as run:
        assert run_preview(kind,b'synthetic')=={}
        assert run.call_args.kwargs['timeout']==expected
    assert URL_IMPORT_TIMEOUT<URL_WORKER_TIMEOUT==30
    assert DOCUMENT_WORKER_TIMEOUT==20

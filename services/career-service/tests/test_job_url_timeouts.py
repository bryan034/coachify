"""Bounded retries and precise public URL failures, using synthetic requests only."""
import json
import ssl
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.clients import job_url
from app.domain.preview import run_preview
from app.schemas.preview import URL_NETWORK_TIMEOUT,URL_IMPORT_TIMEOUT,URL_WORKER_TIMEOUT,DOCUMENT_WORKER_TIMEOUT


def public_dns(host,port,**kwargs):return [(2,1,6,'',('93.184.216.34',port))]


@pytest.mark.parametrize('failure,expected',[
    (TimeoutError('private diagnostic'),'timed out while checking its robots.txt'),
    (ssl.SSLCertVerificationError('private diagnostic'),'TLS certificate could not be verified'),
    (ssl.SSLError('private diagnostic'),'secure TLS connection'),
    (ConnectionResetError('private diagnostic'),'could not be reached'),
])
def test_network_errors_are_distinct_and_sanitized(failure,expected):
    with patch('socket.getaddrinfo',public_dns),patch('socket.create_connection'),patch('ssl.create_default_context'),patch('http.client.HTTPConnection') as connection:
        connection.return_value.getresponse.side_effect=failure
        with pytest.raises(ValueError,match=expected) as raised:
            job_url.request_page('https://example.test/robots.txt',job_url.time.monotonic()+60)
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


def test_robots_timeout_retries_once_then_fetches_job():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        if len(seen)==1:raise job_url.PageTimeout('timed out')
        if url.endswith('/robots.txt'):return 200,{},b'User-agent: *\nAllow: /'
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['text']=='Analyst requires SQL.'
    assert seen==['https://example.test/robots.txt']*2+['https://example.test/job']


def test_unresponsive_robots_is_unknown_so_the_job_page_is_still_read():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        if url.endswith('/robots.txt'):raise job_url.PageTimeout('timed out')
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['text']=='Analyst requires SQL.'
    assert seen==['https://example.test/robots.txt']*2+['https://example.test/job']


def test_robots_and_page_timeouts_still_fail_as_a_timeout():
    seen=[]
    def fetch(url,deadline):seen.append(url);raise job_url.PageTimeout('timed out')
    with patch('socket.getaddrinfo',public_dns),pytest.raises(job_url.PageTimeout):
        job_url.import_url('https://example.test/job',fetch)
    assert seen==['https://example.test/robots.txt']*2+['https://example.test/job']*2


@pytest.mark.parametrize('status',[401,403,429,503])
def test_robots_refusals_block_without_downloading_job(status):
    seen=[]
    def fetch(url,deadline):seen.append(url);return status,{},b''
    with patch('socket.getaddrinfo',public_dns),pytest.raises(job_url.AccessBlocked,match='Copy and paste the job description'):
        job_url.import_url('https://example.test/job',fetch)
    assert seen==['https://example.test/robots.txt']


@pytest.mark.parametrize('url',['https://www.linkedin.com/jobs/view/1','https://sg.indeed.com/viewjob?jk=1',
    'https://www.glassdoor.sg/job-listing/x','https://www.jobstreet.com.sg/job/1','https://LINKEDIN.COM/jobs/1'])
def test_known_job_aggregators_are_blocked_before_any_network_request(url):
    with patch('socket.getaddrinfo') as dns,pytest.raises(job_url.AccessBlocked):
        job_url.import_url(url,lambda *args:pytest.fail('no request expected'))
    dns.assert_not_called()


def test_lookalike_hosts_are_not_treated_as_aggregators():
    assert not job_url.blocked_host('notlinkedin.com') and not job_url.blocked_host('indeed.com.example.test')


def test_browser_treats_unresponsive_robots_as_unknown():
    from app.clients.job_browser import BrowserAcquisition
    def fetch(url,deadline):raise job_url.PageTimeout('timed out')
    acquisition=BrowserAcquisition(job_url.time.monotonic()+25,fetch)
    with patch('socket.getaddrinfo',public_dns):acquisition.allowed('https://example.test/job')
    assert acquisition.robots=={'https://example.test':None} and acquisition.requests==1


def test_access_restrictions_and_certificate_failures_are_not_retried():
    for failure in ('blocked','certificate'):
        seen=[]
        def fetch(url,deadline):
            seen.append(url)
            if failure=='certificate':raise ValueError('TLS certificate could not be verified')
            return 403,{},b''
        with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError):
            job_url.import_url('https://example.test/job',fetch)
        assert seen==['https://example.test/robots.txt']


def test_retry_cannot_exceed_the_overall_import_deadline():
    clock=[0];seen=[]
    def fetch(url,deadline):
        seen.append(url);assert deadline==URL_IMPORT_TIMEOUT
        clock[0]=deadline
        raise job_url.PageTimeout('timed out')
    with patch('socket.getaddrinfo',public_dns),patch('app.clients.job_url.time.monotonic',lambda:clock[0]),pytest.raises(job_url.PageTimeout):
        job_url.import_url('https://example.test/job',fetch)
    assert len(seen)==1


def test_redirect_robot_timeouts_do_not_multiply_nested_retries():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        if url=='https://example.test/robots.txt':return 404,{},b''
        if url=='https://example.test/job':return 302,{'location':'https://other.test/job'},b''
        if url=='https://other.test/robots.txt':raise job_url.PageTimeout('timed out')
        assert url=='https://other.test/job'
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['source_url']=='https://other.test/job'
    assert seen.count('https://other.test/robots.txt')==2 and len(seen)==5


@pytest.mark.parametrize('kind,expected',[('url',URL_WORKER_TIMEOUT),('document',DOCUMENT_WORKER_TIMEOUT)])
def test_url_worker_has_room_for_retry_but_document_limit_is_unchanged(kind,expected):
    with patch('app.domain.preview.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'preview':{}}))) as run:
        assert run_preview(kind,b'synthetic')=={}
        assert run.call_args.kwargs['timeout']==expected
    assert URL_IMPORT_TIMEOUT<URL_WORKER_TIMEOUT==30
    assert DOCUMENT_WORKER_TIMEOUT==20

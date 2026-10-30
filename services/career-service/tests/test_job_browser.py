"""Browser acquisition policy and handoff checks; no live provider/site access."""
import json
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from fastapi import HTTPException
from app.clients import job_url
from app.clients.job_browser import BrowserAcquisition,MAX_REQUESTS,MAX_TOTAL_BYTES
from app.domain.preview import run_preview,run_browser_preview

URL='https://synthetic.test/job'
SHELL=b'<html><body><div id="root"></div><script src="/app.js"></script><noscript>Enable JavaScript</noscript></body></html>'


def public_dns(host,port,**kwargs):return [(2,1,6,'',('93.184.216.34',port))]


def test_javascript_shell_requests_renderer_only_after_successful_robots_and_html():
    seen=[]
    def fetch(url,deadline):
        seen.append(url)
        return (404,{},b'') if url.endswith('/robots.txt') else (200,{'content-type':'text/html'},SHELL)
    with patch('socket.getaddrinfo',public_dns),pytest.raises(job_url.RenderRequired) as error:
        job_url.import_url(URL,fetch)
    assert error.value.url==URL and seen==['https://synthetic.test/robots.txt',URL]


@pytest.mark.parametrize('status,message',[(401,'requires authentication'),(403,'blocked automated access'),(404,'no longer available'),(410,'no longer available'),(429,'limiting requests'),(503,'temporarily unavailable')])
def test_http_failures_are_precise_and_never_request_browser(status,message):
    def fetch(url,deadline):return (404,{},b'') if url.endswith('/robots.txt') else (status,{'content-type':'text/html'},SHELL)
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match=message) as error:
        job_url.import_url(URL,fetch)
    assert not isinstance(error.value,job_url.RenderRequired)


@pytest.mark.parametrize('page',[b'<title>Just a moment...</title><script src="/challenge"></script>',b'<h1>Sign in</h1>',b'<main>Verify you are human</main>'])
def test_success_status_challenge_pages_do_not_become_jobs_or_trigger_browser(page):
    with pytest.raises(ValueError,match='verification or sign-in'):job_url.check_access_page(page)


def test_short_structured_job_does_not_need_browser():
    assert not job_url.needs_rendering(b'<script type="application/ld+json">{"@type":"JobPosting","description":"SQL"}</script>')


def test_only_url_shell_handoff_starts_browser_and_preserves_one_overall_deadline():
    with patch('app.domain.preview.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'render_url':URL}))),patch('app.domain.preview.run_browser_preview',return_value={'preview':{'text':'SQL'}}) as render:
        assert run_preview('url',URL.encode())=={'text':'SQL'}
        assert render.call_args.args[0]==URL and 0<render.call_args.args[1]-time.monotonic()<=25
    with patch('app.domain.preview.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'preview':{'text':'ordinary'}}))),patch('app.domain.preview.run_browser_preview') as render:
        assert run_preview('url',URL.encode())=={'text':'ordinary'}
        render.assert_not_called()


def test_renderer_timeout_kills_process_group_and_does_not_inherit_credentials():
    process=Mock(pid=54321)
    process.communicate.side_effect=subprocess.TimeoutExpired('browser',1)
    with patch('app.domain.preview.subprocess.Popen',return_value=process) as launch,patch('app.domain.preview.os.killpg') as kill:
        with pytest.raises(HTTPException):run_browser_preview(URL,time.monotonic()+1)
        kill.assert_called_once()
        assert launch.call_args.kwargs['start_new_session'] is True
        assert set(launch.call_args.kwargs['env'])=={'PATH','TMPDIR','HOME','PLAYWRIGHT_BROWSERS_PATH'}
        process.wait.assert_called_once()


def test_expired_import_does_not_launch_browser():
    with patch('app.domain.preview.subprocess.Popen') as launch,pytest.raises(HTTPException):
        run_browser_preview(URL,time.monotonic()-1)
    launch.assert_not_called()


def route(url=URL,method='GET',resource_type='document'):
    page=SimpleNamespace(main_frame=object())
    request=SimpleNamespace(url=url,method=method,resource_type=resource_type,
        frame=SimpleNamespace(page=page),redirected_from=None,is_navigation_request=lambda:resource_type=='document')
    request.frame=page.main_frame=SimpleNamespace(page=page)
    return Mock(request=request)


def test_browser_network_is_fulfilled_by_pinned_fetcher_without_cookies():
    calls=[]
    def fetch(url,deadline):
        calls.append(url)
        if url.endswith('/robots.txt'):return 404,{},b''
        return 200,{'content-type':'text/html','set-cookie':'secret','x-private':'private'},b'<main>Analyst SQL</main>'
    acquisition=BrowserAcquisition(time.monotonic()+25,fetch)
    request=route()
    with patch('socket.getaddrinfo',public_dns):acquisition.route(request)
    assert calls==['https://synthetic.test/robots.txt',URL]
    request.fulfill.assert_called_once_with(status=200,headers={'content-type':'text/html'},body=b'<main>Analyst SQL</main>')
    request.continue_.assert_not_called()


@pytest.mark.parametrize('method,kind',[('POST','xhr'),('GET','image'),('GET','font'),('GET','media')])
def test_submissions_and_unnecessary_assets_never_reach_network(method,kind):
    fetch=Mock()
    acquisition=BrowserAcquisition(time.monotonic()+25,fetch)
    request=route(method=method,resource_type=kind)
    acquisition.route(request)
    request.abort.assert_called_once();fetch.assert_not_called()


def test_browser_cannot_fetch_private_destinations_or_disallowed_robots():
    request=route('http://127.0.0.1/private')
    fetch=Mock()
    acquisition=BrowserAcquisition(time.monotonic()+25,fetch)
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]):acquisition.route(request)
    request.abort.assert_called_once();fetch.assert_not_called()
    assert 'Private' in str(acquisition.failure)
    request=route()
    acquisition=BrowserAcquisition(time.monotonic()+25,lambda *args:(200,{},b'User-agent: *\nDisallow: /'))
    with patch('socket.getaddrinfo',public_dns):acquisition.route(request)
    assert acquisition.requests==1 and 'restricts' in str(acquisition.failure)
    request.abort.assert_called_once()


def test_resource_and_total_download_budgets_are_bounded():
    acquisition=BrowserAcquisition(time.monotonic()+25,lambda *args:(200,{},b'x'))
    acquisition.requests=MAX_REQUESTS
    with pytest.raises(ValueError,match='too many'):acquisition.read(URL)
    acquisition.requests=0;acquisition.bytes=MAX_TOTAL_BYTES
    with pytest.raises(ValueError,match='too large'):acquisition.read(URL)


def test_timeout_cleanup_includes_detached_browser_descendants():
    process=Mock(pid=54321)
    process.communicate.side_effect=subprocess.TimeoutExpired('browser',1)
    with patch('app.domain.preview.subprocess.Popen',return_value=process),patch('app.domain.preview.child_processes',return_value=[54322,54323]),patch('app.domain.preview.os.kill') as kill,patch('app.domain.preview.os.killpg') as kill_group:
        with pytest.raises(HTTPException):run_browser_preview(URL,time.monotonic()+1)
        assert [call.args[0] for call in kill.call_args_list]==[54323,54322]
        kill_group.assert_called_once()


def test_renderer_preserves_cors_and_page_security_headers_but_not_cookies():
    def fetch(url,deadline):
        if url.endswith('/robots.txt'):return 404,{},b''
        return 200,{'content-type':'application/javascript','access-control-allow-origin':'*',
            'content-security-policy':"default-src 'self'",'set-cookie':'must-not-forward'},b'console.log("synthetic");'
    acquisition=BrowserAcquisition(time.monotonic()+25,fetch)
    request=route(URL+'/app.js',resource_type='script')
    with patch('socket.getaddrinfo',public_dns):acquisition.route(request)
    headers=request.fulfill.call_args.kwargs['headers']
    assert headers['access-control-allow-origin']=='*' and headers['content-security-policy']=="default-src 'self'"
    assert 'set-cookie' not in headers

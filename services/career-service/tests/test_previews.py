import asyncio
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from starlette.datastructures import UploadFile
from app.main import create_app
from app.domain.documents import document_text, validate_text
from app.domain.preview import run_preview
from app.clients import job_url
from app.schemas.preview import MAX_FILE, MAX_TEXT, MAX_BODY

BASE='/api/v1/career/imports'
AUTH={'Authorization':'Bearer synthetic-session'}
TEXT='Analyst — 数据\nResponsibilities\n• Research and communicate findings.\nRequirements\nPython or SQL.'


def profile(status=200, body=None, setup_status=200, setup_body=None):
    def handle(request):
        assert request.headers['Authorization'] == AUTH['Authorization']
        if request.url.path == '/api/v1/profile':
            return httpx.Response(setup_status,json=setup_body if setup_body is not None else {'onboarding_complete':True})
        assert request.url.path == '/api/v1/profile/auth/session'
        return httpx.Response(status,json=body if body is not None else {'id':'synthetic-account','email_verified':True})
    return httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(handle))


def fixture_client(processor=run_preview, status=200, body=None):
    return TestClient(create_app(profile(status,body),processor))


def docx(text='Build models & communicate results', extra=None):
    out=BytesIO()
    with ZipFile(out,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('word/document.xml',f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>{text.replace("&","&amp;")}</w:t><w:br/><w:t>Next line</w:t></w:r></w:p></w:body></w:document>')
        for name,data in (extra or {}).items():archive.writestr(name,data)
    return out.getvalue()


def pdf(blank=False, encrypted=False):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer=PdfWriter(); page=writer.add_blank_page(612,792)
    if not blank:
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 50 700 Td (Analyst requirements: SQL) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
    if encrypted:writer.encrypt('synthetic-password')
    out=BytesIO();writer.write(out);return out.getvalue()


def test_authentication_happens_before_import_processing():
    def no_processing(*args):raise AssertionError('unauthorised processing')
    with fixture_client(no_processing) as client:
        assert client.post(BASE+'/url',json={'url':'https://example.test/job'}).status_code==401
        assert client.post(BASE+'/document',files={'file':('role.txt',TEXT,'text/plain')}).status_code==401


@pytest.mark.parametrize('status,body,expected',[(401,{},401),(503,{},503),(200,{'id':'a','email_verified':False},503),(200,{},503),(200,['invalid'],503)])
def test_invalid_profile_session_fails_closed(status,body,expected):
    with fixture_client(lambda *args:None,status,body) as client:
        response=client.post(BASE+'/url',json={'url':'https://example.test/job'},headers=AUTH)
        assert response.status_code==expected
        assert response.headers['Cache-Control']=='no-store'


def test_profile_outage_returns_recoverable_error():
    def outage(request):raise httpx.ConnectError('synthetic outage')
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(outage))
    with TestClient(create_app(upstream)) as client:
        assert client.post(BASE+'/url',json={'url':'https://example.test/job'},headers=AUTH).status_code==503


@pytest.mark.parametrize('status,body,expected',[(200,{},403),(200,{'onboarding_complete':False,'version':12},403),
    (200,{'onboarding_complete':'true'},403),(401,{},401),(503,{},503),(200,[],503)])
def test_imports_require_canonical_onboarding_before_processing(status,body,expected):
    def no_processing(*args):raise AssertionError('unfinished accounts must not process sources')
    with TestClient(create_app(profile(setup_status=status,setup_body=body),no_processing)) as client:
        assert client.post(BASE+'/url',json={'url':'https://example.test/job'},headers=AUTH).status_code==expected
        assert client.post(BASE+'/document',files={'file':('role.txt',TEXT,'text/plain')},headers=AUTH).status_code==expected


@pytest.mark.parametrize('extension,mime,data,expected',[
    ('.txt','text/plain',TEXT.encode(),TEXT),
    ('.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document',docx(),'• Build models & communicate results\nNext line'),
    ('.pdf','application/pdf',pdf(),'Analyst requirements: SQL'),
])
def test_supported_documents_through_real_child_process(extension,mime,data,expected):
    with fixture_client() as client:
        response=client.post(BASE+'/document',files={'file':('role'+extension,data,mime)},headers=AUTH)
        assert response.status_code==200,response.text
        result=response.json();assert result['text']==expected
        assert result['kind']=='document' and result['source_name']=='role'+extension
        assert response.headers['Cache-Control']=='no-store'
        assert 'id' not in result
        # No read/save API exists: preview content cannot be recovered from the service.
        assert client.get('/api/v1/career/sources').status_code==404


@pytest.mark.parametrize('name,data,mime,expected',[
    ('role.doc',b'text','application/msword',422),
    ('role.txt',b'','text/plain',422),
    ('role.pdf',b'not-pdf','application/pdf',422),
    ('role.docx',b'not-docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document',422),
    ('role.txt',b'\x00\x02','text/plain',422),
    ('role.txt',b'\xff\xfe','text/plain',422),
    ('role.txt',b'text','image/png',422),
    ('role.pdf',pdf(blank=True),'application/pdf',422),
    ('role.pdf',pdf(encrypted=True),'application/pdf',422),
])
def test_invalid_documents_are_recoverable(name,data,mime,expected):
    with fixture_client() as client:
        response=client.post(BASE+'/document',files={'file':(name,data,mime)},headers=AUTH)
        assert response.status_code==expected,response.text
        assert 'detail' in response.json()


def test_text_boundaries_preserve_unicode_and_whitespace():
    text=' \n'+'🧭'*(MAX_TEXT-3)+'\n'
    assert document_text(text.encode(),'.txt')['text']==text
    with pytest.raises(ValueError,match='20,000'):document_text(('🧭'*(MAX_TEXT+1)).encode(),'.txt')
    with pytest.raises(ValueError,match='No readable'):validate_text(' \n\t')


def test_file_size_boundaries_and_body_limit():
    with patch('app.domain.documents.validate_text',return_value='synthetic'):
        assert document_text(b'x'*MAX_FILE,'.txt')['text']=='synthetic'
    with pytest.raises(ValueError):document_text(b'x'*(MAX_FILE+1),'.txt')
    with fixture_client() as client:
        assert client.post(BASE+'/document',files={'file':('role.txt',b'x'*(MAX_FILE+1),'text/plain')},headers=AUTH).status_code==413
        assert client.post(BASE+'/document',content=b'x'*(MAX_BODY+1),headers=AUTH).status_code==413
        assert client.post(BASE+'/document',content=(b'x'*65536 for _ in range(170)),headers={**AUTH,'Content-Type':'multipart/form-data; boundary=test'}).status_code in {400,413}


def test_uploads_closed_on_success_and_failure(monkeypatch):
    closed=[]; original=UploadFile.close
    async def close(self):
        await original(self);closed.append(self.file.closed)
    monkeypatch.setattr(UploadFile,'close',close)
    with fixture_client() as client:
        assert client.post(BASE+'/document',files={'file':('role.txt',TEXT,'text/plain')},headers=AUTH).status_code==200
        assert client.post(BASE+'/document',files={'file':('role.pdf',b'invalid','application/pdf')},headers=AUTH).status_code==422
        assert client.post(BASE+'/document',files={'file':('role.exe',b'invalid','application/octet-stream')},headers=AUTH).status_code==422
    assert closed==[True,True,True]


def test_form_structure_and_filename_are_checked():
    with fixture_client() as client:
        result=client.post(BASE+'/document',files={'file':('../../role.txt',TEXT,'text/plain')},headers=AUTH)
        assert result.json()['source_name']=='role.txt'
        assert client.post(BASE+'/document',json={'file':'not-a-file'},headers=AUTH).status_code==415
        assert client.post(BASE+'/document',files=[('file',('a.txt',TEXT)),('file',('b.txt',TEXT))],headers=AUTH).status_code==400
        assert client.post(BASE+'/document',files={'wrong':('role.txt',TEXT)},headers=AUTH).status_code==422


def test_docx_archive_and_xml_safety():
    with pytest.raises(ValueError,match='macro'):document_text(docx(extra={'word/vbaProject.bin':b'fake'}),'.docx')
    data=BytesIO()
    with ZipFile(data,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY test SYSTEM "file:///etc/passwd">]><x>&test;</x>')
    with pytest.raises(ValueError,match='could not be read'):document_text(data.getvalue(),'.docx')


def test_timeout_and_child_failure_are_sanitized():
    import subprocess
    for error in [subprocess.TimeoutExpired('synthetic',20),subprocess.CalledProcessError(1,'synthetic')]:
        with patch('app.domain.preview.subprocess.run',side_effect=error),pytest.raises(HTTPException) as result:
            run_preview('document',b'text','.txt')
        assert result.value.status_code==422
        assert 'synthetic' not in result.value.detail


def test_url_input_contract_and_no_owner_override():
    calls=[]
    def preview(kind,data,extension):
        calls.append((kind,data))
        return {'kind':'url','text':TEXT,'source_name':'example.test','source_url':data.decode(),'notices':[]}
    with fixture_client(preview) as client:
        assert client.post(BASE+'/url',json={'url':'https://example.test/job'},headers=AUTH).status_code==200
        for data in [{'url':''},{'url':'x'*2049},{'url':'https://example.test','owner':'another-user'}]:
            assert client.post(BASE+'/url',json=data,headers=AUTH).status_code==422
    assert len(calls)==1


def public_dns(host,port,**kwargs):return [(2,1,6,'',('93.184.216.34',port))]


@pytest.mark.parametrize('url', ['file:///tmp/a','ftp://example.test/a','http://user:password@example.test/a','http://example.test:8000/a','http://example.test\\@127.0.0.1/','http://example.test/\nHeader: x'])
def test_unsafe_url_syntax_rejected(url):
    with pytest.raises(ValueError),patch('socket.getaddrinfo',public_dns):job_url.destination(url)


@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','169.254.169.254','192.168.1.1','0.0.0.0','::1','fe80::1','::ffff:127.0.0.1','100.64.0.1'])
def test_private_and_special_dns_addresses_rejected(address):
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(address,80))]),pytest.raises(ValueError,match='Private'):
        job_url.destination('https://example.test/job')


def test_mixed_public_private_dns_is_rejected():
    with patch('socket.getaddrinfo',return_value=public_dns('x',443)+[(2,1,6,'',('127.0.0.1',443))]),pytest.raises(ValueError):
        job_url.destination('https://example.test/job')


def test_redirect_dns_checked_before_connection():
    connected=[]
    def dns(host,port,**kwargs):return public_dns(host,port) if host=='example.test' else [(2,1,6,'',('127.0.0.1',port))]
    def fetch(url,deadline):
        job_url.destination(url);connected.append(url)
        return 302,{'location':'http://internal.test/job'},b''
    with patch('socket.getaddrinfo',dns),pytest.raises(ValueError,match='Private'):
        job_url.fetch_following('https://example.test/job',999999999999,fetch)
    assert connected==['https://example.test/job']


def test_tls_request_uses_validated_address_and_original_hostname():
    class Response:
        status=200
        def getheaders(self):return [('Content-Type','text/html')]
        def read1(self,n):return b''
    with patch('socket.getaddrinfo',public_dns),patch('socket.create_connection') as connect,patch('ssl.create_default_context') as context,patch('http.client.HTTPConnection') as connection:
        connection.return_value.getresponse.return_value=Response()
        job_url.request_page('https://example.test/job',__import__('time').monotonic()+10)
        assert connect.call_args.args[0]==('93.184.216.34',443)
        assert context.return_value.wrap_socket.call_args.kwargs['server_hostname']=='example.test'
        assert connection.return_value.request.call_args.kwargs['headers']['Accept-Encoding']=='identity'


def test_jobposting_and_readable_html_extraction():
    page=b'<script type="application/ld+json">{"@type":"JobPosting","title":"Analyst","description":"<p>Requirements</p><ul><li>SQL or Python</li></ul>"}</script><nav>Ignore</nav>'
    text=job_url.extract_page(page)
    assert 'Analyst' in text and 'SQL or Python' in text and 'Ignore' not in text
    assert job_url.extract_page(b'<nav>Ignore</nav><main><h1>Analyst</h1><p>Build <strong>models</strong>.</p><p>SQL</p></main>')=='Analyst\nBuild models.\nSQL'
    with pytest.raises(ValueError,match='multiple jobs'):
        job_url.extract_page(b'<script type="application/ld+json">[{"@type":"JobPosting"},{"@type":"JobPosting"}]</script>')


@pytest.mark.parametrize('status,content_type',[(403,'text/html'),(404,'text/html'),(200,'application/pdf')])
def test_blocked_or_unsupported_job_page_has_fallback(status,content_type):
    def fetch(url,deadline):
        if url.endswith('/robots.txt'):return 404,{},b''
        return status,{'content-type':content_type},b'<main>Read this job</main>'
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='[Pp]aste|upload'):
        job_url.import_url('https://example.test/job',fetch)


def test_robots_and_redirect_limits():
    seen=[]
    def fetch(url,deadline):seen.append(url);return 200,{},b'User-agent: *\nDisallow: /'
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='restricts'):
        job_url.import_url('https://example.test/job',fetch)
    assert len(seen)==1
    with pytest.raises(ValueError,match='too many'):
        job_url.fetch_following('https://example.test/job',999999,lambda u,d:(302,{'location':'/again'},b''))


def test_url_preview_has_only_temporary_metadata():
    def fetch(url,deadline):
        if url.endswith('/robots.txt'):return 404,{},b''
        return 200,{'content-type':'text/html; charset=utf-8'},b'<main><h1>Analyst</h1><p>SQL</p></main>'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url('https://example.test/job',fetch)
    assert result['kind']=='url' and result['source_url']=='https://example.test/job'
    assert 'id' not in result


def test_concurrent_import_limit_precedes_document_parsing():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    entered=Event();release=Event();lock=Lock();count=0
    def processor(kind,data,extension):
        nonlocal count
        with lock:
            count+=1
            if count==2:entered.set()
        assert release.wait(5)
        return {'kind':'document','text':'Synthetic role','source_name':'role.txt','notices':[]}
    with fixture_client(processor) as client,ThreadPoolExecutor(2) as pool:
        jobs=[pool.submit(client.post,BASE+'/document',files={'file':('role.txt',TEXT,'text/plain')},headers=AUTH) for _ in range(2)]
        try:
            assert entered.wait(5)
            response=client.post(BASE+'/document',content=b'not even valid multipart',headers={**AUTH,'Content-Type':'multipart/form-data; boundary=x'})
            assert response.status_code==429
            assert count==2
        finally:release.set()
        assert [job.result().status_code for job in jobs]==[200,200]


def test_chunked_upload_is_bounded_even_without_content_length():
    prefix=b'--preview\r\nContent-Disposition: form-data; name="file"; filename="role.txt"\r\nContent-Type: text/plain\r\n\r\n'
    def chunks():
        yield prefix
        for _ in range(162):yield b'x'*65536
        yield b'\r\n--preview--\r\n'
    with fixture_client() as client:
        response=client.post(BASE+'/document',content=chunks(),headers={**AUTH,'Content-Type':'multipart/form-data; boundary=preview'})
        assert response.status_code==413,response.text


def test_redirect_destination_robots_is_checked_before_job_content():
    requested=[]
    def fetch(url,deadline):
        requested.append(url)
        if url=='https://example.test/robots.txt':return 404,{},b''
        if url=='https://example.test/job':return 302,{'location':'https://other.test/job'},b''
        if url=='https://other.test/robots.txt':return 200,{},b'User-agent: *\nDisallow: /job'
        raise AssertionError('blocked destination job must not be downloaded')
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='restricts'):
        job_url.import_url('https://example.test/job',fetch)
    assert requested==['https://example.test/robots.txt','https://example.test/job','https://other.test/robots.txt']

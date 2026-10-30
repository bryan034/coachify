"""Disposable JavaScript rendering, with every network read through the pinned fetcher."""
import time
import tempfile
from urllib.parse import urlsplit,urlunsplit
from urllib.robotparser import RobotFileParser
from app.clients import job_url

MAX_REQUESTS=24
MAX_TOTAL_BYTES=8*1024*1024


class BrowserAcquisition:
    def __init__(self,deadline,fetch=job_url.request_page):
        self.deadline=deadline
        self.fetch=fetch
        self.requests=0
        self.bytes=0
        self.robots={}
        self.failure=None

    def read(self,url,deadline=None):
        self.requests+=1
        if self.requests>MAX_REQUESTS:raise ValueError('This page needs too many resources. Paste the description or upload a document.')
        job_url.network_timeout(self.deadline)
        status,headers,data=job_url.fetch_with_timeout_retry(url,self.deadline,self.fetch)
        self.bytes+=len(data)
        if self.bytes>MAX_TOTAL_BYTES:raise ValueError('This page is too large to render. Paste the description or upload a document.')
        return status,headers,data

    def allowed(self,url):
        parsed,*_=job_url.destination(url)
        origin=urlunsplit((parsed.scheme,parsed.netloc,'','',''))
        if origin not in self.robots:
            # Redirect robots files go through the existing bounded public fetcher.
            _,status,_,data=job_url.fetch_following(origin+'/robots.txt',self.deadline,self.read)
            if status in (401,403,429) or status>=500:
                raise ValueError('This website restricts automated access. Paste the description or upload a document.')
            rules=RobotFileParser()
            rules.parse(data.decode('utf-8',errors='replace').splitlines() if status==200 else [])
            self.robots[origin]=rules if status==200 else None
        rules=self.robots[origin]
        if rules is not None and not rules.can_fetch(job_url.AGENT,url):
            raise ValueError('This website restricts automated access. Paste the description or upload a document.')

    def route(self,route):
        request=route.request
        try:
            # No form submission, browser credentials, binary assets or background sockets.
            if request.method!='GET' or request.resource_type not in {'document','script','xhr','fetch'}:
                route.abort();return
            if request.resource_type=='document' and request.frame!=request.frame.page.main_frame:
                route.abort();return
            previous=request.redirected_from
            redirects=0
            while previous is not None:
                redirects+=1;previous=previous.redirected_from
                if redirects>3:raise ValueError('The website redirects too many times. Paste the description instead.')
            self.allowed(request.url)
            status,headers,data=self.read(request.url)
            if request.is_navigation_request():
                if status not in (301,302,303,307,308):
                    job_url.check_page_status(status)
                    if headers.get('content-type','').split(';')[0].strip().lower() not in {'text/html','application/xhtml+xml'}:
                        raise ValueError('Use a public HTML job page, or upload the document instead.')
                    job_url.check_access_page(data)
            safe_headers={'content-type':headers.get('content-type','text/plain')}
            for name in ('access-control-allow-origin','content-security-policy','x-content-type-options','cross-origin-resource-policy'):
                if name in headers:safe_headers[name]=headers[name]
            if status in (301,302,303,307,308):
                location=headers.get('location')
                if not location:raise ValueError('The website returned an invalid redirect. Paste the description instead.')
                safe_headers['location']=location
            # No Set-Cookie, remote headers or browser-supplied cookies/Authorization are forwarded.
            route.fulfill(status=status,headers=safe_headers,body=data)
        except ValueError as exc:
            self.failure=exc
            route.abort()


def render_url(url,deadline,fetch=job_url.request_page):
    from playwright.sync_api import sync_playwright,TimeoutError as BrowserTimeout,Error as BrowserError
    job_url.destination(url)
    acquisition=BrowserAcquisition(deadline,fetch)
    try:
        with sync_playwright() as playwright:
            # Chromium has no direct network path: intercepted requests are fulfilled
            # above, and all unintercepted HTTP traffic hits a closed loopback proxy.
            browser=playwright.chromium.launch(headless=True,chromium_sandbox=True,env={'HOME':tempfile.gettempdir(),'TMPDIR':tempfile.gettempdir()},
                args=['--proxy-server=http://127.0.0.1:9','--proxy-bypass-list=<-loopback>',
                    '--disable-background-networking','--disable-quic','--host-resolver-rules=MAP * ~NOTFOUND',
                    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
            try:
                context=browser.new_context(user_agent=job_url.AGENT,service_workers='block',accept_downloads=False)
                context.route('**/*',acquisition.route)
                context.route_web_socket('**/*',lambda ws:ws.close())
                page=context.new_page()
                page.on('dialog',lambda dialog:dialog.dismiss())
                page.goto(url,wait_until='domcontentloaded',timeout=max(1,(deadline-time.monotonic())*1000))
                try:
                    page.wait_for_function("""() => Array.from(document.querySelectorAll('script[type="application/ld+json"]')).some(s => s.textContent.includes('JobPosting')) || (document.body && document.body.innerText.length >= 200 && !/enable javascript/i.test(document.body.innerText))""",
                        timeout=max(1,min(8000,(deadline-time.monotonic())*1000)))
                except BrowserTimeout:
                    pass
                if acquisition.failure:raise acquisition.failure
                content=page.content().encode('utf-8')
                if len(content)>job_url.MAX_DOWNLOAD:raise ValueError('The rendered page is too large. Paste the description instead.')
                job_url.check_access_page(content)
                if job_url.needs_rendering(content):raise ValueError('The page did not provide a readable job description after loading. Paste the description or upload a document.')
                final=page.url
                job_url.destination(final)
                return {'kind':'url','text':job_url.extract_page(content),'source_name':urlsplit(final).hostname,'source_url':final,
                    'notices':['Prepared using an isolated JavaScript browser. Check that the preview contains one complete job description.',
                        'This is a temporary preview; no role or skills have been interpreted.']}
            finally:
                browser.close()
    except BrowserError:
        if acquisition.failure:raise acquisition.failure
        raise ValueError('The JavaScript page could not be loaded within the import limits. Paste the description or upload a document.') from None

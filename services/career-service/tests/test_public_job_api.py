"""Official public job-board acquisition; no provider keys or application writes."""
import json
from unittest.mock import patch
import pytest
from app.clients import job_url

URL='https://careers.roblox.com/jobs/8143981'
API='https://boards-api.greenhouse.io/v1/boards/roblox/jobs/8143981'


def public_dns(host,port,**kwargs):return [(2,1,6,'',('93.184.216.34',port))]


def posting(**updates):
    return {'id':8143981,'title':'Product Management Intern','company_name':'Roblox',
        'absolute_url':URL+'?gh_jid=8143981','location':{'name':'San Mateo, CA'},
        'content':'&lt;p&gt;Research user needs.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Analyse product data.&lt;/li&gt;&lt;/ul&gt;',
        'questions':[{'label':'An application-form question, not a job requirement'}],**updates}


def test_known_employer_uses_matching_public_api_and_preserves_both_source_references():
    calls=[]
    def fetch(url,deadline):
        calls.append(url)
        assert url==API
        return 200,{'content-type':'application/json; charset=utf-8'},json.dumps(posting()).encode()
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url(URL,fetch)
    assert calls==[API]
    assert result['source_url']==URL and result['source_name']=='careers.roblox.com'
    for text in ('Product Management Intern','Company: Roblox','San Mateo','Research user needs','Analyse product data'):
        assert text in result['text']
    assert 'application-form question' not in result['text'] and '&lt;' not in result['text']
    assert any(API in notice for notice in result['notices'])


@pytest.mark.parametrize('updates',[
    {'id':123},{'id':True},{'title':None},{'content':''},{'content':'<script>bad()</script>'},
    {'absolute_url':'https://other.test/jobs/8143981'},
    {'absolute_url':'https://careers.roblox.com/jobs/123'},
    {'absolute_url':'https://user:password@careers.roblox.com/jobs/8143981'},
    {'absolute_url':'http://careers.roblox.com/jobs/8143981'},
])
def test_mismatched_or_unreadable_api_data_cannot_become_the_job(updates):
    def fetch(url,deadline):return 200,{'content-type':'application/json'},json.dumps(posting(**updates)).encode()
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='matching readable'):
        job_url.import_url(URL,fetch)


@pytest.mark.parametrize('status',[302,403,404,429,500])
def test_api_failures_do_not_follow_redirects_or_download_html(status):
    calls=[]
    def fetch(url,deadline):
        calls.append(url)
        return status,{'location':'http://127.0.0.1/private'},b'private upstream error'
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError) as error:
        job_url.import_url(URL,fetch)
    assert calls==[API] and 'private' not in str(error.value)


def test_api_timeout_retains_the_single_retry_limit():
    calls=[]
    def fetch(url,deadline):calls.append(url);raise job_url.PageTimeout('timed out')
    with patch('socket.getaddrinfo',public_dns),pytest.raises(job_url.PageTimeout):job_url.import_url(URL,fetch)
    assert calls==[API,API]


def test_arbitrary_hosts_keep_the_existing_html_flow():
    calls=[]
    def fetch(url,deadline):
        calls.append(url)
        return 200,{'content-type':'text/html'},b'<main>Analyst requires SQL.</main>'
    url='https://careers.other.test/jobs/8143981'
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url(url,fetch)
    assert calls==[url]
    assert result['source_url']==url


def test_private_dns_is_rejected_before_any_api_request():
    def forbidden(*args):pytest.fail('Unsafe input must not trigger acquisition')
    with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),pytest.raises(ValueError,match='Private'):
        job_url.import_url(URL,forbidden)


@pytest.mark.parametrize('host',['boards.greenhouse.io','job-boards.greenhouse.io'])
def test_greenhouse_hosted_links_use_board_scoped_public_api(host):
    url=f'https://{host}/synthetic/jobs/8143981?source=tracking'
    seen=[]
    def fetch(target,deadline):
        seen.append(target)
        return 200,{'content-type':'application/json'},json.dumps(posting(absolute_url=url)).encode()
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url(url,fetch)
    assert seen==['https://boards-api.greenhouse.io/v1/boards/synthetic/jobs/8143981']
    assert result['source_url']==url and 'Research user needs' in result['text']


@pytest.mark.parametrize('host,api_host',[('jobs.lever.co','api.lever.co'),('jobs.eu.lever.co','api.eu.lever.co')])
def test_lever_public_api_preserves_requirements_sections(host,api_host):
    job_id='12345678-1234-1234-1234-123456789abc'
    url=f'https://{host}/synthetic/{job_id}'
    job={'id':job_id,'text':'Analyst','hostedUrl':url,'description':'<p>Analyse user needs.</p>',
        'categories':{'location':'Singapore','commitment':'Full time'},'workplaceType':'hybrid',
        'lists':[{'text':'Requirements','content':'<li>SQL and communication</li>'}],
        'additional':'<p>Work with researchers.</p>','salaryDescription':'<p>Salary by experience.</p>',
        'questions':['Must not appear in preview']}
    def fetch(target,deadline):
        assert target==f'https://{api_host}/v0/postings/synthetic/{job_id}?mode=json'
        return 200,{'content-type':'application/json'},json.dumps(job).encode()
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url(url,fetch)
    for text in ('SQL and communication','Requirements','Work with researchers','Singapore','hybrid','Salary by experience'):
        assert text in result['text']
    assert 'Must not appear' not in result['text'] and result['source_url']==url


@pytest.mark.parametrize('url',[
    'https://jobs.lever.co.evil.test/synthetic/12345678-1234-1234-1234-123456789abc',
    'https://boards.greenhouse.io/synthetic/../jobs/123',
    'https://boards.greenhouse.io/synthetic%2fother/jobs/123',
    'https://jobs.lever.co/synthetic/not-a-job-id',
    'https://boards-api.greenhouse.io/v1/boards/synthetic/jobs/123',
])
def test_unsupported_or_spoofed_paths_cannot_construct_api_targets(url):
    from app.clients.public_job_api import mapping
    from urllib.parse import urlsplit
    assert mapping(urlsplit(url)) is None


def test_lever_mismatched_id_and_host_are_rejected():
    url='https://jobs.lever.co/synthetic/12345678-1234-1234-1234-123456789abc'
    for job in ({'id':'other'}, {'id':url.rsplit('/',1)[1],'text':'Role','description':'<p>SQL</p>','hostedUrl':'https://other.test/job'}):
        with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='matching readable'):
            job_url.import_url(url,lambda *args:(200,{'content-type':'application/json'},json.dumps(job).encode()))


MCF_ID='0123456789abcdef0123456789abcdef'
MCF_URL=f'https://www.mycareersfuture.gov.sg/job/information-technology/data-analyst-synthetic-analytics-{MCF_ID}'
MCF_API=f'https://api.mycareersfuture.gov.sg/v2/jobs/{MCF_ID}'


def mcf_job(**updates):
    job={'uuid':MCF_ID,'title':'Data Analyst','description':'<p>Analyse product data with <strong>SQL</strong>.</p>',
        'otherRequirements':'<p>Degree in a quantitative field.</p>','minimumYearsExperience':2,
        'postedCompany':{'name':'Synthetic Analytics Pte. Ltd.'},'hiringCompany':None,
        'address':{'isOverseas':False,'districts':[{'region':'Central'}]},
        'employmentTypes':[{'employmentType':'Full Time'}],'positionLevels':[{'position':'Executive'}],
        'flexibleWorkArrangements':[{'flexibleWorkArrangement':'Hybrid'}],'categories':[{'category':'Information Technology'}],
        'skills':[{'skill':'SQL'},{'skill':'Tableau'}],'salary':{'minimum':4000,'maximum':5500,'type':{'salaryType':'Monthly'}},
        'screeningQuestions':[{'question':'An application-form question, not a job requirement'}],
        'metadata':{'jobDetailsUrl':MCF_URL,'isHideSalary':False,'isHideCompanyAddress':False,
            'isHideEmployerName':False,'isHideHiringEmployerName':False}}
    job.update(updates)
    return job


@pytest.mark.parametrize('url',[MCF_URL,MCF_URL+'/?source=share','https://mycareersfuture.gov.sg/job/'+MCF_ID])
def test_mycareersfuture_links_use_the_public_job_api(url):
    seen=[]
    def fetch(target,deadline):
        seen.append(target)
        return 200,{'content-type':'application/json; charset=utf-8'},json.dumps(mcf_job()).encode()
    with patch('socket.getaddrinfo',public_dns):result=job_url.import_url(url,fetch)
    assert seen==[MCF_API]
    for text in ('Data Analyst','Company: Synthetic Analytics Pte. Ltd.','Job location: Central, Singapore',
            'Employment type: Full Time','Position level: Executive','Work arrangement: Hybrid',
            'Experience requirements: at least 2 years','Salary: SGD 4,000–5,500 (monthly)','Skills: SQL; Tableau',
            'Analyse product data with SQL.','Degree in a quantitative field.'):
        assert text in result['text']
    assert 'application-form question' not in result['text'] and '<p>' not in result['text']
    assert result['source_url']==url and any('MyCareersFuture' in notice and MCF_API in notice for notice in result['notices'])


def test_mycareersfuture_keeps_employer_hidden_details_hidden():
    job=mcf_job(metadata={**mcf_job()['metadata'],'isHideSalary':True,'isHideCompanyAddress':True,'isHideEmployerName':True})
    with patch('socket.getaddrinfo',public_dns):
        result=job_url.import_url(MCF_URL,lambda *args:(200,{'content-type':'application/json'},json.dumps(job).encode()))
    for hidden in ('Synthetic Analytics','Salary','Central'):
        assert hidden not in result['text']
    assert 'Analyse product data with SQL.' in result['text']


@pytest.mark.parametrize('updates',[
    {'uuid':'f'*32},{'title':None},{'description':''},{'description':None},
    {'metadata':{'jobDetailsUrl':'https://other.test/job/'+MCF_ID}},
    {'metadata':{'jobDetailsUrl':'https://www.mycareersfuture.gov.sg/job/x/other-'+'f'*32}},
    {'metadata':{'jobDetailsUrl':'http://www.mycareersfuture.gov.sg/job/x/'+MCF_ID}},
])
def test_mycareersfuture_mismatched_or_unreadable_jobs_are_rejected(updates):
    def fetch(url,deadline):return 200,{'content-type':'application/json'},json.dumps(mcf_job(**updates)).encode()
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='matching readable'):
        job_url.import_url(MCF_URL,fetch)


def test_mycareersfuture_missing_job_names_the_board():
    with patch('socket.getaddrinfo',public_dns),pytest.raises(ValueError,match='no longer available on MyCareersFuture'):
        job_url.import_url(MCF_URL,lambda *args:(404,{'content-type':'application/json'},b'{}'))


@pytest.mark.parametrize('url',[
    'https://www.mycareersfuture.gov.sg/job/engineering/not-a-job-id',
    'https://www.mycareersfuture.gov.sg/search?search='+MCF_ID,
    'https://www.mycareersfuture.gov.sg.evil.test/job/x/'+MCF_ID,
    'http://www.mycareersfuture.gov.sg/job/x/'+MCF_ID,
    'https://www.mycareersfuture.gov.sg/job/a/b/c/'+MCF_ID,
])
def test_mycareersfuture_unsupported_paths_do_not_construct_api_targets(url):
    from app.clients.public_job_api import mapping
    from urllib.parse import urlsplit
    assert mapping(urlsplit(url)) is None

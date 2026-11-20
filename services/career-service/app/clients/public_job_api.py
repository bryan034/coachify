"""Read-only public job API adapters (ATS boards and MyCareersFuture). All API origins and path grammars are fixed."""
import html
import json
import re
from http import HTTPStatus
from urllib.parse import urlsplit
from app.clients.public_url import destination,html_text
from app.domain.documents import validate_text
from app.schemas.preview import MAX_JD_TEXT

MAX_LISTS = 100

GREENHOUSE_HOSTS={'boards.greenhouse.io','job-boards.greenhouse.io'}
LEVER_HOSTS={'jobs.lever.co':'api.lever.co','jobs.eu.lever.co':'api.eu.lever.co'}
BOARD=r'[A-Za-z0-9_-]{1,100}'
JOB=r'[1-9][0-9]{0,11}'
UUID=r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
MCF_HOSTS={'www.mycareersfuture.gov.sg','mycareersfuture.gov.sg'}
MCF_JOB=r'/job/(?:[a-z0-9-]{1,100}/)?(?:[a-z0-9-]{0,300}-)?([0-9a-f]{32})/?'


def mapping(parsed):
    if parsed.scheme!='https':return None
    if parsed.hostname=='careers.roblox.com':
        match=re.fullmatch(rf'/jobs/({JOB})/?',parsed.path)
        if match:return 'Greenhouse','roblox',match[1],f'https://boards-api.greenhouse.io/v1/boards/roblox/jobs/{match[1]}'
    if parsed.hostname in GREENHOUSE_HOSTS:
        match=re.fullmatch(rf'/({BOARD})/jobs/({JOB})/?',parsed.path)
        if match:return 'Greenhouse',match[1],match[2],f'https://boards-api.greenhouse.io/v1/boards/{match[1]}/jobs/{match[2]}'
    if parsed.hostname in MCF_HOSTS:
        match=re.fullmatch(MCF_JOB,parsed.path)
        if match:return 'MyCareersFuture',None,match[1],f'https://api.mycareersfuture.gov.sg/v2/jobs/{match[1]}'
    if parsed.hostname in LEVER_HOSTS:
        match=re.fullmatch(rf'/({BOARD})/({UUID})/?',parsed.path)
        if match:return 'Lever',match[1],match[2],f'https://{LEVER_HOSTS[parsed.hostname]}/v0/postings/{match[1]}/{match[2]}?mode=json'
    return None


def read_preview(parsed,url,deadline,fetch):
    target=mapping(parsed)
    if target is None:return None
    provider,_,job_id,api=target
    status,headers,data=fetch(api,deadline)
    if status==HTTPStatus.NOT_FOUND:raise ValueError(f'This job is no longer available on {"MyCareersFuture" if provider=="MyCareersFuture" else "the employer’s public job board"}. Paste the description or upload a document.')
    if status!=HTTPStatus.OK:raise ValueError('The public job API is unavailable. Retry, paste the description or upload a document.')
    try:
        if headers.get('content-type','').split(';')[0].strip().lower()!='application/json':raise ValueError
        job=json.loads(data)
        if not isinstance(job,dict):raise ValueError
        if provider=='Greenhouse':
            if type(job.get('id')) is not int or job['id']!=int(job_id):raise ValueError
            posting=urlsplit(job.get('absolute_url',''))
            title=job.get('title');content=job.get('content')
            if not isinstance(content,str):raise ValueError
            description=html_text(html.unescape(content))
            if parsed.hostname=='careers.roblox.com':
                if posting.hostname!=parsed.hostname or posting.path.rstrip('/')!=parsed.path.rstrip('/'):raise ValueError
            elif posting.hostname in GREENHOUSE_HOSTS:
                if posting.path.rstrip('/')!=parsed.path.rstrip('/'):raise ValueError
            # Custom employer domains are provider-published metadata, never followed.
            destination(job['absolute_url'])
            lines=[]
            if isinstance(job.get('company_name'),str):lines.append('Company: '+html_text(job['company_name']))
            location=job.get('location')
            if isinstance(location,dict) and isinstance(location.get('name'),str):lines.append('Job location: '+html_text(location['name']))
        elif provider=='MyCareersFuture':
            title,description,lines,posting=mycareersfuture_job(job,job_id)
        else:
            if job.get('id')!=job_id:raise ValueError
            posting=urlsplit(job.get('hostedUrl',''))
            if posting.hostname!=parsed.hostname or posting.path.rstrip('/')!=parsed.path.rstrip('/'):raise ValueError
            title=job.get('text')
            content=job.get('description')
            if not isinstance(content,str) or not content.strip():raise ValueError
            sections=[content]
            lists=job.get('lists',[])
            if not isinstance(lists,list) or len(lists)>MAX_LISTS:raise ValueError
            for item in lists:
                if not isinstance(item,dict) or not isinstance(item.get('text'),str) or not isinstance(item.get('content'),str):raise ValueError
                sections.extend([item['text'],item['content']])
            for key in ('additional','salaryDescription'):
                if isinstance(job.get(key),str):sections.append(job[key])
            description='\n\n'.join(filter(None,(html_text(part) for part in sections)))
            lines=[]
            categories=job.get('categories',{})
            if isinstance(categories,dict):
                for key,label in (('location','Job location'),('commitment','Employment type'),('team','Team'),('department','Department')):
                    if isinstance(categories.get(key),str):lines.append(label+': '+html_text(categories[key]))
            if isinstance(job.get('workplaceType'),str):lines.append('Work arrangement: '+html_text(job['workplaceType']))
        if (posting.scheme!='https' or posting.port not in (None,443)
            or posting.username is not None or posting.password is not None):raise ValueError
        if not isinstance(title,str) or not html_text(title).strip() or not description.strip():raise ValueError
        text=validate_text('\n\n'.join([html_text(title),*lines,description]),max_text=MAX_JD_TEXT)
    except (ValueError,TypeError,AttributeError,KeyError,RecursionError):
        raise ValueError('The public job API did not return a matching readable job description within the limits. Paste the description or upload a document.') from None
    origin='the public MyCareersFuture job API' if provider=='MyCareersFuture' else f'the employer’s public {provider} Job Board API'
    return {'kind':'url','text':text,'source_name':parsed.hostname,'source_url':url,
        'notices':[f'Retrieved from {origin}: {api}. The source link is the original job page.',
            'Check that this preview contains one complete job description.',
            'This is a temporary preview; no role or skills have been interpreted.']}


def mycareersfuture_job(job,job_id):
    """Title, description, labelled facts and listing URL; employer-hidden fields stay hidden."""
    if job.get('uuid')!=job_id:raise ValueError
    posting=urlsplit(job.get('metadata',{}).get('jobDetailsUrl',''))
    if posting.hostname not in MCF_HOSTS or not re.fullmatch(MCF_JOB,posting.path) or not posting.path.rstrip('/').endswith(job_id):raise ValueError
    content=job.get('description')
    if not isinstance(content,str) or not html_text(content).strip():raise ValueError
    hidden=job['metadata']

    def names(key,field):
        values=job.get(key)
        if not isinstance(values,list):return ''
        return '; '.join(html_text(item[field]) for item in values if isinstance(item,dict) and isinstance(item.get(field),str))

    lines=[]
    company=next((c.get('name') for c in (job.get('hiringCompany'),job.get('postedCompany')) if isinstance(c,dict) and isinstance(c.get('name'),str)),None)
    if company and not hidden.get('isHideEmployerName') and not hidden.get('isHideHiringEmployerName'):lines.append('Company: '+html_text(company))
    address=job.get('address')
    if isinstance(address,dict) and not hidden.get('isHideCompanyAddress'):
        if address.get('isOverseas') and isinstance(address.get('overseasCountry'),str):lines.append('Job location: '+html_text(address['overseasCountry']))
        elif isinstance(address.get('districts'),list):
            region=next((d.get('region') for d in address['districts'] if isinstance(d,dict) and isinstance(d.get('region'),str)),None)
            if region:lines.append(f'Job location: {html_text(region)}, Singapore')
    for key,field,label in (('employmentTypes','employmentType','Employment type'),('positionLevels','position','Position level'),
            ('flexibleWorkArrangements','flexibleWorkArrangement','Work arrangement'),('categories','category','Job category')):
        text=names(key,field)
        if text:lines.append(label+': '+text)
    years=job.get('minimumYearsExperience')
    if type(years) is int and years>=0:lines.append(f'Experience requirements: at least {years} year{"" if years==1 else "s"}')
    salary=job.get('salary')
    if isinstance(salary,dict) and not hidden.get('isHideSalary') and type(salary.get('minimum')) is int and type(salary.get('maximum')) is int:
        period=salary.get('type',{}).get('salaryType') if isinstance(salary.get('type'),dict) else None
        lines.append(f'Salary: SGD {salary["minimum"]:,}–{salary["maximum"]:,}'+(f' ({html_text(period).lower()})' if isinstance(period,str) else ''))
    skills=names('skills','skill')
    if skills:lines.append('Skills: '+skills)
    sections=[content]
    if isinstance(job.get('otherRequirements'),str):sections.append(job['otherRequirements'])
    description='\n\n'.join(filter(None,(html_text(part) for part in sections)))
    return job.get('title'),description,lines,posting

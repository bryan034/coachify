"""Read-only public ATS adapters. All API origins and path grammars are fixed."""
import html
import json
import re
from urllib.parse import urlsplit
from app.domain.documents import validate_text
from app.schemas.preview import MAX_JD_TEXT

GREENHOUSE_HOSTS={'boards.greenhouse.io','job-boards.greenhouse.io'}
LEVER_HOSTS={'jobs.lever.co':'api.lever.co','jobs.eu.lever.co':'api.eu.lever.co'}
BOARD=r'[A-Za-z0-9_-]{1,100}'
JOB=r'[1-9][0-9]{0,11}'
UUID=r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'


def mapping(parsed):
    if parsed.scheme!='https':return None
    if parsed.hostname=='careers.roblox.com':
        match=re.fullmatch(rf'/jobs/({JOB})/?',parsed.path)
        if match:return 'Greenhouse','roblox',match[1],f'https://boards-api.greenhouse.io/v1/boards/roblox/jobs/{match[1]}'
    if parsed.hostname in GREENHOUSE_HOSTS:
        match=re.fullmatch(rf'/({BOARD})/jobs/({JOB})/?',parsed.path)
        if match:return 'Greenhouse',match[1],match[2],f'https://boards-api.greenhouse.io/v1/boards/{match[1]}/jobs/{match[2]}'
    if parsed.hostname in LEVER_HOSTS:
        match=re.fullmatch(rf'/({BOARD})/({UUID})/?',parsed.path)
        if match:return 'Lever',match[1],match[2],f'https://{LEVER_HOSTS[parsed.hostname]}/v0/postings/{match[1]}/{match[2]}?mode=json'
    return None


def read_preview(parsed,url,deadline,fetch):
    from app.clients.job_url import destination,html_text
    target=mapping(parsed)
    if target is None:return None
    provider,board,job_id,api=target
    status,headers,data=fetch(api,deadline)
    if status==404:raise ValueError('This job is no longer available in the employer’s public job board. Paste the description or upload a document.')
    if status!=200:raise ValueError('The employer’s public job API is unavailable. Retry, paste the description or upload a document.')
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
        else:
            if job.get('id')!=job_id:raise ValueError
            posting=urlsplit(job.get('hostedUrl',''))
            if posting.hostname!=parsed.hostname or posting.path.rstrip('/')!=parsed.path.rstrip('/'):raise ValueError
            title=job.get('text')
            content=job.get('description')
            if not isinstance(content,str) or not content.strip():raise ValueError
            sections=[content]
            lists=job.get('lists',[])
            if not isinstance(lists,list) or len(lists)>100:raise ValueError
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
        raise ValueError('The employer’s public job API did not return a matching readable job description within the limits. Paste the description or upload a document.') from None
    return {'kind':'url','text':text,'source_name':parsed.hostname,'source_url':url,
        'notices':[f'Retrieved from the employer’s public {provider} Job Board API: {api}. The source link is the original job page.',
            'Check that this preview contains one complete job description.',
            'This is a temporary preview; no role or skills have been interpreted.']}

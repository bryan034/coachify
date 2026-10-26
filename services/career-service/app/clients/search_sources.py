"""Bounded Brave API adapter. Public scope only, no page scraping."""
import hashlib
import html
import json
import os
import re
from urllib.parse import urlsplit
import httpx
from app.repositories.goals import GoalError,now
from app.schemas.analysis import ResearchSource,BraveAnswer,AnswerClaim
from app.schemas.research import ResearchBatch


def excerpt(text):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',text or ''))).strip()[:600]

class AnswersAccessError(GoalError):
    def __init__(self):super().__init__('Brave Answers API access was denied. Set BRAVE_SEARCH_MODE=answers and use an API key with an Answers plan.',503)

# Only fixed codes/field names leave this boundary; provider prose can echo secrets or queries.
BRAVE_CODES={
    'INTERNAL':'Brave reported an internal API error. Retry shortly.',
    'QUOTA_LIMITED':'Brave API quota was reached. Check the subscription quota.',
    'RATE_LIMITED':'Brave API rate limit was reached. Wait before retrying.',
    'SUBSCRIPTION_TOKEN_INVALID':'Brave rejected the subscription token for this endpoint.',
    'SUBSCRIPTION_NOT_FOUND':'Brave found no subscription for this endpoint.',
    'RESOURCE_NOT_ALLOWED':'This Brave subscription does not allow the requested endpoint. Check Answers API access.',
    'OPTION_NOT_IN_PLAN':'A requested Brave API option is not included in this subscription.',
    'USAGE_LIMIT_EXCEEDED':'Brave subscription usage limit was exceeded.',
    'INVALID_URL':'Brave rejected a URL in the API request.',
    'CREDIT_EXHAUSTED':'Brave API credits are exhausted.',
}
BRAVE_FIELDS={'model','messages','role','content','stream','enable_citations','enable_research','max_completion_tokens','country'}

async def rejection_details(response):
    data=bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data)>16384:return ''
    try:payload=json.loads(data)
    except (ValueError,UnicodeError):return ''
    if not isinstance(payload,dict):return ''
    error=payload.get('error',{})
    if not isinstance(error,dict):return ''
    code=error.get('code')
    if isinstance(code,str) and code in BRAVE_CODES:
        return f' Brave code: {code}. {BRAVE_CODES[code]}'
    # Pydantic-style validation locations are safe only after selecting known field names.
    meta=error.get('meta');fields=set()
    if isinstance(meta,dict) and isinstance(meta.get('errors'),list):
        for item in meta['errors'][:20]:
            if not isinstance(item,dict) or not isinstance(item.get('loc'),list):continue
            fields.update(v for v in item['loc'] if isinstance(v,str) and v in BRAVE_FIELDS)
    return ' Rejected fields: '+', '.join(sorted(fields))+'.' if fields else ''

async def body(client,method,url,**kwargs):
    try:
        async with client.stream(method,url,timeout=kwargs.pop('timeout',15),follow_redirects=False,**kwargs) as response:
            if response.status_code in (401,403):
                if url.endswith('/chat/completions'):raise AnswersAccessError()
                raise GoalError('Brave Search API credentials or access need checking.',503)
            if response.status_code!=200:
                status=response.status_code
                if status==402:message='Brave API quota or billing access is exhausted (HTTP 402). Check the plan for this API key.'
                elif status==429:message='Brave API rate limit reached (HTTP 429). Wait before retrying interview research.'
                elif status in (400,422):message=f'Brave rejected the research request (HTTP {status}). Check the API integration and request parameters.'
                elif status>=500:message=f'Brave API is temporarily unavailable (HTTP {status}). Retry shortly.'
                else:message=f'Brave research request failed (HTTP {status}). Check endpoint access.'
                message+=await rejection_details(response)
                raise GoalError(message,503)
            data=bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data)>256*1024:raise GoalError('The source API response exceeded its limit.',503)
            return bytes(data)
    except httpx.TimeoutException:raise GoalError('Brave API timed out. Retry interview research shortly.',503) from None
    except httpx.HTTPError:raise GoalError('Could not connect to Brave API. Check the server network connection and retry.',503) from None
    except ValueError:raise GoalError('Brave returned an unreadable response. Retry interview research.',503) from None

class SourceAPIs:
    def __init__(self,client,*,brave_key='',brave_mode='answers'):
        if brave_mode not in ('search','answers'):raise ValueError('BRAVE_SEARCH_MODE must be search or answers.')
        self.client,self.brave_key,self.brave_mode=client,brave_key,brave_mode

    @classmethod
    def from_environment(cls,client):
        return cls(client,brave_key=os.getenv('BRAVE_API_KEY',''),brave_mode=os.getenv('BRAVE_SEARCH_MODE','answers'))

    @property
    def cache_policy(self):return 'public-interview-brave-process-v4:'+self.brave_mode

    def query(self,context,round):
        if self.brave_mode=='answers':
            role=' '.join(v for v in (context.seniority_level,context.role) if v)
            scope=f"{role} at {context.company}" if context.company and not round else f"{role} roles in {context.field}"
            location=f" in {context.location}" if context.location else ''
            return (f"What interview stages, assessments, technical and transferable skills, and question patterns are reported for {scope}{location}? "
                "Distinguish official employer guidance from candidate reports and general role guidance. Cite sources for each finding; identify missing or uncertain details. Do not infer hiring requirements from the job title.")
        fields=[context.role,context.field] if round else [context.company,context.role,context.location,context.seniority_level]
        return ' '.join(v for v in fields if v)[:420]+' interview stages assessments skills'

    async def collect_platform(self,context,platform,round=0):
        query=self.query(context,round)
        if platform=='brave':return await self.brave(query,country='SG' if (context.location or '').strip().casefold() in ('singapore','sg') else 'ALL')
        raise GoalError('Unsupported research platform.',422)

    async def collect(self,context):
        return await self.collect_platform(context,'brave')

    async def brave(self,query,*,country='ALL'):
        if not self.brave_key:raise GoalError('The running career service has no Brave API key. After configuring BRAVE_API_KEY, recreate the career-service container and retry.',503)
        headers={'X-Subscription-Token':self.brave_key,'Accept':'application/json'}
        if self.brave_mode=='search':
            raw=await body(self.client,'GET','https://api.search.brave.com/res/v1/web/search',headers=headers,
                params={'q':query,'count':3,'extra_snippets':'true'})
            try:results=json.loads(raw).get('web',{}).get('results',[])[:3]
            except (ValueError,AttributeError,TypeError):raise GoalError('Brave returned invalid search data.',503) from None
            return [self.source('brave',v['url'],v.get('title'),excerpt(v.get('description',''))) for v in results if isinstance(v,dict) and isinstance(v.get('url'),str) and v.get('description')]
        # Answers citations require streaming. Accumulate bounded SSE fragments;
        # retain the AI answer separately from source excerpts with citation offsets.
        raw=await body(self.client,'POST','https://api.search.brave.com/res/v1/chat/completions',headers={**headers,'Accept':'text/event-stream'},timeout=35,
            json={'model':'brave','messages':[{'role':'user','content':query}], 'stream':True,'enable_citations':True,'enable_research':False,'max_completion_tokens':1536,'country':country})
        text='';done=False;finished=False
        try:
            for line in raw.decode().splitlines():
                if not line.startswith('data:'):continue
                data=line[5:].lstrip()
                if data=='[DONE]':done=True;continue
                item=json.loads(data)
                if item.get('error'):raise ValueError('Answer stream error')
                choices=item.get('choices') or []
                if choices:
                    if choices[0].get('finish_reason')=='stop':finished=True
                    if choices[0].get('finish_reason') in ('length','content_filter'):raise ValueError('Incomplete answer')
                    text+=choices[0].get('delta',{}).get('content') or ''
            if not (done or finished):raise ValueError('Incomplete stream')
            citations=[json.loads(v) for v in re.findall(r'<citation>(.*?)</citation>',text,re.S)]
            plain=re.sub(r'<(?:citation|usage|entity)>.*?</(?:citation|usage|entity)>','',text,flags=re.S)
            if re.search(r'</?(?:citation|usage|entity)>',plain):raise ValueError('Incomplete metadata')
            # Offsets refer to the answer's original text, before trimming/normalization.
            sources=[];seen=set();links=[]
            for item in citations:
                if not isinstance(item,dict) or not isinstance(item.get('url'),str) or not isinstance(item.get('snippet'),str):continue
                url=item['url']
                if url not in seen:
                    if len(sources)>=6:continue
                    sources.append(self.source('brave',url,None,excerpt(item['snippet'])));seen.add(url)
                source=next(v for v in sources if v.url==url)
                start,end=item.get('start_index'),item.get('end_index')
                if type(start) is int and type(end) is int and 0<=start<end<=min(len(plain),2400) and end-start<=600:
                    links.append((start,end,source.source_id))
            summaries=[]
            answer=plain[:2400]
            if answer.strip() and sources:
                claims=[]
                for start,end in dict.fromkeys((a,b) for a,b,_ in links):
                    claim=answer[start:end]
                    if not claim.strip() or len(claims)>=4:continue
                    claims.append(AnswerClaim(text=claim,source_ids=list(dict.fromkeys(s for a,b,s in links if a==start and b==end))))
                summaries=[BraveAnswer(summary_id='brave-answer-'+hashlib.sha256((query+answer).encode()).hexdigest()[:16],
                    text=answer,source_ids=[s.source_id for s in sources],claims=claims)]
            return ResearchBatch(sources=sources,summaries=summaries)
        except (ValueError,TypeError,KeyError,AttributeError):raise GoalError('Brave returned invalid or incomplete answer/citation data.',503) from None

    @staticmethod
    def source(provider,url,title,evidence,published_date=None):
        return ResearchSource(source_id=provider+'-'+hashlib.sha256(url.encode()).hexdigest()[:16],platform='reddit' if (urlsplit(url).hostname or '').lower() in ('reddit.com','www.reddit.com','old.reddit.com') else 'other',
            url=url,title=excerpt(title)[:160] or None,evidence=evidence,published_date=published_date,reliability='anecdotal' if (urlsplit(url).hostname or '').lower() in ('reddit.com','www.reddit.com','old.reddit.com') else 'unverified',
            role_match='unknown',report_group=None,retrieved_at=now())

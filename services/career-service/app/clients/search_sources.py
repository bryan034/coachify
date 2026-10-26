"""Bounded Brave API adapter. Public scope only, no page scraping."""
import hashlib
import html
import json
import math
import os
import re
from urllib.parse import urlsplit
import httpx
from pydantic import ValidationError
from app.repositories.goals import GoalError,now
from app.schemas.analysis import ResearchSource,BraveAnswer,AnswerClaim
from app.schemas.research import ResearchBatch


def excerpt(text):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',text or ''))).strip()[:600]

def search_results(payload):
    """Read Brave's Search envelope, including compatible direct-results responses."""
    if not isinstance(payload,dict):raise GoalError('Brave returned invalid search data.',503)
    web=payload.get('web')
    results=web.get('results') if isinstance(web,dict) else payload.get('results')
    if not isinstance(results,list):raise GoalError('Brave returned invalid search data.',503)
    return results

INTERVIEW_TERMS=re.compile(r'\b(?:interview|rounds?|stages?|assessments?|coding|technical|behavio[u]?ral|case study|screening)\b',re.I)


def interview_excerpt(value,terms=INTERVIEW_TERMS):
    # Rank windows before truncation: LLM Context passages often start with navigation.
    text=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',value))).strip()
    if len(text)<=600:return text
    starts={0}
    for match in terms.finditer(text):
        # Keep the sentence prefix when possible so employer/role context survives.
        boundary=max(text.rfind('. ',0,match.start()),text.rfind('! ',0,match.start()),text.rfind('? ',0,match.start()))
        start=boundary+2 if boundary>=0 and match.start()-boundary<160 else max(0,match.start()-100)
        starts.add(min(start,max(0,len(text)-600)))
    start=max(sorted(starts),key=lambda start:len(terms.findall(text[start:start+600])))
    return text[start:start+600]


def search_evidence(result,focus=None):
    """Prefer interview-bearing excerpts; never ask a model to clean search results."""
    terms=INTERVIEW_TERMS
    if focus:
        words=[w for w in re.findall(r'[a-z]{3,}',focus.casefold()) if w not in {'the','and','for','with','what','are','does','company','singapore'}]
        if words:terms=re.compile(r'\b(?:'+'|'.join(map(re.escape,words))+r')\b',re.I)
    extra=result.get('extra_snippets',[])
    if isinstance(extra,str):extra=[extra]
    values=[result.get('description') or result.get('snippet')]
    if isinstance(extra,list):
        values.extend(item if isinstance(item,str) else item.get('snippet') or item.get('text')
            if isinstance(item,dict) else None for item in extra[:5])
    snippets=[];seen=set()
    for value in values:
        if not isinstance(value,str):continue
        text=interview_excerpt(value,terms);key=text.casefold()
        if text and key not in seen:snippets.append(text);seen.add(key)
    snippets.sort(key=lambda text:len(terms.findall(text)),reverse=True)
    selected=[];remaining=600
    for text in snippets:
        # A full excerpt leaves -1 after reserving the separator. Never slice with
        # a negative budget: text[:-1] would append nearly the whole next snippet.
        if remaining<=0:break
        # Skip repeated/subsumed snippets instead of paying for the same claim twice.
        if any(text.casefold() in old.casefold() for old in selected):continue
        piece=text[:remaining]
        if not piece:break
        selected.append(piece);remaining-=len(piece)+1
    return '\n'.join(selected)

# Supported Search country enum; Singapore must remain in q with country=ALL.
SEARCH_COUNTRIES=frozenset('AR AU AT BE BR CA CL DK FI FR DE GR HK IN ID IT JP KR MY MX NL NZ NO CN PL PT PH RU SA ZA ES SE CH TW TR GB US ALL'.split())


def search_country(location):
    return 'SG' if re.search(r'\b(?:singapore|sg)\b',(location or '').casefold()) else 'ALL'

def error_excerpt(text):
    """Recognise standalone provider failures, not interview discussion of API keys."""
    value=' '.join((text or '').casefold().split()).strip(" .\"'`")
    if len(value)<=600 and value.startswith('{'):
        try:
            error=json.loads(value)
            if isinstance(error,dict):
                value=next((error[k] for k in ('error','message','detail') if isinstance(error.get(k),str)),value)
                value=' '.join(value.split()).strip(" .\"'`")
        except ValueError:pass
    return bool(re.fullmatch(r'(?:error[: ]+)?(?:(?:api |subscription )?key (?:is )?(?:not specified|not provided|missing|invalid)|missing (?:api |subscription )?key|unauthori[sz]ed|authentication failed|access denied|no results found)',value))


def context_results(payload):
    if not isinstance(payload,dict) or payload.get('error') or payload.get('type')=='ErrorResponse':
        raise GoalError('Brave LLM Context returned an error instead of research results.',503)
    grounding=payload.get('grounding')
    if not isinstance(grounding,dict) or not isinstance(grounding.get('generic'),list):
        raise GoalError('Brave LLM Context did not return valid grounding data.',503)
    metadata=payload.get('sources',{})
    metadata=metadata if isinstance(metadata,dict) else {}
    groups={}
    for item in grounding['generic'][:50]:
        if not isinstance(item,dict) or not isinstance(item.get('url'),str) or not isinstance(item.get('snippets'),list):continue
        snippets=[v for v in item['snippets'][:20] if isinstance(v,str) and v.strip() and not error_excerpt(v)]
        if not snippets:continue
        url=item['url'];meta=metadata.get(url,{})
        meta=meta if isinstance(meta,dict) else {}
        if url not in groups:groups[url]={'url':url,'title':item.get('title') or meta.get('title'),'extra_snippets':[]}
        groups[url]['extra_snippets'].extend(snippets)
    return list(groups.values())


class SourceRateLimit(GoalError):
    def __init__(self,retry_after):
        try:delay=float(retry_after)
        except (TypeError,ValueError):delay=30
        self.retry_after=max(1,min(3600,int(delay))) if math.isfinite(delay) else 30
        super().__init__('Brave API rate limit reached (HTTP 429). Wait before retrying interview research.',503)

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
BRAVE_FIELDS={'model','messages','role','content','stream','enable_citations','enable_research','max_completion_tokens','country','q','count','extra_snippets','text_decorations','maximum_number_of_urls','maximum_number_of_tokens','maximum_number_of_tokens_per_url','maximum_number_of_snippets','maximum_number_of_snippets_per_url','context_threshold_mode','enable_local'}

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
            if response.status_code==429:raise SourceRateLimit(response.headers.get('retry-after'))
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
    def __init__(self,client,*,brave_key='',brave_mode='llm_context'):
        if brave_mode not in ('llm_context','search','answers'):raise ValueError('BRAVE_SEARCH_MODE must be llm_context, search or answers.')
        self.client,self.brave_key,self.brave_mode=client,brave_key,brave_mode

    @classmethod
    def from_environment(cls,client):
        return cls(client,brave_key=os.getenv('BRAVE_API_KEY',''),brave_mode=os.getenv('BRAVE_SEARCH_MODE','llm_context'))

    @property
    def cache_policy(self):return 'public-interview-brave-process-v8:'+self.brave_mode

    @property
    def configured(self):return bool(self.brave_key.strip())

    def for_opportunity(self):
        # The new graph always uses LLM Context; legacy interview mode is separate.
        return SourceAPIs(self.client,brave_key=self.brave_key,brave_mode='llm_context')

    def query(self,context,round):
        if self.brave_mode=='answers':
            role=' '.join(v for v in (context.seniority_level,context.role) if v)
            scope=f"{role} at {context.company}" if context.company and not round else f"{role} roles in {context.field}"
            location=f" in {context.location}" if context.location else ''
            return (f"What interview stages, assessments, technical and transferable skills, and question patterns are reported for {scope}{location}? "
                "Distinguish official employer guidance from candidate reports and general role guidance. Cite sources for each finding; identify missing or uncertain details. Do not infer hiring requirements from the job title.")
        fields=[context.company,context.role,context.location,context.field] if round else [context.company,context.role,context.location,context.seniority_level]
        return ' '.join(v for v in fields if v)[:420]+' interview stages assessments skills'

    async def collect_platform(self,context,platform,round=0):
        query=self.query(context,round)
        if platform=='brave':return await self.brave(query,country=search_country(context.location))
        raise GoalError('Unsupported research platform.',422)

    async def collect(self,context):
        return await self.collect_platform(context,'brave')

    async def collect_query(self,context,query):
        # The model supplies text only; endpoint, credentials and result budget stay fixed.
        return await self.brave(query,country=search_country(context.location),count=5)

    async def collect_opportunity_query(self,context,query):
        if self.brave_mode!='llm_context':raise GoalError('Opportunity Intelligence requires Brave LLM Context mode.',503)
        return await self.brave(query,country=search_country(context.location),count=5,focus=query)

    async def brave(self,query,*,country='ALL',count=3,focus=None):
        if not self.brave_key:raise GoalError('The running career service has no Brave API key. After configuring BRAVE_API_KEY, recreate the career-service container and retry.',503)
        headers={'X-Subscription-Token':self.brave_key,'Accept':'application/json'}
        if self.brave_mode=='llm_context':
            country=country if country in SEARCH_COUNTRIES else 'ALL'
            raw=await body(self.client,'GET','https://api.search.brave.com/res/v1/llm/context',headers=headers,timeout=30,
                params={'q':query,'country':country,'count':20,'maximum_number_of_urls':5,
                    'maximum_number_of_tokens':2048,'maximum_number_of_tokens_per_url':512,
                    'maximum_number_of_snippets':10,'maximum_number_of_snippets_per_url':2,
                    'context_threshold_mode':'balanced','enable_local':'false'})
            try:results=context_results(json.loads(raw))
            except (ValueError,UnicodeError,TypeError):raise GoalError('Brave returned invalid LLM context data.',503) from None
            sources=[]
            for value in results:
                evidence=search_evidence(value,focus)
                if not evidence or error_excerpt(evidence):continue
                try:source=self.source('brave',value['url'],value.get('title') if isinstance(value.get('title'),str) else None,evidence)
                except (ValidationError,ValueError):continue
                # URL safety and canonicalisation apply before this can count as a result.
                from app.clients.research import normalize_sources
                try:sources.extend(normalize_sources([source]))
                except GoalError:continue
                if len(sources)>=5:break
            return sources
        if self.brave_mode=='search':
            country=country if country in SEARCH_COUNTRIES else 'ALL'
            raw=await body(self.client,'GET','https://api.search.brave.com/res/v1/web/search',headers=headers,
                params={'q':query,'count':count,'extra_snippets':'true','text_decorations':'false','country':country})
            try:
                results=search_results(json.loads(raw))
            except (ValueError,UnicodeError,TypeError):raise GoalError('Brave returned invalid search data.',503) from None
            sources=[];seen=set();invalid=0
            for value in results[:count]:
                if not isinstance(value,dict) or not isinstance(value.get('url'),str):
                    invalid+=1
                    continue
                if value['url'] in seen:continue
                evidence=search_evidence(value,focus)
                if not evidence:continue
                try:source=self.source('brave',value['url'],value.get('title') if isinstance(value.get('title'),str) else None,evidence)
                except (ValidationError,ValueError):invalid+=1;continue
                seen.add(value['url'])
                sources.append(source)
            if results and not sources and invalid:
                raise GoalError('Brave Search returned results, but their URLs or fields were not usable.',503)
            return sources
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

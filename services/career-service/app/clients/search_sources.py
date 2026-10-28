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
from app.schemas.analysis import ResearchSource


OPPORTUNITY_SOURCE_LIMIT=3
OPPORTUNITY_EXCERPT_LIMIT=8000

def excerpt(text):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',text or ''))).strip()[:600]

INTERVIEW_TERMS=re.compile(r'\b(?:interview|rounds?|stages?|assessments?|coding|technical|behavio[u]?ral|case study|screening)\b',re.I)


def interview_excerpt(value,terms=INTERVIEW_TERMS,budget=600):
    # Rank windows before truncation: LLM Context passages often start with navigation.
    text=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',value))).strip()
    if len(text)<=budget:return text
    starts={0}
    for match in terms.finditer(text):
        # Keep the sentence prefix when possible so employer/role context survives.
        boundary=max(text.rfind('. ',0,match.start()),text.rfind('! ',0,match.start()),text.rfind('? ',0,match.start()))
        start=boundary+2 if boundary>=0 and match.start()-boundary<160 else max(0,match.start()-100)
        starts.add(min(start,max(0,len(text)-budget)))
    start=max(sorted(starts),key=lambda start:len(terms.findall(text[start:start+budget])))
    return text[start:start+budget]


def search_evidence(result,focus=None,*,budget=600):
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
            if isinstance(item,dict) else None for item in extra[:30])
    snippets=[];seen=set()
    for value in values:
        if not isinstance(value,str):continue
        text=interview_excerpt(value,terms,budget);key=text.casefold()
        if text and key not in seen:snippets.append(text);seen.add(key)
    snippets.sort(key=lambda text:len(terms.findall(text)),reverse=True)
    selected=[];remaining=budget
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

# Only fixed codes/field names leave this boundary; provider prose can echo secrets or queries.
BRAVE_CODES={
    'INTERNAL':'Brave reported an internal API error. Retry shortly.',
    'QUOTA_LIMITED':'Brave API quota was reached. Check the subscription quota.',
    'RATE_LIMITED':'Brave API rate limit was reached. Wait before retrying.',
    'SUBSCRIPTION_TOKEN_INVALID':'Brave rejected the subscription token for this endpoint.',
    'SUBSCRIPTION_NOT_FOUND':'Brave found no subscription for this endpoint.',
    'RESOURCE_NOT_ALLOWED':'This Brave subscription does not allow the requested endpoint. Check LLM Context API access.',
    'OPTION_NOT_IN_PLAN':'A requested Brave API option is not included in this subscription.',
    'USAGE_LIMIT_EXCEEDED':'Brave subscription usage limit was exceeded.',
    'INVALID_URL':'Brave rejected a URL in the API request.',
    'CREDIT_EXHAUSTED':'Brave API credits are exhausted.',
}
BRAVE_FIELDS={'model','messages','role','content','stream','enable_citations','enable_research','max_completion_tokens','country','q','count','extra_snippets','text_decorations','maximum_number_of_urls','maximum_number_of_tokens','maximum_number_of_tokens_per_url','maximum_number_of_snippets','maximum_number_of_snippets_per_url','context_threshold_mode','enable_local','search_lang','operators','operators_fallback','spellcheck','enable_source_metadata'}

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
                raise GoalError('Brave LLM Context API credentials or access need checking.',503)
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
        # Accept the legacy argument so existing callers migrate without an outage.
        # Every retrieval now uses LLM Context, irrespective of old mode settings.
        self.client,self.brave_key,self.brave_mode=client,brave_key,'llm_context'

    @classmethod
    def from_environment(cls,client):
        return cls(client,brave_key=os.getenv('BRAVE_API_KEY',''))

    @property
    def cache_policy(self):return 'public-interview-brave-context-v9:'+self.brave_mode

    @property
    def configured(self):return bool(self.brave_key.strip())

    def for_opportunity(self):
        # All research workflows share the same LLM Context adapter.
        return SourceAPIs(self.client,brave_key=self.brave_key,brave_mode='llm_context')

    def query(self,context,round):
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
        return await self.brave(query,country=search_country(context.location))

    async def collect_opportunity_query(self,context,query):
        if self.brave_mode!='llm_context':raise GoalError('Opportunity Intelligence requires Brave LLM Context mode.',503)
        return await self.brave(query,country=search_country(context.location),focus=query,max_sources=OPPORTUNITY_SOURCE_LIMIT,evidence_chars=OPPORTUNITY_EXCERPT_LIMIT)

    async def brave(self,query,*,country='ALL',focus=None,max_sources=6,evidence_chars=2400):
        if not self.brave_key:raise GoalError('The running career service has no Brave API key. After configuring BRAVE_API_KEY, recreate the career-service container and retry.',503)
        headers={'X-Subscription-Token':self.brave_key,'Accept':'application/json'}
        country=country if country in SEARCH_COUNTRIES else 'ALL'
        raw=await body(self.client,'GET','https://api.search.brave.com/res/v1/llm/context',headers=headers,timeout=30,
            params={'q':query,'country':country,'count':30,'maximum_number_of_urls':max_sources,
                'maximum_number_of_tokens':8192,'maximum_number_of_tokens_per_url':2048,
                'maximum_number_of_snippets':30,'maximum_number_of_snippets_per_url':6,
                'context_threshold_mode':'balanced','enable_local':'false',
                'search_lang':'en','operators':'true','operators_fallback':'false',
                'spellcheck':'false','enable_source_metadata':'true'})
        try:results=context_results(json.loads(raw))
        except (ValueError,UnicodeError,TypeError):raise GoalError('Brave returned invalid LLM context data.',503) from None
        sources=[]
        for value in results:
            evidence=search_evidence(value,focus,budget=evidence_chars)
            if not evidence or error_excerpt(evidence):continue
            try:source=self.source('brave',value['url'],value.get('title') if isinstance(value.get('title'),str) else None,evidence)
            except (ValidationError,ValueError):continue
            # URL safety and canonicalisation apply before this can count as a result.
            from app.clients.research import normalize_sources
            try:sources.extend(normalize_sources([source]))
            except GoalError:continue
            if len(sources)>=max_sources:break
        return sources

    @staticmethod
    def source(provider,url,title,evidence,published_date=None):
        return ResearchSource(source_id=provider+'-'+hashlib.sha256(url.encode()).hexdigest()[:16],platform='reddit' if (urlsplit(url).hostname or '').lower() in ('reddit.com','www.reddit.com','old.reddit.com') else 'other',
            url=url,title=excerpt(title)[:160] or None,evidence=evidence,published_date=published_date,reliability='anecdotal' if (urlsplit(url).hostname or '').lower() in ('reddit.com','www.reddit.com','old.reddit.com') else 'unverified',
            role_match='unknown',report_group=None,retrieved_at=now())

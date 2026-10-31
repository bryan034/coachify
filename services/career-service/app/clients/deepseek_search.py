"""DeepSeek Search API adapter; only returned page content becomes evidence."""
import json
from datetime import date
import httpx
from pydantic import ValidationError
from app.clients.search_sources import SourceAPIs,SourceRateLimit,search_evidence,error_excerpt,discovery_employer
from app.clients.research import normalize_sources
from app.repositories.goals import GoalError


class DeepSeekSearch(SourceAPIs):
    provider='deepseek'

    def __init__(self,client,*,api_key=''):
        self.client,self.api_key=client,api_key

    @property
    def configured(self):return bool(self.api_key.strip())

    @property
    def cache_policy(self):return 'public-deepseek-search-content-v1'

    async def search(self,query,*,max_sources=6,evidence_chars=2400,focus=None,discovery=False,**kwargs):
        if not self.configured:raise GoalError('Configure CAREER_RESEARCH_API_KEY for DeepSeek Search and recreate Career.',503)
        query=' '.join(query.split())
        # The documented API limit is 128 Unicode characters. Preserve both the
        # public role/employer prefix and the specific research focus suffix.
        if len(query)>128:query=query[:79].rsplit(' ',1)[0]+' '+query[-48:].split(' ',1)[-1]
        if not query:raise GoalError('The public research query is empty.',422)
        try:
            async with self.client.stream('POST','https://api.deepseek.com/v1/tools/search',
                headers={'Authorization':'Bearer '+self.api_key,'Content-Type':'application/json'},
                json={'query':query,'count':max_sources,'need_content':True},
                timeout=30,follow_redirects=False) as response:
                if response.status_code==429:raise SourceRateLimit(response.headers.get('retry-after'),self.provider)
                if response.status_code in (401,403):raise GoalError('DeepSeek Search credentials or access need checking.',503)
                if response.status_code!=200:raise GoalError(f'DeepSeek Search request failed (HTTP {response.status_code}). Check API access and retry.',503)
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>256*1024:raise GoalError('The search API response exceeded its limit.',503)
            payload=json.loads(data)
            if not isinstance(payload,dict) or payload.get('error') or not isinstance(payload.get('results'),list):
                raise ValueError
        except httpx.TimeoutException:raise GoalError('DeepSeek Search timed out. Retry research shortly.',503) from None
        except httpx.HTTPError:raise GoalError('Could not connect to DeepSeek Search. Retry research shortly.',503) from None
        except (ValueError,UnicodeError):raise GoalError('DeepSeek Search returned invalid results.',503) from None
        sources=[]
        for item in payload['results'][:50]:
            if not isinstance(item,dict) or not isinstance(item.get('url'),str):continue
            content=item.get('content')
            # Search summaries/snippets are generated summaries, not original
            # page quotes. Missing content stays missing; never relabel it.
            if not isinstance(content,str) or not content.strip() or error_excerpt(content):continue
            evidence=search_evidence({'description':content},focus,budget=evidence_chars)
            title=item.get('title') if isinstance(item.get('title'),str) else None
            published=None
            try:published=date.fromisoformat(item['date'][:10])
            except (KeyError,TypeError,ValueError):pass
            try:
                source=normalize_sources([self.source(self.provider,item['url'],title,evidence,published)])[0]
                if discovery:
                    from app.schemas.discovery import DiscoverySource
                    source=DiscoverySource(**source.model_dump(),company=discovery_employer([content]))
            except (ValidationError,ValueError,GoalError):continue
            if source.url in {old.url for old in sources}:continue
            sources.append(source)
            if len(sources)>=max_sources:break
        return sources

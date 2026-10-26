"""API-source extension point. No built-in search, scraping or user-entered URLs."""
import hashlib
import ipaddress
import re
from typing import Protocol
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from pydantic import ValidationError
from app.repositories.goals import GoalError,now
from app.schemas.analysis import ResearchContext,ResearchSource
from app.schemas.research import ResearchBatch

class ResearchProvider(Protocol):
    async def collect(self,context:ResearchContext)->list[ResearchSource]|ResearchBatch:
        """Fetch permitted public API evidence for this context, or raise GoalError.

        Adapters must respect API access/licensing rules, avoid private context,
        verify provenance/reliability and assign report_group only when common
        report origin/independence is established. Provider summaries stay labelled as AI synthesis, separate from source excerpts.
        """
        ...

class UnavailableResearchProvider:
    async def collect(self,context):
        raise GoalError('Interview research source APIs are not connected yet. Saved research is still available.',503)


def normalize_sources(values):
    """Validate bounded connector output, canonical links and duplicate excerpts."""
    if not isinstance(values,list) or len(values)>6:
        raise GoalError('The research API returned an invalid source batch.',503)
    sources=[];seen=set();identities=set()
    for value in values:
        try:
            source=ResearchSource.model_validate(value)
            p=urlsplit(source.url);host=p.hostname or ''
            if p.port not in (None,80,443) or host in ('localhost','metadata.google.internal') or host.endswith(('.local','.localhost','.internal')):
                raise ValueError
            try:
                if not ipaddress.ip_address(host).is_global:raise ValueError
            except ValueError:
                # Hostnames are citation links, not destinations fetched by this service.
                if re.fullmatch(r'[0-9.:]+',host) or ':' in host:raise
            query=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
            if any(re.search(r'token|password|api.?key|email|signature|auth',k,re.I) for k,_ in query):raise ValueError
            url=urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urlencode(sorted(query)),''))
            if source.source_id in identities:raise ValueError
            identities.add(source.source_id)
            digest=hashlib.sha256(re.sub(r'\W+',' ',(source.evidence or '').casefold()).encode()).hexdigest()
            if not source.evidence or url in seen or digest in seen:continue
            seen.update((url,digest))
            source.url=url
            source.retrieved_at=source.retrieved_at or now()
            sources.append(source)
        except (ValidationError,ValueError):
            raise GoalError('The research API returned invalid or unsafe public evidence.',503) from None
    if values and not sources:raise GoalError('No usable public evidence was returned by the source API.',503)
    return sources


def normalize_batch(value):
    """Keep provider summaries separate from original source excerpts."""
    from app.schemas.research import ResearchBatch
    if isinstance(value,list):return ResearchBatch(sources=normalize_sources(value))
    batch=ResearchBatch.model_validate(value)
    sources=normalize_sources(batch.sources);ids={s.source_id for s in sources};summaries=[]
    for summary in batch.summaries:
        if not set(summary.source_ids)<={v.source_id for v in batch.sources} or any(c.text not in summary.text or not set(c.source_ids)<=set(summary.source_ids) for c in summary.claims):
            raise GoalError('The research API returned invalid summary attribution.',503)
        keep=[v for v in summary.source_ids if v in ids]
        if not keep:continue
        claims=[c.model_copy(update={'source_ids':[v for v in c.source_ids if v in ids]}) for c in summary.claims if any(v in ids for v in c.source_ids)]
        summaries.append(summary.model_copy(update={'source_ids':keep,'claims':claims}))
    return ResearchBatch(sources=sources,summaries=summaries)

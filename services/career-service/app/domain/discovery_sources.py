"""Discovery-only candidate filtering, provenance and diverse source selection."""
import hashlib
import re
from collections import defaultdict
from urllib.parse import urlsplit, parse_qs
from app.clients.research import normalize_sources
from app.ai.adapter import AIError
from app.schemas.discovery import DiscoverySource

POLICY = 'discovery-listings-v4-semantic-evidence'


def excluded_kind(source):
    """Known index/template shapes cannot become individual-vacancy evidence."""
    url=urlsplit(source.url);path=url.path.casefold();title=(source.title or '').casefold()
    if any(term in path for term in ('/job-descriptions/','/job-search/position-overview/')):
        return 'career_advice'
    if ('srch_' in path or re.search(r'/q-[^/]*jobs(?:\.html)?$',path)
        or re.search(r'/(?:jobs?|careers)/(?:search|categories?)(?:/|$)',path)
        or path.rstrip('/') in ('/jobs','/job-search','/search/jobs')
        or parse_qs(url.query).get('q') and re.search(r'/(?:jobs?|search)/?$',path)
        or re.match(r'^[\d,]+\s+.+\bjobs\b',title)
        or re.search(r'\bjobs,?\s+(?:employment|work)\b',title)):
        return 'index'
    return None


def candidates(values):
    """Keep all bounded query candidates, with stable IDs and safe public URLs."""
    result={}
    for raw in values:
        company=raw.get('company')
        source=normalize_sources([{k:v for k,v in raw.items() if k!='company'}])[0]
        source=DiscoverySource(**source.model_dump(),company=company)
        source.source_id='op-'+hashlib.sha256(source.url.encode()).hexdigest()[:24]
        if source.url not in result:result[source.url]=source
        # Preserve evidence already used by completed extractions on a repeated URL.
    return list(result.values())


def validate_assessments(output,sources):
    if sorted(item.ref for item in output.sources)!=list(range(len(sources))):
        raise AIError('invalid_output',reason='assessment_references')
    result={}
    for item in output.sources:
        source=sources[item.ref]
        value=item.model_dump(mode='json')
        # Gemini owns semantic relevance/faithful paraphrasing; Python does not
        # impose a kind taxonomy, compare employer names, or require verbatim text.
        if excluded_kind(source):value.update(relevant=False)
        value['company']=getattr(source,'company',None)
        result[source.source_id]=value
    return result


def ranked_sources(sources,assessments,evaluated,listings,limit):
    """Relevance within employer groups, then one per employer before repeats."""
    known={v['source_id']:v for v in listings}
    groups=defaultdict(list)
    for source in sources:
        assessment=assessments.get(source.source_id,{})
        if not assessment.get('relevant') or excluded_kind(source):continue
        if source.source_id in evaluated and source.source_id not in known:continue
        company=' '.join((known.get(source.source_id,{}).get('company') or assessment.get('company') or '').casefold().split())
        group=company or urlsplit(source.url).hostname
        groups[group].append(source)
    def score(source):return (-assessments[source.source_id]['score'],source.url)
    for group in groups.values():group.sort(key=score)
    ordered=sorted(groups.values(),key=lambda group:score(group[0]));selected=[]
    while ordered and len(selected)<limit:
        remaining=[]
        for group in ordered:
            if len(selected)>=limit:break
            selected.append(group.pop(0))
            if group:remaining.append(group)
        ordered=remaining
    return selected

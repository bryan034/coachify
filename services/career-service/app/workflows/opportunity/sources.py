"""Bounded canonical source pooling across independently retrieved categories."""
import hashlib
from app.clients.research import normalize_sources
from app.clients.search_sources import OPPORTUNITY_EXCERPT_LIMIT
from app.ai.opportunity_contracts import evidence_passages
from app.schemas.opportunity import FIELDS,MAX_RESEARCH_SOURCES
from .topics import policy,site

def pool(values):
    result={}
    for raw in values:
        source=normalize_sources([raw])[0]
        source.source_id='op-'+hashlib.sha256(source.url.encode()).hexdigest()[:24]
        if source.url in result:
            previous=result[source.url]
            if source.evidence and source.evidence not in (previous.evidence or ''):
                previous.evidence=((previous.evidence or '')+'\n'+source.evidence)[:OPPORTUNITY_EXCERPT_LIMIT]
        else:result[source.url]=source
    return list(result.values())[:MAX_RESEARCH_SOURCES]


# Pages kept for a category with no supported finding, so "not found" still shows what was checked.
CHECKED_SOURCE_LIMIT=3


def retain_useful(category,findings,sources,relevant_ids=()):
    """Keep each topic's best sources up to its policy, preferring distinct sites.

    A finding keeps only its citations from kept sources and is dropped when none remain.
    Each kept source stores only the passages its kept findings cite.
    """
    by_id={s.source_id:s for s in sources}
    ranks={'insufficient_evidence':0,'low':1,'medium':2,'high':3}
    preferred='candidate_reported' if category in ('interview_intelligence','internship_insights','company_intelligence') else 'official'
    kept=[]
    for topic in FIELDS[category]:
        own=[f for f in findings if f.field==topic]
        def score(sid):
            cited=[f for f in own if sid in f.source_ids]
            return (sum(f.scope=='exact' for f in cited),sum(ranks[f.confidence] for f in cited),
                sum(f.evidence_type==preferred for f in cited),by_id[sid].reliability=='official',len(cited))
        candidates=sorted(dict.fromkeys(sid for f in own for sid in f.source_ids if sid in by_id),key=score,reverse=True)
        chosen=[];sites=set()
        for sid in candidates:
            if site(by_id[sid].url) not in sites:chosen.append(sid);sites.add(site(by_id[sid].url))
        chosen=set([*chosen,*[sid for sid in candidates if sid not in chosen]][:policy(topic).keep])
        for finding in own:
            pairs=[(sid,quote) for sid,quote in zip(finding.source_ids,finding.quotes) if sid in chosen]
            if pairs:kept.append(finding if len(pairs)==len(finding.source_ids) else
                finding.model_copy(update={'source_ids':[p[0] for p in pairs],'quotes':[p[1] for p in pairs]}))
    order={f.finding_id:i for i,f in enumerate(findings)}
    kept.sort(key=lambda f:order.get(f.finding_id,len(order)))
    cited={}
    for finding in kept:
        for sid,quote in zip(finding.source_ids,finding.quotes):cited.setdefault(sid,[]).append(quote)
    if cited:
        return kept,[s.model_copy(update={'evidence':'\n'.join(dict.fromkeys(cited[s.source_id]))}) for s in sources if s.source_id in cited]
    checked=[s for s in sources if s.source_id in set(relevant_ids)][:CHECKED_SOURCE_LIMIT]
    return [],[s.model_copy(update={'evidence':next((p['text'] for p in evidence_passages([s])),None)}) for s in checked]


def choose_reads(due,found,flags,read):
    """Pages to read this round: per topic, its own search's triaged pages up to one search's allowance,
    then pages other topics' searches found for it, never beyond the topic's total read allowance."""
    chosen={};reads={}
    for topic in due:
        done=set(read.get(topic,[]));limit=policy(topic).max_urls-len(done)
        mine=[s for s in found.get(topic,[]) if topic in flags.get(s.source_id,()) and s.source_id not in done]
        others=[s for t in due if t!=topic for s in found.get(t,[]) if topic in flags.get(s.source_id,()) and s.source_id not in done]
        picks=list({s.source_id:s for s in mine[:min(policy(topic).urls_per_search,limit)]}.values())
        for source in others:
            if len(picks)>=limit:break
            if source.source_id not in {p.source_id for p in picks}:picks.append(source)
        reads[topic]=[s.source_id for s in picks]
        chosen.update({s.source_id:s for s in picks})
    return list(chosen.values()),reads


def merge_sources(saved,fresh):
    """Present fresh URLs first while preserving previously cited text within each page.

    Saved sources are pooled first, then the merged pages are reordered so new results come first.
    """
    merged=pool([*saved,*fresh])
    priority={s.source_id:index for index,s in enumerate(pool(fresh))}
    return sorted(merged,key=lambda s:priority.get(s.source_id,len(priority)))


def category_sources(job,category):
    """A category's own saved sources; a page shared with another category is never merged in."""
    retained=job.get('retained_sources')
    values=(retained.get(category) if retained is not None else None) or job.get('evidence',{}).get(category,[])
    return {s.source_id:s for s in pool(values)}

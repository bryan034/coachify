"""Bounded canonical source pooling across independently retrieved categories."""
import hashlib
from app.clients.research import normalize_sources
from app.clients.search_sources import OPPORTUNITY_EXCERPT_LIMIT

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
    return list(result.values())[:30]


def retain_useful(category,findings,sources,relevant_ids=()):
    """Select up to three sources by validated coverage, not arrival order."""
    from itertools import combinations
    from app.clients.search_sources import OPPORTUNITY_SOURCE_LIMIT
    useful=set(relevant_ids)|{s for f in findings for s in f.source_ids}
    candidates=[s for s in sources if s.source_id in useful]
    if not candidates:return [],[]
    ranks={'insufficient_evidence':0,'low':1,'medium':2,'high':3}
    def score(group):
        ids={s.source_id for s in group};supported=[f for f in findings if set(f.source_ids)<=ids]
        preferred='candidate_reported' if category in ('interview_intelligence','internship_insights','company_intelligence') else 'official'
        return (len({f.field for f in supported}),sum(f.scope=='exact' for f in supported),
            sum(ranks[f.confidence] for f in supported),sum(f.evidence_type==preferred for f in supported),
            sum(s.reliability=='official' for s in group),len(supported))
    chosen=max(combinations(candidates,min(OPPORTUNITY_SOURCE_LIMIT,len(candidates))),key=score)
    ids={s.source_id for s in chosen}
    return [f for f in findings if set(f.source_ids)<=ids],list(chosen)

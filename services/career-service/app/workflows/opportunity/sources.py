"""Bounded canonical source pooling across independently retrieved categories."""
import hashlib
from app.clients.research import normalize_sources

def pool(values):
    result={}
    for raw in values:
        source=normalize_sources([raw])[0]
        source.source_id='op-'+hashlib.sha256(source.url.encode()).hexdigest()[:24]
        if source.url in result:
            previous=result[source.url]
            if source.evidence and source.evidence not in (previous.evidence or ''):
                previous.evidence=((previous.evidence or '')+'\n'+source.evidence)[:2400]
        else:result[source.url]=source
    return list(result.values())[:30]

"""Normalize presentation citations against backend-approved sources only."""
import re
from urllib.parse import quote
from app.ai.adapter import AIError


def citation_error(issue):
    return AIError('invalid_output', True, reason='provenance', fields=('reply',),
                   violations=({'field': 'reply', 'issue': issue},))


def normalize_citations(reply, sources, *, strict_markers=True):
    """Accept exact trusted URLs and grouped IDs, never model-chosen destinations.

    Return canonical [source_id] markers before Python restores final links.
    No model response text, unknown reference or URL enters diagnostics.
    """
    urls = {}
    for identifier, url in sources.items():
        urls.setdefault(url, identifier)

    def approved_url(value):
        identifier=urls.get(value)
        if identifier is None:raise citation_error('unapproved_source_url')
        return '['+identifier+']'

    # Parse balanced Markdown destinations; a regex alone stops at URL parentheses.
    pattern=re.compile(r'\[[^\]\n]*\]\(')
    position=0
    while match:=pattern.search(reply,position):
        start=match.end();end=start;depth=1
        if reply[start:start+1]=='<':
            close=reply.find('>)',start+1)
            if close<0:raise citation_error('unapproved_source_url')
            destination=reply[start+1:close];end=close+1
        else:
            while end<len(reply):
                char=reply[end]
                if char=='(' :depth+=1
                elif char==')':
                    depth-=1
                    if depth==0:break
                end+=1
            if depth:raise citation_error('unapproved_source_url')
            destination=reply[start:end]
        marker=approved_url(destination)
        reply=reply[:match.start()]+marker+reply[end+1:]
        position=match.start()+len(marker)
    reply=re.sub(r'<(https?://[^<>\s]+)>',lambda m:approved_url(m[1]),reply)

    def bare_url(match):
        value=match[0];destination=value
        while destination not in urls and destination and destination[-1] in '.,;:!?)':
            destination=destination[:-1]
        return approved_url(destination)+value[len(destination):]

    reply=re.sub(r'https?://[^\s<>\]]+',bare_url,reply)
    if '](' in reply:raise citation_error('unapproved_source_url')
    cited = set()

    def marker(match):
        # Prefer a complete known ID before interpreting commas as separators.
        refs = [match[1]] if match[1] in sources else re.split(r'\s*[,;]\s*', match[1].strip())
        if any(ref not in sources for ref in refs):
            if not strict_markers:
                return match[0]  # Follow-up prose can contain arrays or bracketed terms.
            raise citation_error('unknown_source_reference')
        cited.update(refs)
        return ' '.join('[' + ref + ']' for ref in refs)

    return re.sub(r'\[([^\]\n]+)\]', marker, reply), cited


def source_links(identifiers,sources):
    """Links are always built from backend-approved URLs; angle destinations preserve parentheses."""
    urls=list(dict.fromkeys(sources[identifier] for identifier in identifiers))
    return ' '.join('[Source](<'+quote(url,safe=":/?#[]@!$&'()*+,;=%~")+'>)' for url in urls)


def summary_text(text):
    """Render model prose as text; model-authored Markdown/HTML cannot create links."""
    text=' '.join(text.split())
    return re.sub(r'([\\`*_{}\[\]()<>#!|+\-])',r'\\\1',text)


def render_citations(reply, sources):
    return re.sub(r'\[([^\]\n]+)\]',lambda m:source_links([m[1]],sources) if m[1] in sources else m[0],reply)


def fact_citations(reply,references,links,*,max_length=4000):
    """Replace inline fact markers with their approved links, never expose fact IDs."""
    if not references or any(ref not in links for ref in references):
        raise AIError('invalid_output',True,reason='provenance',fields=('references',),
            violations=({'field':'references','issue':'unknown_fact_reference'},))
    sources={source['source_id']:source['url'] for ref in references for source in links[ref]}

    def fact_marker(match):
        refs=re.split(r'\s*[,;]\s*',match[1].strip())
        if not any(re.fullmatch(r'(?:f|web)\d+',ref) for ref in refs):return match[0]
        if any(ref not in references for ref in refs):
            raise citation_error('unknown_fact_reference')
        ids=list(dict.fromkeys(source['source_id'] for ref in refs for source in links[ref]))
        return source_links(ids,sources)

    reply=re.sub(r'\[([^\]\n]+)\]',fact_marker,reply)
    normalized,cited=normalize_citations(reply,sources,strict_markers=False)
    reply=render_citations(normalized,sources)
    cited_urls={sources[identifier] for identifier in cited}
    # Compatibility for answers lacking inline markers: retain only uncited sources.
    remaining=[]
    for identifier,url in sources.items():
        if url not in cited_urls:
            remaining.append(identifier);cited_urls.add(url)
    if remaining:reply+='\n\nSources: '+source_links(remaining,sources)
    if len(reply)>max_length:
        raise AIError('invalid_output',True,reason='schema_validation',fields=('reply',),
            violations=({'field':'reply','issue':'citation_output_too_long'},))
    return reply

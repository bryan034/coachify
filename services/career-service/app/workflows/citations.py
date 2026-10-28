"""Normalize presentation citations against backend-approved sources only."""
import re
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

    def link(match):
        identifier = urls.get(match[1])
        if identifier is None:
            raise citation_error('unapproved_source_url')
        return '[' + identifier + ']'

    # A model may render a valid source as Markdown instead of the requested marker.
    reply = re.sub(r'\[[^\]\n]*\]\((https?://[^\s<>]+?)\)', link, reply)

    def bare_url(match):
        value = match[0]
        destination = value if value in urls else value.rstrip('.,;:!?')
        identifier = urls.get(destination)
        if identifier is None:
            raise citation_error('unapproved_source_url')
        return '[' + identifier + ']' + value[len(destination):]

    reply = re.sub(r'https?://[^\s<>\]\)]+', bare_url, reply)
    if '](' in reply:
        raise citation_error('unapproved_source_url')
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


def render_citations(reply, sources):
    return re.sub(r'\[([^\]\n]+)\]', lambda m: f'[Source]({sources[m[1]]})' if m[1] in sources else m[0], reply)

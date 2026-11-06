"""Search links to job sites elo does not read. Only the user's keywords go into these fixed addresses."""
from urllib.parse import urlencode

# Prosple's 9705 is its Singapore location. Huzzle offers no location parameter, so its results are worldwide.
SITES = (
    ('Prosple', 'https://sg.prosple.com/search-jobs', lambda q: {'keywords': q, 'locations': '9705', 'defaults_applied': '1'}),
    ('Huzzle', 'https://www.huzzle.com/search/results', lambda q: {'search': q, 'type': 'jobs'}),
    ('LinkedIn', 'https://www.linkedin.com/jobs/search/', lambda q: {'keywords': q, 'location': 'Singapore'}),
    ('Indeed', 'https://sg.indeed.com/jobs', lambda q: {'q': q, 'l': 'Singapore'}),
)


def external_searches(keywords):
    return [{'name': name, 'url': f'{origin}?{urlencode(params(keywords))}'} for name, origin, params in SITES]

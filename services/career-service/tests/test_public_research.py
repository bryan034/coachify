"""Future API connector boundary; no live search/scraping credentials."""
import asyncio
import pytest
from app.clients.research import normalize_sources,UnavailableResearchProvider
from app.repositories.goals import GoalError
from app.schemas.analysis import ResearchContext,ResearchSource

def source(**updates):return {'source_id':'s1','platform':'other','url':'https://example.test/interview',
    'title':'Public guide','evidence':'Data Analyst interview includes SQL exercise.',
    'reliability':'unverified','report_group':None,**updates}

def test_unconnected_api_is_explicitly_unavailable():
    with pytest.raises(GoalError,match='not connected'):
        asyncio.run(UnavailableResearchProvider().collect(ResearchContext(role='Analyst',field='Data')))

def test_duplicate_links_and_reposted_excerpts_are_deduplicated_without_inventing_independence():
    rows=normalize_sources([source(),source(source_id='s2',url='https://other.test/repost')])
    assert len(rows)==1 and rows[0].report_group is None and rows[0].retrieved_at is not None
    assert normalize_sources([source(url='https://example.test/interview?utm_source=test#top')])[0].url=='https://example.test/interview'

@pytest.mark.parametrize('url',['http://localhost/x','http://127.0.0.1/x','http://10.0.0.1/x','http://[::1]/x','http://user:pw@example.test','https://example.test:123/x','https://example.test/?token=secret'])
def test_unsafe_citation_links_are_rejected(url):
    with pytest.raises(GoalError):normalize_sources([source(url=url)])

def test_private_extra_fields_and_unbounded_batches_cannot_enter_shared_evidence():
    with pytest.raises(GoalError):normalize_sources([source(user_id='PRIVATE')])
    with pytest.raises(GoalError):normalize_sources([source()]*7)
    with pytest.raises(GoalError):normalize_sources([source(),source(evidence='different')])
    assert normalize_sources([])==[]

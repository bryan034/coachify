"""A cited passage must survive source merging, and each category is checked against its own sources."""
from app.clients.search_sources import OPPORTUNITY_EXCERPT_LIMIT
from app.schemas.analysis import ResearchSource
from app.workflows.opportunity.sources import category_sources,merge_sources,pool

URL='https://example.test/interview'


def source(text,url=URL):
    return ResearchSource(source_id='x',platform='other',url=url,evidence=text).model_dump(mode='json')


def long_text(marker,size):
    # The marker sits at the end, where a cut at the excerpt limit would remove it.
    return ('filler words '*size)[:size-len(marker)-1]+' '+marker


def test_new_text_for_a_known_page_never_pushes_out_the_text_already_cited():
    saved=long_text('QUOTED-FIRST-ROUND',OPPORTUNITY_EXCERPT_LIMIT-500)
    fresh=long_text('SECOND-SEARCH',OPPORTUNITY_EXCERPT_LIMIT-500)
    kept=merge_sources([source(saved)],[source(fresh)])[0].evidence
    assert 'QUOTED-FIRST-ROUND' in kept and len(kept)<=OPPORTUNITY_EXCERPT_LIMIT
    # The previous new-first order lost the cited passage: this is the regression.
    assert 'QUOTED-FIRST-ROUND' in pool([source(saved),source(fresh)])[0].evidence
    assert saved.rstrip() not in pool([source(fresh),source(saved)])[0].evidence


def test_a_page_shared_with_another_category_keeps_each_categorys_full_text():
    interview=long_text('INTERVIEW-QUOTE',OPPORTUNITY_EXCERPT_LIMIT-500)
    company=long_text('COMPANY-QUOTE',OPPORTUNITY_EXCERPT_LIMIT-500)
    job={'retained_sources':{'interview_intelligence':[source(interview)],'company_intelligence':[source(company)]}}
    combined=pool([s for values in job['retained_sources'].values() for s in values])[0].evidence
    assert 'COMPANY-QUOTE' not in combined  # the old all-category merge dropped it
    own=list(category_sources(job,'company_intelligence').values())[0].evidence
    assert 'COMPANY-QUOTE' in own and 'INTERVIEW-QUOTE' not in own


def test_followup_pages_lead_evaluation_without_replacing_saved_page_text():
    saved=long_text('SAVED-CITATION',OPPORTUNITY_EXCERPT_LIMIT-500)
    fresh=long_text('FRESH-EXCERPT',OPPORTUNITY_EXCERPT_LIMIT-500)
    merged=merge_sources([source(saved),source('Earlier result.',URL+'/old')],
        [source('Follow-up result.',URL+'/new'),source(fresh)])
    assert [s.url for s in merged]==[URL+'/new',URL,URL+'/old']
    assert saved in merged[1].evidence
    assert len(merged[1].evidence)<=OPPORTUNITY_EXCERPT_LIMIT
    # Reloading a checkpoint must retain both evaluation order and the original quote.
    restored=pool([s.model_dump(mode='json') for s in merged])
    assert [s.url for s in restored]==[s.url for s in merged]
    assert saved in restored[1].evidence


def test_category_sources_fall_back_to_unevaluated_evidence_and_unknown_categories():
    job={'evidence':{'interview_intelligence':[source('Round one is a case study.')]}}
    assert 'case study' in list(category_sources(job,'interview_intelligence').values())[0].evidence
    assert category_sources(job,'company_intelligence')=={}

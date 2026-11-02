"""Discovery summaries retain evidence and stay readable inside the saved chat."""
from app.schemas.discovery import MarketSummary, Scope
from app.workflows.discovery import summary_message


def sample():
    summary=MarketSummary.model_validate({
        'responsibility_refs':[0],
        'skills':[{'name':'SQL','requirement_type':'core','learning_priority':'high',
                   'relevance':'Useful for querying data.','skill_refs':[0]}],
        'specialisations':['Backend engineering'],'question':'Do you enjoy building APIs?',
    })
    result={'listings':[{'source_id':'job-1'}],'employers':1,'coverage':'limited',
            'responsibilities':[{'name':'Build APIs','source_ids':['job-1']}],
            'stats':[{'source_ids':['job-1']}],
            'qualifications':[{'name':'Relevant qualification','source_ids':['job-1']}],
            'warnings':['Only one listing was available.']}
    sources=[{'source_id':'job-1','url':'https://example.test/jobs/1'}]
    return Scope(field='Software',area='Software Engineering'),result,summary,sources


def test_summary_groups_findings_under_headings_with_sources_and_bold_invitation():
    message=summary_message(*sample())
    for title in ('Your career direction','Research coverage','Typical work','Recommended skills',
                  'Conditions to check','Possible specialisations','Research limitations','A question for you'):
        assert title in message and ('## '+title in message or '### '+title in message)
    assert '- **SQL**' in message and '**high learning priority**' in message
    assert '[source](<https://example.test/jobs/1>)' in message
    assert 'not universal employer requirements' in message
    assert message.endswith('**You can ask questions and refine your career goal through this chat.**')
    assert 'Review and confirm' not in message


def test_summary_omits_empty_sections_and_keeps_requested_skills_distinct():
    scope,result,summary,sources=sample()
    result.update(responsibilities=[],qualifications=[],warnings=[])
    summary.responsibility_refs=[];summary.specialisations=[];summary.question=None
    summary.skills[0].skill_refs=[]
    message=summary_message(scope,result,summary,sources)
    for title in ('Typical work','Conditions to check','Possible specialisations','Research limitations','A question for you'):
        assert title not in message
    assert '(user-requested addition; no listing evidence)' in message
    assert '[source]' not in message


def test_long_citations_cannot_drop_the_closing_invitation_or_break_the_message_bound():
    scope,result,summary,sources=sample()
    sources[0]['url']='https://example.test/'+'a'*11900
    message=summary_message(scope,result,summary,sources)
    assert len(message)<=12000
    assert message.endswith('**You can ask questions and refine your career goal through this chat.**')

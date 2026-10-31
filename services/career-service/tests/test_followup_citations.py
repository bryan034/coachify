"""Question answers resolve internal fact IDs to nearby verified source links."""
import asyncio
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.workflows.citations import fact_citations
from app.workflows.context_chat import semantic_chat
from tests.test_goal_chat_presentation import environment

A={'source_id':'a','url':'https://reports.test/interview_(online)'}
B={'source_id':'b','url':'https://candidates.test/report'}


def test_grouped_fact_markers_become_inline_links_without_duplicate_source_footer():
    text='1. Online test: 50 questions [f1, f3].\n2. Supervisor interview [f4].\n3. HR and panel interviews [f5].'
    reply=fact_citations(text,['f1','f3','f4','f5'],{'f1':[A],'f3':[A],'f4':[B],'f5':[B]})
    assert '50 questions [Source](<https://reports.test/interview_(online)>).' in reply
    assert 'Supervisor interview [Source](<https://candidates.test/report>).' in reply
    assert 'HR and panel interviews [Source](<https://candidates.test/report>).' in reply
    assert all(ref not in reply for ref in ('[f1','f3]','[f4]','[f5]'))
    assert 'Sources:' not in reply and reply.count('reports.test')==1


@pytest.mark.parametrize('marker',['[f999]','[f1, f999]','[web99]'])
def test_unknown_inline_fact_references_are_rejected(marker):
    with pytest.raises(AIError) as caught:fact_citations('Interview '+marker,['f1'],{'f1':[A]})
    assert caught.value.reason=='provenance'
    assert caught.value.violations==({'field':'reply','issue':'unknown_fact_reference'},)


def test_inline_refs_must_belong_to_the_declared_answer_references():
    with pytest.raises(AIError):fact_citations('Interview [f2]',['f1'],{'f1':[A],'f2':[B]})


def test_new_research_refs_and_uncited_compatibility_sources_still_resolve():
    reply=fact_citations('Office location [web0].',['web0','web1'],{'web0':[A],'web1':[B]})
    assert 'Office location [Source](<https://reports.test/interview_(online)>).' in reply
    assert reply.endswith('Sources: [Source](<https://candidates.test/report>)')
    assert reply.count('reports.test')==1


def test_saved_facts_without_public_sources_do_not_leak_fact_ids_or_invent_links():
    reply=fact_citations('SQL [required] is a saved skill [f1].',['f1'],{'f1':[]})
    assert '[required]' in reply and '[f1]' not in reply and 'http' not in reply


def test_a_model_written_unapproved_link_is_still_rejected():
    with pytest.raises(AIError):fact_citations('[Source](https://unapproved.test) [f1]',['f1'],{'f1':[A]})


def test_expanded_links_respect_the_reply_limit_without_truncating_citations():
    with pytest.raises(AIError) as caught:fact_citations('Interview [f1]',['f1'],{'f1':[A]},max_length=10)
    assert caught.value.violations==({'field':'reply','issue':'citation_output_too_long'},)


@pytest.mark.parametrize('count',[2,6])
def test_semantic_question_returns_links_in_the_interview_list(monkeypatch,count):
    async def run():
        request,body,*_=environment();body.message='What is the interview process?';body.conversation=[]
        class Store:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        names=['Online test','Supervisor interview',*[f'Interview stage {i}' for i in range(3,count+1)]]
        refs=[f'f{i}' for i in range(1,count+1)]
        links={ref:[A if i==0 else B] for i,ref in enumerate(refs)}
        monkeypatch.setattr('app.workflows.context_chat.selected_facts',lambda *args:([
            {'ref':ref,'kind':'interview_finding','data':{'value':name}}
            for ref,name in zip(refs,names)
        ],links,False))
        async def generate(payload,operation,**kwargs):
            result=ContextPlan(topic='interview_process',resolved_question=body.message) if payload.stage=='context_route' else FocusedAnswer(
                reply='\n'.join(f'{i}. {name} [{ref}].' for i,(ref,name) in enumerate(zip(refs,names),1)),references=refs)
            if kwargs.get('validate_output'):kwargs['validate_output'](result)
            return NS(data=result)
        request.app.state.ai=NS(generate=generate)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert 'Online test [Source](<https://reports.test/interview_(online)>).' in result.reply
        assert 'Supervisor interview [Source](<https://candidates.test/report>).' in result.reply
        assert 'Sources:' not in result.reply and '[f1]' not in result.reply
        assert all(name in result.reply for name in names)
    asyncio.run(run())


def test_many_references_still_reject_an_unknown_declared_fact():
    refs=[f'f{i}' for i in range(1,7)]
    with pytest.raises(AIError) as caught:
        fact_citations('Reported interviews [f1].',refs,{ref:[A] for ref in refs[:-1]})
    assert caught.value.violations==({'field':'references','issue':'unknown_fact_reference'},)

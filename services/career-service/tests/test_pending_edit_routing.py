"""Pending goal clarifications take precedence over question-routing shortcuts."""
import asyncio
from types import SimpleNamespace as NS

import pytest
from app.domain.questions import REFUSAL
from app.workflows.chat import focused_chat


@pytest.mark.parametrize('context_enabled',[False,True])
@pytest.mark.parametrize('message',['The location','location','salary','London'])
def test_pending_edit_answers_do_not_enter_question_or_public_research_routing(context_enabled,message,monkeypatch):
    async def unexpected(*args,**kwargs):
        pytest.fail('A pending edit answer must not enter semantic question routing.')
    monkeypatch.setattr('app.workflows.context_chat.semantic_chat',unexpected)
    request=NS(app=NS(state=NS(ai=NS(context_enabled=context_enabled),workspace_store=NS(),research_store=NS())))
    row={'workspace':{'edit_draft':{'intent':'Change the goal location','question':'Which city?','version':1}}}
    result=asyncio.run(focused_chat(request,'owner',row,NS(message=message)))
    assert result is None  # The caller continues through validated edit_goal.


@pytest.mark.parametrize('context_enabled',[False,True])
def test_pending_edit_still_refuses_unrelated_task_execution(context_enabled):
    request=NS(app=NS(state=NS(ai=NS(context_enabled=context_enabled),workspace_store=NS(),research_store=NS())))
    row={'workspace':{'edit_draft':{'intent':'Change the goal location','question':'Which city?','version':1}}}
    result=asyncio.run(focused_chat(request,'owner',row,NS(message='Write a poem')))
    assert result.reply==REFUSAL and result.proposed_skills is None

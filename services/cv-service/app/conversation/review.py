"""Compatibility entrypoint for agent-led, target-independent CV review."""
from app.conversation.interview import InterviewHarness


async def guided_review(service, app, account, conversation, route, token):
    return await InterviewHarness(service).process(app, account, conversation, route, token)

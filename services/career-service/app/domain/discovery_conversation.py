"""Fixed Career Discovery copy; opening a chat requires no model generation."""
import re

LEGACY_INTRODUCTION = (
    "Hi, I’m elo’s Career Discovery assistant. This chat helps you choose a career "
    "direction and build a recommended skill set backed by research.\n\n"
    "To start, tell me a field or role you’re interested in, or describe the kind of work "
    "you enjoy. You can keep it broad—no CV, specific vacancy or specialisation is required.\n\n"
    "I’ll ask one focused question at a time when useful, then research representative roles "
    "once your direction is clear. You can ask questions or refine the results, and you’ll "
    "review and confirm before saving your goal."
)


PREVIOUS_INTRODUCTION = LEGACY_INTRODUCTION.replace(
    "I’ll ask one focused question at a time when useful, then research representative roles once your direction is clear.",
    "I will ask questions to understand your interests and personalise your goal for you, then research representative roles once we have enough context.",
)

MANUAL_SAVE_INTRODUCTION = (
    "Hi, I’m elo’s career guidance assistant. I can help you explore career paths, "
    "compare roles, or talk through questions about jobs and internships.\n\n"
    "Tell me what’s on your mind, a field you’re curious about, or the kind of work you enjoy. "
    "You don’t need a CV or a clear direction to start. You can also ask how this chat works.\n\n"
    "As we talk, I’ll ask questions to understand your interests and preferences. "
    "Once we have enough context, I’ll research representative roles and suggest a skill set "
    "for your direction. You’ll review and confirm before saving your career goal."
)


INTRODUCTION = MANUAL_SAVE_INTRODUCTION.replace(
    'You’ll review and confirm before saving your career goal.',
    'Your career goal updates automatically as we refine your direction together.',
)


def conversation_messages(messages):
    """Exclude display-only opening copy, including legacy stored introductions."""
    return [message for message in messages
            if not (message.get('role') == 'assistant' and message.get('content') in (INTRODUCTION,MANUAL_SAVE_INTRODUCTION,PREVIOUS_INTRODUCTION,LEGACY_INTRODUCTION))]


def conversational_reply(message, *, ongoing=False):
    """Exact social/help turns need no inference; mixed requests still use the model."""
    text=re.sub(r'[.!?]+$', '', ' '.join(message.casefold().split())).strip()
    if text in ('hi','hello','hey','hi elo','hello elo','hey elo','good morning','good afternoon','good evening'):
        if ongoing:
            return 'Hi again! We can carry on exploring your career direction from where we left off.'
        return 'Hi! I can help you explore career paths, compare roles, and discuss jobs or internships.'
    if text in ('how do i use this','how to use this','how does this work','how do i use this chat','what can you do'):
        return ('Start with a career question, an interest, or a kind of work you enjoy. '
            'We can compare directions and build up your interests and preferences together. '
            'Once there is enough context, I’ll research representative roles. '
            'Your goal updates automatically as we refine it.')
    if text in ('thanks','thank you','thanks elo','thank you elo'):
        return 'You’re welcome! We can keep exploring your career direction whenever you’re ready.'
    return None

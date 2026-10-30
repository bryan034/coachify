"""Fixed Career Discovery copy; opening a chat requires no model generation."""

LEGACY_INTRODUCTION = (
    "Hi, I’m elo’s Career Discovery assistant. This chat helps you choose a career "
    "direction and build a recommended skill set backed by research.\n\n"
    "To start, tell me a field or role you’re interested in, or describe the kind of work "
    "you enjoy. You can keep it broad—no CV, specific vacancy or specialisation is required.\n\n"
    "I’ll ask one focused question at a time when useful, then research representative roles "
    "once your direction is clear. You can ask questions or refine the results, and you’ll "
    "review and confirm before saving your goal."
)


INTRODUCTION = LEGACY_INTRODUCTION.replace(
    "I’ll ask one focused question at a time when useful, then research representative roles once your direction is clear.",
    "I will ask questions to understand your interests and personalise your goal for you, then research representative roles once we have enough context.",
)


def conversation_messages(messages):
    """Exclude display-only opening copy, including legacy stored introductions."""
    return [message for message in messages
            if not (message.get('role') == 'assistant' and message.get('content') in (INTRODUCTION,LEGACY_INTRODUCTION))]

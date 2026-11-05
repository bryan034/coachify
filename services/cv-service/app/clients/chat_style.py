"""Formatting guidance for model prompts that write user-facing chat text."""

CHAT_EMPHASIS = '''
Chat formatting: write chat text shown to the user (reply, follow_up and question fields) as Markdown and bold key words and phrases with **double asterisks** so it is easy to scan, such as role names, skills, dates, decisions and the next action. Bold a few short phrases per paragraph, never whole sentences. Keep source markers, IDs and links outside bold text. Never add bold to any other field, including quotes, excerpts, evidence, explanations and saved values.
'''

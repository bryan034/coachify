"""One 1-10 scale for how well a skill is understood: the level a role expects and the level a person has shown.

AI tools can produce work for anyone, so the scale measures understanding of the subject, not whether the
person can carry out the tasks alone. Career rates each required skill on it, CV rates each of the person's
skills on it, and Assessment compares the two. Evidence of a person's level is read pessimistically: what is
not stated or explained is assumed not to be understood.
"""
SCALE_VERSION = 'understanding-1-10-v2'
MIN_LEVEL, MAX_LEVEL = 1, 10
# Moderate understanding (4-6) is the midpoint: enough to explain the concepts.
MODERATE_LEVEL = 5
# Evidence of use alone, without the person explaining the subject, shows at most little understanding.
UNEXPLAINED_CEILING = 3
# A skill that is only named, with no described use.
MENTION_CEILING = 2

ANCHORS = {
    1: 'No understanding: only named, or cannot answer questions about the skill.',
    2: 'Little understanding: heard of or briefly seen; would struggle with most questions.',
    3: 'Basic understanding: knows the vocabulary and basic ideas but cannot proficiently answer most questions on the skill.',
    4: 'Moderate understanding: can explain the main concepts, with gaps.',
    5: 'Moderate understanding: explains the concepts and why they work, with a decent grasp.',
    6: 'Solid moderate understanding: explains concepts and trade-offs and handles follow-up questions on common situations.',
    7: 'Good understanding: eloquently articulates the core concepts and how they connect.',
    8: 'Strong good understanding: articulates core concepts and edge cases clearly and answers probing questions well.',
    9: 'Expert understanding: deep knowledge of the subject, including internals, trade-offs and limits.',
    10: 'Expert understanding at the deepest level: authoritative knowledge that others consult.',
}

SCALE_TEXT = ('Understanding scale, whole numbers 1-10. It rates how well the skill is UNDERSTOOD, not whether the person can do the tasks '
              'alone; AI tools can produce work for anyone, so having done or delivered work is not itself understanding. '
              '1-3 = no, little or basic understanding: if questioned, could not proficiently answer most questions on the skill. '
              '4-6 = moderate understanding: enough to explain the concepts, with a decent level of understanding. '
              '7-8 = good understanding: able to eloquently articulate the core concepts. '
              '9-10 = expert understanding with deep knowledge.\n'
              + '\n'.join(f'{level} = {text}' for level, text in ANCHORS.items()))

PESSIMISM_TEXT = ('Be pessimistic about a person\'s level: choose the lower level whenever the evidence allows two readings. '
                  'Judge understanding from what the person explains or demonstrates they know, such as their review answers '
                  'and how they describe concepts, reasons and trade-offs. '
                  'What is not stated or explained is not understood. Using a skill, delivering results or finishing a project does '
                  'not show understanding by itself, because AI may have done the work; whether it was done independently is '
                  'irrelevant to the level. '
                  f'If the evidence shows a skill was used but nothing shows the person understands it, give at most level {UNEXPLAINED_CEILING}. '
                  f'A skill that is only named, with no described use, is at most level {MENTION_CEILING}. '
                  f'Levels {MODERATE_LEVEL} and above need explanations that show the concepts are understood; 7-8 need clear, '
                  'articulate explanation of the core concepts; 9-10 need deep knowledge shown through detail, trade-offs and edge cases. '
                  'Titles, tenure, team results, tool lists and self-ratings alone never raise a level.')


def clamp_level(level, ceiling=MAX_LEVEL):
    """A whole-number level within the scale and under an evidence ceiling."""
    return max(MIN_LEVEL, min(int(level), ceiling, MAX_LEVEL))

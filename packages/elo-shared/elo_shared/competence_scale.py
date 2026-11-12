"""One 1-10 competence scale for the level a role needs and the level a person has shown.

Career rates each required skill on it, CV rates each of the person's skills on it, and
Assessment compares the two. Evidence of a person's level is read pessimistically: what is
not stated is assumed not to have happened.
"""
SCALE_VERSION = 'competence-1-10-v1'
MIN_LEVEL, MAX_LEVEL = 1, 10
# Working alone with understanding is the midpoint; below it the person still needs guidance.
INDEPENDENT_LEVEL = 5
# Without stated independence the work is assumed guided.
GUIDED_CEILING = 3
# A skill that is only named, with no described use.
MENTION_CEILING = 2

ANCHORS = {
    1: 'Not competent: no real use shown, at most named or briefly seen.',
    2: 'Basic exposure: coursework, tutorials or a listed skill with no described use.',
    3: 'Guided use: applied on real tasks with guidance, supervision or an unclear personal part.',
    4: 'Mostly independent: works alone on routine tasks, results not yet proven.',
    5: 'Independent and understands: delivers working results alone and can explain why they work.',
    6: 'Independent on non-routine tasks, solving unfamiliar problems.',
    7: 'Complex work: designs and delivers complex solutions and debugs hard problems.',
    8: 'Sustained complex work over years, and guides others.',
    9: 'Leads and architects complex systems or work at scale; a recognised authority.',
    10: 'Expert on the most complex work in the field, setting direction for others.',
}

SCALE_TEXT = ('Competence scale, whole numbers 1-10 (1 = not competent, 5 = works independently and understands the skill, '
              '10 = handles the most complex work in the field):\n'
              + '\n'.join(f'{level} = {text}' for level, text in ANCHORS.items()))

PESSIMISM_TEXT = ('Be pessimistic about a person\'s level: choose the lower level whenever the evidence allows two readings. '
                  'What is not stated did not happen. If the evidence shows a skill was used but does not say the person did it '
                  f'independently, assume it was done under guidance: at most level {GUIDED_CEILING}. '
                  f'A skill that is only named, with no described use, is at most level {MENTION_CEILING}. '
                  f'Level {INDEPENDENT_LEVEL} and above need stated independent work; 6-7 also need described complexity and '
                  'problem solving in that skill; 8 and above need sustained, repeated complex work. '
                  'Titles, tenure, team results and tool lists alone never raise a level.')


def clamp_level(level, ceiling=MAX_LEVEL):
    """A whole-number level within the scale and under an evidence ceiling."""
    return max(MIN_LEVEL, min(int(level), ceiling, MAX_LEVEL))

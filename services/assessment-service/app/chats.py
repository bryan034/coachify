"""Saved Skills Helper conversations: one document per account and skill, keeping the newest turns."""
from elo_shared.runtime import Problem, stamp

KEPT_TURNS = 40
MODEL_TURNS = 20


def chat_key(name, canonical_skill_id=None):
    return (canonical_skill_id or '').strip() or name.strip().casefold()


def person_turn(text):
    return {'role': 'person', 'text': text, 'evidence': None, 'level': None, 'created_at': stamp()}


def elo_turn(text, evidence=None, level=None):
    return {'role': 'elo', 'text': text, 'evidence': evidence, 'level': level, 'created_at': stamp()}


def model_conversation(turns, message):
    """The newest saved turns plus the person's new message, with saved evidence and level checks spelled out."""
    def spoken(turn):
        text = turn['text']
        if turn.get('evidence'):
            text += "\nSaved to the person's Skills Profile: " + turn['evidence']
        if turn.get('level'):
            text = ('elo re-judged this skill with what the person said: level ' + str(turn['level']['before'] or 'not rated')
                    + ' -> ' + str(turn['level']['after'] or 'not rated') + '. ' + text)
        return {'role': turn['role'], 'text': text}
    return [spoken(turn) for turn in turns[-(MODEL_TURNS - 1):]] + [{'role': 'person', 'text': message}]


class SkillChats:
    def __init__(self, database):
        self.collection = database['skill_chats'] if database is not None else None

    def _rows(self):
        if self.collection is None:
            raise Problem('Service storage is not configured.', 503, 'storage')
        return self.collection

    def turns(self, owner, key):
        row = self._rows().find_one({'_id': owner + ':' + key, 'owner': owner}, {'turns': 1})
        return (row or {}).get('turns', [])

    def append(self, owner, key, name, *turns):
        self._rows().update_one({'_id': owner + ':' + key, 'owner': owner},
                                {'$push': {'turns': {'$each': list(turns), '$slice': -KEPT_TURNS}},
                                 '$set': {'name': name, 'updated_at': stamp()}}, upsert=True)

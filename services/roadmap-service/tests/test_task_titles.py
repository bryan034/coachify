"""New task titles are bounded without invalidating older saved work."""
import pytest
from pydantic import ValidationError

from app.schemas.tasks import EditableTask, TaskChanges, TaskDefinition
from app.schemas.roadmap import NewSession, SessionChanges


def test_title_word_limit_on_creation_and_edit():
    fields = dict(instructions='Do the work', completion_outcome='Record the result', estimated_minutes=30)
    assert TaskDefinition(title=' '.join(['word'] * 11), **fields).title.count('word') == 11
    with pytest.raises(ValidationError, match='at most 11'):
        TaskDefinition(title=' '.join(['word'] * 12), **fields)
    with pytest.raises(ValidationError, match='at most 11'):
        TaskChanges(title='\t'.join(['word'] * 12))
    assert TaskChanges(instructions='Updated instructions').title is None


def test_existing_long_title_remains_readable_and_unsplit_text_uses_character_limit():
    title = ' '.join(['word'] * 12)
    task = EditableTask(id='old', title=title, instructions='Work', completion_outcome='Done',
                        estimated_minutes=30, status='not_started', origin='generated')
    assert task.title == title
    assert TaskChanges(title='学习数组和算法').title == '学习数组和算法'
    with pytest.raises(ValidationError):
        TaskChanges(title='字' * 161)


def test_session_edit_and_create_apply_the_same_title_limit():
    title=' '.join(['word'] * 12)
    with pytest.raises(ValidationError, match='at most 11'):
        SessionChanges(title=title)
    with pytest.raises(ValidationError, match='at most 11'):
        NewSession(title=title,date='2030-01-09',duration_minutes=30)
    assert SessionChanges(notes={'blocks':[]}).title is None

"""New task titles are bounded without invalidating older saved work."""
import pytest
from pydantic import ValidationError

from app.schemas.tasks import EditableTask, TaskChanges, TaskDefinition


def test_title_word_limit_on_creation_and_edit():
    fields = dict(instructions='Do the work', completion_outcome='Record the result', estimated_minutes=30)
    assert TaskDefinition(title=' '.join(['word'] * 19), **fields).title.count('word') == 19
    with pytest.raises(ValidationError, match='at most 19'):
        TaskDefinition(title=' '.join(['word'] * 20), **fields)
    with pytest.raises(ValidationError, match='at most 19'):
        TaskChanges(title='\t'.join(['word'] * 20))
    assert TaskChanges(instructions='Updated instructions').title is None


def test_existing_long_title_remains_readable_and_unsplit_text_uses_character_limit():
    title = ' '.join(['word'] * 20)
    task = EditableTask(id='old', title=title, instructions='Work', completion_outcome='Done',
                        estimated_minutes=30, status='not_started', origin='generated')
    assert task.title == title
    assert TaskChanges(title='学习数组和算法').title == '学习数组和算法'
    with pytest.raises(ValidationError):
        TaskChanges(title='字' * 161)

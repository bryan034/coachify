"""Task notes: a Word-like document with inserted checkboxes and choices, saved as validated data."""
import pytest
from pydantic import ValidationError

from app.schemas.notes import MAX_TEXT, NotesDocument
from planner_fixtures import draft
from test_editable_tasks import by_title, definition, request, save
from test_planner_flow import Scripted, Sources, accepted, client_for, read

DOC = {'blocks': [
    {'type': 'heading', 'runs': [{'text': 'What I did'}]},
    {'type': 'paragraph', 'runs': [{'text': 'Set up '}, {'text': 'pytest', 'bold': True}, {'text': ' today.', 'italic': True}]},
    {'type': 'checkbox', 'checked': True, 'runs': [{'text': 'Install pytest'}]},
    {'type': 'choice', 'id': 'feel', 'question': 'How did it go?', 'options': [{'id': 'easy', 'text': 'Easy'}, {'id': 'hard', 'text': 'Hard'}], 'selected': 'easy'},
    {'type': 'bullet', 'runs': [{'text': 'Read the docs'}]},
]}


def test_notes_save_restore_and_leave_status_and_schedule_alone():
    with client_for(Scripted([draft()]), Sources()) as client:
        state = save(client, 'add', accepted(client), task=definition())
        task = by_title(state, 'Practise explaining a project')
        state = save(client, 'notes', state, task_id=task['id'], notes=DOC)
        saved = by_title(state, task['title'])
        assert saved['notes'] == NotesDocument.model_validate(DOC).model_dump(mode='json')
        assert saved['notes_updated_at'] and saved['status'] == task['status'] and saved['schedule'] == task['schedule']
        assert by_title(read(client), task['title'])['notes'] == saved['notes']
        stamp = saved['notes_updated_at']
        again = save(client, 'notes', state, task_id=task['id'], notes=DOC)
        assert by_title(again, task['title'])['notes_updated_at'] == stamp  # unchanged notes keep their time


def test_notes_need_the_current_version_and_an_owned_task():
    sources = Sources()
    with client_for(Scripted([draft()]), sources) as client:
        state = save(client, 'add', accepted(client), task=definition())
        task = by_title(state, 'Practise explaining a project')
        stale = {**state, 'version': state['version'] - 1}
        assert request(client, 'notes', stale, task_id=task['id'], notes=DOC).status_code == 409
        assert request(client, 'notes', state, task_id='missing', notes=DOC).status_code == 404
        sources.owner = '22222222-2222-4222-8222-222222222222'
        assert request(client, 'notes', read(client), task_id=task['id'], notes=DOC).status_code in (404, 409)


@pytest.mark.parametrize('blocks', [
    [{'type': 'html', 'runs': [{'text': '<script>'}]}],
    [{'type': 'choice', 'id': 'q', 'options': [{'id': 'a', 'text': 'Only one'}]}],
    [{'type': 'choice', 'id': 'q', 'options': [{'id': 'a', 'text': 'A'}, {'id': 'b', 'text': 'B'}], 'selected': 'c'}],
    [{'type': 'choice', 'id': 'q', 'options': [{'id': 'a', 'text': 'A'}, {'id': 'a', 'text': 'B'}]}],
    [{'type': 'paragraph', 'runs': [{'text': 'x', 'colour': 'red'}]}],
    [{'type': 'paragraph', 'runs': [{'text': 'x' * 2000}]}] * 11,
])
def test_notes_reject_unknown_markup_impossible_choices_and_oversized_documents(blocks):
    with pytest.raises(ValidationError):
        NotesDocument.model_validate({'blocks': blocks})
    assert MAX_TEXT == 20000


def test_a_task_with_notes_is_protected_when_the_plan_is_regenerated():
    from app.planning.generator import protected_tasks
    plan = {'editable_tasks': [{'id': 't1', 'origin': 'generated', 'status': 'not_started', 'notes': DOC},
                               {'id': 't2', 'origin': 'generated', 'status': 'not_started'}]}
    assert [task['id'] for task in protected_tasks(plan)] == ['t1']


def test_each_projected_session_names_its_task_so_notes_can_be_found():
    with client_for(Scripted([draft()]), Sources()) as client:
        plan = accepted(client)['planner']['active']
        tasks = {task['id'] for task in plan['editable_tasks']}
        assert plan['assignments'] and all(session['task_id'] in tasks for session in plan['assignments'])

"""Generated task guidance survives preview, publication, reads and edits."""
import copy
import pytest
from pydantic import ValidationError
from planner_fixtures import assignment, draft
from app.schemas.tasks import EditableTask
from app.schemas.weeks import WeekTask
from test_planner_flow import Scripted, accept_outline, client_for, configure, generate, read, week_draft
from test_editable_tasks import request, save, tasks

DESCRIPTION='1. Create an endpoint using the project conventions.\n2. Add tests for success and invalid input, run them and fix failures.\n3. Save your code once all tests pass.'

def generated(**changes):
    return {**week_draft([assignment()])['tasks'][0],'description':DESCRIPTION,**changes}

def test_generated_title_word_limit():
    title=' '.join(['Build']*11)
    assert WeekTask.model_validate(generated(title=title)).title==title
    with pytest.raises(ValidationError,match='at most 11'):
        WeekTask.model_validate(generated(title=title+' endpoint'))

@pytest.mark.parametrize('description',[None,'','   ','x'*4001])
def test_generated_description_is_required_and_bounded(description):
    with pytest.raises(ValidationError):WeekTask.model_validate(generated(description=description))
    missing=generated();missing.pop('description')
    with pytest.raises(ValidationError):WeekTask.model_validate(missing)

def test_description_survives_preview_acceptance_reads_and_edits():
    model=Scripted([draft()],weeks=[week_draft(tasks=[generated()])])
    with client_for(model) as client:
        state=generate(client,configure(client))
        assert state['planner']['week_candidate']['tasks'][0]['description']==DESCRIPTION
        state=accept_outline(client,state)
        task=state['planner']['active']['editable_tasks'][0]
        assert task['description']==DESCRIPTION
        assert state['planner']['active_sessions'][0]['description']==DESCRIPTION
        assert tasks(client)['tasks'][0]['description']==DESCRIPTION
        revised=DESCRIPTION+'\n4. Explain your solution aloud.'
        state=save(client,'edit',state,task_id=task['id'],changes={'description':revised})
        saved=state['planner']['active']['editable_tasks'][0]
        assert saved['description']==revised
        assert saved['history'][-1]['previous']['description']==DESCRIPTION
        assert read(client)['planner']['active_sessions'][0]['description']==revised
        invalid=request(client,'edit',state,task_id=task['id'],changes={'title':' '.join(['word']*12)})
        assert invalid.status_code==422
        assert read(client)['version']==state['version']
        legacy=copy.deepcopy(saved);legacy.pop('description');legacy['title']=' '.join(['Historical']*20)
        assert EditableTask.model_validate(legacy).description is None
        assert EditableTask.model_validate(legacy).title==legacy['title']

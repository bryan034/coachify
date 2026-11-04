"""Display groups sit on the read wrapper so the saved goal, and its hash, stay unchanged."""
import json
from pathlib import Path
from app.repositories.goals import fingerprint
from app.schemas.workspace import CurrentCareerGoal, WorkspaceView

FIXTURE = Path(__file__).resolve().parents[3] / 'apps/frontend/tests/fixtures/career-workspace.json'


def workspace():
    return json.loads(FIXTURE.read_text())


def test_workspace_maps_each_goal_skill_to_a_display_group():
    current = WorkspaceView.model_validate(workspace()).current
    assert current.skill_groups == {'SQL': 'Data & analytics'}


def test_a_client_supplied_map_is_replaced_by_the_derived_one():
    value = workspace()
    value['current']['skill_groups'] = {'SQL': 'Invented group'}
    assert WorkspaceView.model_validate(value).current.skill_groups == {'SQL': 'Data & analytics'}


def test_no_goal_has_no_groups():
    assert CurrentCareerGoal(selection_version=0, goal=None).skill_groups == {}


def test_the_saved_goal_and_its_confirmation_hash_do_not_depend_on_groups():
    value = workspace()
    goal = WorkspaceView.model_validate(value).current.goal
    dumped = goal.model_dump(mode='json', by_alias=True)
    assert 'skill_groups' not in dumped and all('skill_groups' not in skill for skill in dumped['skills'])
    without = workspace()
    without['current'].pop('skill_groups')
    again = WorkspaceView.model_validate(without).current.goal
    assert fingerprint(again.model_dump(mode='json', by_alias=True)) == fingerprint(dumped)

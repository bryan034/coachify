"""Static rules for the service code that Ruff and vulture do not cover."""
import ast
from pathlib import Path
from fastapi.routing import APIRoute
from app.main import app

APP=Path(__file__).resolve().parents[1]/'app'
GATE_KEYS={'freshness','ready','stale','availability'}
UNTYPED_OBJECTS_ALLOWED={'assessment','context','goal','cv'}
READ_ONLY_UNTIMED_PLAN={'Plan','Task','Schedule'}
SHARED_RUNTIME_ROUTES={'/health'}


def modules():
    for path in sorted(APP.rglob('*.py')):
        yield path.relative_to(APP.parent).as_posix(),ast.parse(path.read_text(),filename=str(path))


def is_message_text(node):
    if isinstance(node,ast.Subscript) and isinstance(node.slice,ast.Constant):return node.slice.value in ('message','detail')
    return isinstance(node,ast.Attribute) and node.attr in ('message','detail')


def test_code_branches_on_error_codes_not_on_message_text():
    found=[f'{name}:{node.lineno}' for name,tree in modules() for node in ast.walk(tree)
        if isinstance(node,ast.Compare) and any(isinstance(op,(ast.In,ast.NotIn,ast.Eq,ast.NotEq)) for op in node.ops)
        and any(is_message_text(side) for side in [node.left,*node.comparators])]
    assert found==[]


def test_gate_fields_are_never_given_a_permissive_default():
    found=[]
    for name,tree in modules():
        for node in ast.walk(tree):
            if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='get' and len(node.args)==2
                    and isinstance(node.args[0],ast.Constant) and node.args[0].value in GATE_KEYS
                    and not (isinstance(node.args[1],ast.Constant) and node.args[1].value in (None,False))):
                found.append(f'{name}:{node.lineno}')
    assert found==[]


def test_hasattr_is_not_used_to_accept_two_shapes_of_data():
    found=[f'{name}:{node.lineno}' for name,tree in modules() for node in ast.walk(tree)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='hasattr']
    assert found==[]


def test_session_ids_are_derived_in_one_place():
    found=[name for name,tree in modules() for node in ast.walk(tree)
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and ':slot:' in node.value]
    assert found==['app/planning/tasks.py']


def test_every_route_declares_its_response_model():
    assert [route.path for route in app.routes if isinstance(route,APIRoute) and route.response_model is None and route.path not in SHARED_RUNTIME_ROUTES]==[]


def untyped(node,field,where,found):
    """Collect open objects (no properties and no typed values) by the property that holds them."""
    if isinstance(node,list):
        for value in node:untyped(value,field,where,found)
        return
    if not isinstance(node,dict):return
    values=node.get('additionalProperties')
    if node.get('type')=='object' and 'properties' not in node and not (isinstance(values,dict) and values):found.append((field,where))
    for key,value in node.items():
        if key=='properties':
            for name,schema in value.items():untyped(schema,name,f'{where}.{name}',found)
        else:untyped(value,field,where,found)


def test_published_schemas_have_no_untyped_objects_outside_source_snapshots():
    found=[]
    for name,schema in app.openapi()['components']['schemas'].items():
        if name not in READ_ONLY_UNTIMED_PLAN:untyped(schema,name,name,found)
    assert sorted(where for field,where in found if field not in UNTYPED_OBJECTS_ALLOWED)==[]

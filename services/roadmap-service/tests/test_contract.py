import json
from pathlib import Path
from app.main import app
from app.schemas import OperationAccepted,Plan,PlannedRoadmap

def test_published_contracts_match_the_running_service_models():
    root=Path(__file__).resolve().parents[3]/'contracts/api'
    assert json.loads((root/'roadmap.yaml').read_text())==app.openapi()
    assert json.loads((root/'models/roadmap.schema.json').read_text())==Plan.model_json_schema()
    assert json.loads((root/'models/roadmap-plan.schema.json').read_text())==PlannedRoadmap.model_json_schema()

def test_operation_routes_publish_the_shape_the_frontend_polls():
    paths=app.openapi()['paths']
    for path,method,status in (('/api/v1/roadmaps/planner/generate','post','202'),('/api/v1/roadmaps/messages','post','202'),('/api/v1/roadmaps/progress','get','200')):
        schema=paths[path][method]['responses'][status]['content']['application/json']['schema']
        assert schema=={'$ref':'#/components/schemas/'+OperationAccepted.__name__}

def test_a_saved_roadmap_has_no_untyped_objects_except_the_assessment_snapshot():
    schema=PlannedRoadmap.model_json_schema();untyped=[]
    def walk(node,where):
        if isinstance(node,dict):
            if node.get('type')=='object' and 'properties' not in node:untyped.append(where)
            for key,value in node.items():walk(value,f'{where}.{key}')
        elif isinstance(node,list):
            for value in node:walk(value,where)
    walk(schema,'')
    assert untyped==['.properties.assessment']

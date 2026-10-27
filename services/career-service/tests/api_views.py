"""Test helpers for canonical goal content and explicit research reads."""
from bson import ObjectId
from app.schemas.jd import JDExtraction

def goal_view(response):
    value=response.json()
    if set(value)=={'current'} and value['current'].get('goal'):
        goal=value['current']['goal']
        return {**goal,'goal_id':goal['_id'],'content':{k:v for k,v in goal.items() if k in JDExtraction.model_fields}}
    return value

def saved_research(flow,workspace):
    record=flow[1].interview_research.find_one({'_id':ObjectId(workspace['research_id'])}) if workspace.get('research_id') else None
    return record

def goal_content(goal):
    return {k:v for k,v in goal.items() if k in JDExtraction.model_fields}

"""Test helpers for canonical goal content, explicit research reads and synthetic passage labels."""
import json
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


def label_passages(payload):
    """Synthetic passage-scope labels: the target market or a .sg host is local; a number or a subject word states the detail."""
    from app.ai.passage_scope import PassageScopes
    data=json.loads(payload.context)
    market=data['target_market'].casefold()
    subject={w for w in (data.get('subject') or '').casefold().split() if len(w)>3}
    def label(passage):
        text=f"{passage['title'] or ''} {passage['text']}".casefold()
        local=market in text or passage['source'].endswith('.sg')
        detail=any(c.isdigit() for c in passage['text']) or bool(subject & set(text.replace('.',' ').split()))
        return {'ref':passage['ref'],'market':'target' if local else 'unknown','states_detail':detail}
    return PassageScopes(passages=[label(p) for p in data['passages']])

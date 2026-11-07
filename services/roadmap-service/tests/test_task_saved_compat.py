"""Typed task responses preserve sparse saved history and future extras."""
import copy

from app.schemas.roadmap import PlannedRoadmap
from app.schemas.tasks import EditableTask


def task():
    return {'id':'task-1','title':'Synthetic task','instructions':'Read.',
        'completion_outcome':'A summary.','estimated_minutes':30,'requirement_refs':[],
        'prerequisites':[],'milestone_key':'m1','schedule':[], 'status':'not_started',
        'origin':'generated','history':[],'removed':False,'removal':None,'source_assignment':None}


def test_saved_history_removal_and_source_assignment_keep_sparse_fields_and_extras():
    source=task()
    source['history']=[
        {'at':'2030-01-01T00:00:00Z','from':'scheduled','to':'completed','legacy':'retained'},
        {'at':'2030-01-02T00:00:00Z','event':'edited','fields':['title','schedule'],
         'previous':{'title':'Earlier title','schedule':[{'date':'2030-01-03','start_time':'10:00','duration_minutes':30}],
                     'future_attribute':{'nested':'retained'}}},
        {'event':'removed','reason':None},
    ]
    source['removal']={'at':'2030-01-03T00:00:00Z','reason':None,'future':'retained'}
    source['source_assignment']={'id':'old-1','status':'completed',
        'history':[{'from':'scheduled','to':'completed'}],'future':{'nested':1}}
    original=copy.deepcopy(source)
    restored=EditableTask.model_validate(source).model_dump(mode='json',by_alias=True)
    for key in ('history','removal','source_assignment'):
        assert restored[key]==original[key]
    assert source==original


def test_legacy_minimal_records_are_not_filled_with_null_history_fields():
    source=task()
    source['history']=[{}, {'from':'not_started','to':'in_progress'}, {'event':'edited','previous':{}}]
    source['removal']={}
    source['source_assignment']={}
    restored=EditableTask.model_validate(source).model_dump(mode='json',by_alias=True)
    assert restored['history']==source['history']
    assert restored['removal']=={}
    assert restored['source_assignment']=={}


def test_saved_roadmap_schema_keeps_assessment_as_the_only_untyped_object():
    untyped=[]
    def walk(node,path):
        if isinstance(node,dict):
            if node.get('type')=='object' and 'properties' not in node:untyped.append(path)
            for key,value in node.items():walk(value,path+'.'+key)
        elif isinstance(node,list):
            for item in node:walk(item,path)
    walk(PlannedRoadmap.model_json_schema(),'')
    assert untyped==['.properties.assessment']

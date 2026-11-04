"""Synthetic scenario shared by the validator and flow tests. Wednesday 2030-01-09, 08:00 Singapore."""
from datetime import datetime, timezone

NOW=datetime(2030,1,9,0,0,tzinfo=timezone.utc)
OWNER='11111111-1111-4111-8111-111111111111'
BLOCKS=[{'day':0,'start_time':'19:00','duration_minutes':120,'kind':'preferred'},
    {'day':2,'start_time':'19:00','duration_minutes':90,'kind':'preferred'},
    {'day':5,'start_time':'10:00','duration_minutes':120,'kind':'preferred'},
    {'day':5,'start_time':'11:00','duration_minutes':120,'kind':'preferred'},
    {'day':6,'start_time':'09:00','duration_minutes':120,'kind':'backup'}]
def settings(**changes):
    return {'start_date':'2030-01-09','target_date':'2030-01-27','time_zone':'Asia/Singapore','weekly_minutes':300,'blocks':BLOCKS,
        'blackouts':[{'frequency':'once','start_date':'2030-01-12'}],'preferred_session_minutes':60,'learning_focus':['portfolio_work'],**changes}
def outcome(ref,status,shortfall=False):
    component={'dimension':'capability','status':'confirmed_shortfall' if shortfall else 'uncertain' if status!='supported' else 'supported','explanation':'Synthetic.','evidence_refs':[]}
    return {'ref':ref,'kind':'job_skill','name':ref.split(':')[1].title(),'match_status':status,'components':[component],'recommendation':None,'mapping_method':'canonical','mapping_reason':'Synthetic.'}
def assessment(input_hash='hash1'):
    return {'id':'assessment1','input_hash':input_hash,'role':'Developer','target_type':'specific_job','research_coverage':'no_findings',
        'job_skill_gaps':[outcome('job:python','confirmed_shortfall',True),outcome('job:sql','uncertain'),outcome('job:git','supported')],
        'interview_prep_gaps':[],'constraints':[{'ref':'condition:visa','name':'Work authorisation','match_status':'uncertain','components':[]}],
        'groups':[],'priorities':['job:python'],'evidence':{'cv:a':{'kind':'skill','name':'Git','text':'Declared project use.','attribution':'personal'},
            'cv:b':{'kind':'project','name':'Synthetic API','text':'Built an API.'}}}
def gap(id='python',**changes):
    return {'id':id,'name':'Python','requirement_ref':'job:python','source':'stated','inference_reason':None,'status':'confirmed_gap','priority':1,
        'plan_impact':'material','resolution':None,'confirmation_question':None,'rationale':'Required by the role and stated as a limitation.',**changes}
def milestone(key='m1',**changes):
    return {'key':key,'title':'Build a Python API','gap_ids':['python'],'prerequisite_keys':[],'estimated_minutes':240,'projected_start':'2030-01-09',
        'projected_end':'2030-01-20','demonstrable_outcome':'A small API running locally that you can walk through.',**changes}
def assignment(key='a1',**changes):
    return {'key':key,'milestone_key':'m1','gap_id':None,'kind':'study','date':'2030-01-09','start_time':'19:00','duration_minutes':60,
        'task':'Write one tested Python endpoint.','completion_criterion':'The endpoint test passes.',**changes}
def draft(**changes):
    return {'summary':'Build Python depth first.','gaps':[gap()],'milestones':[milestone()],'assignments':[assignment()],
        'deadline_outcome':{'summary':'You can show a working API by the target date.','achievable_by_target':['A working API'],'fits_in_runway':True},
        'beyond_deadline':[],'exclusions':[],**changes}

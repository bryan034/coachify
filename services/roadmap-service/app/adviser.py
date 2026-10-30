"""Suggestions change the draft. Only explicit user activation changes the active plan."""
from uuid import uuid5,NAMESPACE_URL
from pydantic import ValidationError
from elo_shared.runtime import Problem,stamp
from app.schemas import AdviserReply,Preferences
from app.scheduler import reschedule_plan

INSTRUCTIONS='''Act as a warm, practical personal career adviser. Work WITH the user on how to spend their time towards their chosen goal. Offer directions, choices, reasons and trade-offs from their actual skills, interests, learning preferences and availability. User priorities govern the proposed plan. Ask only a few relevant questions at a time; use saved inputs as suggestions and do not repeatedly ask resolved questions. Keep the conversation career-focused. Do not repeat capability-clarification interviews; explain uncertainty as a planning choice and route factual corrections to CV/Profile. You may answer questions without making changes.
Collect a projected preparation timeline (start plus readiness target, or explicit ongoing horizon), weekly hours, preferred days and comfortable session length. Dates, minutes and day budgets are proposed preferences, not employer facts. Use current_date and captured time_zone for relative dates. If supplied dates have elapsed, flag this and discuss a current goal/timeline instead of recommending a past deadline. Never invent a job start date; supplied job_dates contain original evidence and may be partial. Distinguish application/interview/start and recommend an earlier readiness target where useful, leaving the choice to the user. Null preference values mean keep the saved value. Weekdays are Monday=0 through Sunday=6. Convert hours to whole minutes, never overbook weekly budget. Never assume availability on unchosen days. Preserve reduced periods.
Propose small concrete activities with observable completion outcomes, effort estimates, learning rationale and valid assessment requirement_refs. Supported capabilities need no mandatory repeat work; uncertain capabilities may invite optional exploration, not compulsory remediation. Non-learning qualifications/eligibility/tenure cannot be replaced by courses. A user may choose personal development tasks with no requirement_refs. Avoid generic 'learn X' tasks and guaranteed readiness/employment. Label estimates and learning foundations in rationale. Reuse existing stable task IDs when editing, with a complete replacement definition. For NEW tasks use unique temporary keys. Return only changed/new task definitions; unchanged tasks are preserved by the backend. Never change completion status or capability evidence. Provide source correction guidance if a user reports new skills or a reduced claim.
Removal and scope exclusions require an exact quote from THIS user message explicitly requesting that choice. Return scope_inclusions with an exact current-message quote when the user wants to reconsider a previously excluded requirement. A missed task is not permission to delete it. Preserve unrelated tasks, completed work and user edits. Describe recommended changes and explain trade-offs. The backend computes daily allocations and feasibility; do not invent available hours, total fit or exact completion claims. The UI provides explicit Apply/Start actions. If insufficient time, discuss increasing time, changing target or user-chosen scope. Return the schema.'''

def propose(row,output,assessment,message,operation_id):
    draft=row.get('draft') or row.get('active') or {'tasks':[],'preferences':row.get('preferences',{}),'exclusions':[]}
    import copy
    plan=copy.deepcopy(draft)
    if not row.get('draft'):plan['base_active_id']=(row.get('active') or {}).get('id')
    preferences=Preferences.model_validate(plan.get('preferences',{})).model_dump(mode='json')
    patch=output.preferences.model_dump(mode='json')
    for key,value in patch.items():
        if key!='clear_target' and value is not None:preferences[key]=value
    if patch['clear_target']:preferences['target_date']=None
    try: preferences=Preferences.model_validate(preferences).model_dump(mode='json')
    except ValidationError:raise Problem('The proposed availability or timeline conflicts. Retry with clarified days and hours.',502,'planning_output') from None
    valid_refs={item['ref'] for key in ('job_skill_gaps','interview_prep_gaps','constraints') for item in assessment[key]}
    tasks=plan.get('tasks',[]); lookup={t['id']:t for t in tasks};changes=output.task_changes
    if len({t.id for t in changes})!=len(changes):raise Problem('The adviser duplicated a task identity.',502,'planning_output')
    mapped={t.id:t.id if t.id in lookup else str(uuid5(NAMESPACE_URL,operation_id+':task:'+t.id)) for t in changes}
    for definition in changes:
        data=definition.model_dump(); data['id']=mapped[definition.id]
        if not set(data['requirement_refs'])<=valid_refs:raise Problem('A suggested task referenced an unavailable assessment requirement.',502,'planning_output')
        data['prerequisites']=[mapped.get(key,key) for key in data['prerequisites']]
        previous=lookup.get(data['id']); data={**(previous or {}),**data,'status':previous.get('status','not_started') if previous else 'not_started',
            'provenance':previous.get('provenance','adviser_suggested') if previous else 'adviser_suggested'}
        if previous:
            if all(previous.get(k)==data.get(k) for k in type(definition).model_fields):continue
            data['history']=[*previous.get('history',[]),{'at':stamp(),'definition':{k:previous.get(k) for k in type(definition).model_fields}}]
            if previous['status']=='completed' and any(previous.get(k)!=data.get(k) for k in ('instructions','completion_outcome')):data['definition_review_required']=True
            tasks[tasks.index(previous)]=data
        else:tasks.append(data)
        lookup[data['id']]=data
    for removal in output.remove_tasks:
        if removal.task_id not in lookup or removal.quote not in message:raise Problem('Task removal needs an explicit request for that saved task.',502,'planning_output')
        lookup[removal.task_id].update(removed=True,removal_reason=removal.reason)
    exclusions={e['requirement_ref']:e for e in plan.get('exclusions',[])}
    for exclusion in output.scope_exclusions:
        if exclusion.requirement_ref not in valid_refs or exclusion.quote not in message:raise Problem('Scope changes need an explicit user request and a valid source.',502,'planning_output')
        exclusions[exclusion.requirement_ref]=exclusion.model_dump()
    for inclusion in output.scope_inclusions:
        if inclusion.requirement_ref not in valid_refs or inclusion.quote not in message:raise Problem('Reconsidering scope needs an explicit current request and a valid source.',502,'planning_output')
        exclusions.pop(inclusion.requirement_ref,None)
    for task in tasks:
        if not task.get('removed') and any(key not in lookup for key in task['prerequisites']):raise Problem('A task prerequisite references unknown work.',502,'planning_output')
    plan['assessment']={k:assessment[k] for k in ('id','input_hash','role','job_skill_gaps','interview_prep_gaps','constraints','groups','priorities','research_coverage','evidence')}
    plan.update(id=str(uuid5(NAMESPACE_URL,operation_id+':plan')),tasks=tasks,preferences=preferences,
        exclusions=list(exclusions.values()),assessment_id=assessment['id'],assessment_hash=assessment['input_hash'],created_at=stamp())
    plan['schedule']=reschedule_plan(plan)
    covered={ref for task in tasks if not task.get('removed') for ref in task['requirement_refs']}|set(exclusions)
    plan['unaddressed_requirements']=[ref for ref in assessment['priorities'] if ref not in covered]
    return plan

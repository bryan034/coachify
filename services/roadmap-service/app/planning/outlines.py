"""Outline-only generation, validation and owner-scoped revision lifecycle."""
import copy
import re
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, begin, digest, launch, operation_view, stamp
from app.planning.capacity import Capacity, merge, week_of
from app.planning.generator import MAX_ATTEMPTS, PLANNING_SECONDS, PLAN_MAX_TOKENS, reserved_sessions, set_stage
from app.planning.state import ASSESSMENT_FIELDS, completed_sessions, config_digest, planner_state, saved_config
from app.planning.validator import check_gaps, check_milestones, issue
from app.schemas.base import Mutation
from app.schemas.outlines import OutlineDraft, EditOutline
from app.schemas.roadmap import GeneratePlan, OperationAccepted, PlanDraft, PlannerConfig
from app.schemas.planner import Workspace

OUTLINE_INSTRUCTIONS='''Create a milestone outline for the user's career goal from the supplied assessment and capacity. Return milestones, prerequisite order, demonstrable outcomes, dates, effort and any beyond-deadline work. Do not create tasks. Material unknowns must have a diagnostic intent or a confirmation question; do not invent a skill gap. Include routine rules only where the user requested recurring practice; show weekdays, duration, topic progression and difficulty. Routine effort is included in its milestone estimate, not additional effort. Keep work within the runway and capacity. Preserve completed work and milestone keys. Exclusions require an exact quote from the user's instruction. Correct all validation errors when supplied.'''

def validate_outline(draft, capacity, assessment, confirmations, completed=(), instruction=None, existing=None, authorized_exclusions=()):
    # Existing validation can check gap provenance and milestone capacity independently of tasks.
    plan=PlanDraft.model_validate({**draft.model_dump(mode='json',exclude={'routine_rules'}),'assignments':[]})
    from app.planning.tasks import ensure_tasks
    tasks=ensure_tasks(copy.deepcopy(existing)) if existing else []
    allocated={};saved_effort={}
    for task in tasks:
        if not task.get('removed') and task.get('milestone_key'):
            key=task['milestone_key']
            saved_effort[key]=saved_effort.get(key,0)+task.get('estimated_minutes',0)
            allocated[key]=allocated.get(key,0)+sum(slot['duration_minutes'] for slot in task.get('schedule',[]))
    # Estimates cover already accepted work as well as remaining work. Reserve
    # saved slots in capacity once and validate only the unallocated effort.
    for milestone in plan.milestones:
        milestone.estimated_minutes=max(0,milestone.estimated_minutes-allocated.get(milestone.key,0))
    known_ids={task['id'] for task in tasks}
    retained={s['milestone_key'] for s in completed}
    work_markers=[*completed,*[{'milestone_key':key,'duration_minutes':minutes} for key,minutes in allocated.items()]]
    errors=check_milestones(plan,capacity,work_markers,retained)
    for milestone in draft.milestones:
        if saved_effort.get(milestone.key,0)>milestone.estimated_minutes:
            errors.append(issue('milestone_effort_below_saved_work',f"Milestone '{milestone.key}' estimates less effort than its saved tasks."))
    errors.extend(e for e in check_gaps(plan,assessment,confirmations,instruction,authorized_exclusions)
        if not (e['code']=='unresolved_material_unknown' and 'diagnostic assignment' in e['message']))
    if draft.gaps and not draft.milestones and not draft.beyond_deadline:
        errors.append(issue('no_milestones','Define milestones for the gaps you identified.'))
    lookup={m.key:m for m in draft.milestones}
    for old in (existing or {}).get('milestones',[]):
        current=lookup.get(old['key'])
        for checkpoint in old.get('checkpoints',[]):
            if checkpoint.get('reached_at'):
                match=next((c for c in current.checkpoints if c.key==checkpoint['key']),None) if current else None
                if not match or match.title!=checkpoint['title'] or str(match.date)!=str(checkpoint['date']):
                    errors.append(issue('checkpoint_progress_conflict',f"Keep reached checkpoint '{checkpoint['key']}' unchanged; it is part of saved progress."))
    for m in draft.milestones:
        outcome=m.demonstrable_outcome.strip().rstrip('.!').lower()
        if re.fullmatch(r'(?:learn|understand|know|study|master) [\w +#.-]+',outcome):
            errors.append(issue('milestone_outcome_generic',f"Milestone '{m.key}' needs a demonstrable outcome, such as a project, explanation or working example."))
        for key in m.prerequisite_keys:
            if key in lookup and lookup[key].projected_end>m.projected_start:
                errors.append(issue('prerequisite_order',f"Milestone '{m.key}' begins before prerequisite '{key}' ends."))
    ids=set(); daily={}; weekly={}; effort={}; month_counts={}
    for rule in draft.routine_rules:
        if rule.id in ids:errors.append(issue('duplicate_routine',f"Routine '{rule.id}' is duplicated."))
        ids.add(rule.id); milestone=lookup.get(rule.milestone_key)
        for topic in rule.topic_progression or ['']:
            title=' '.join(part.strip() for part in (rule.activity,rule.difficulty,topic) if part.strip())
            if len(title)>160 or len(title.split())>19:
                errors.append(issue('routine_title',f"Shorten routine '{rule.id}' activity, difficulty or topic to fit a task title."));break
        if not milestone:
            errors.append(issue('unknown_milestone',f"Routine '{rule.id}' must reference an outline milestone."));continue
        if rule.start_date<milestone.projected_start or rule.end_date>milestone.projected_end:
            errors.append(issue('routine_outside_milestone',f"Routine '{rule.id}' must fit within its milestone dates."))
        if (rule.end_date-rule.start_date).days>366:
            errors.append(issue('routine_too_long',f"Routine '{rule.id}' exceeds one year."));continue
        day=rule.start_date
        while day<=rule.end_date:
            ident=str(uuid5(NAMESPACE_URL,'roadmap:routine:'+rule.id+':'+day.isoformat()))
            if day.weekday() in rule.weekdays and day>=capacity.start and ident not in known_ids:
                month=(day.year,day.month);month_counts[month]=month_counts.get(month,0)+1
                effort[rule.milestone_key]=effort.get(rule.milestone_key,0)+rule.duration_minutes
                daily[day]=daily.get(day,0)+rule.duration_minutes
                week=week_of(day);weekly[week]=weekly.get(week,0)+rule.duration_minutes
                windows=capacity.days.get(day,{'preferred':[],'backup':[]})
                allowed=merge([*windows['preferred'],*(windows['backup'] if capacity.config.use_backup else [])])
                if not any(high-low>=rule.duration_minutes for low,high in allowed):
                    errors.append(issue('routine_conflict',f"Routine '{rule.id}' does not fit an available window on {day}. Adjust its days, duration or availability."))
            day+=timedelta(days=1)
    for (year,month),count in month_counts.items():
        if count>100:errors.append(issue('routine_month_capacity',f'Routines create {count} tasks in {year:04d}-{month:02d}; reduce their frequency below the monthly limit.'))
    for day,minutes in daily.items():
        if minutes>capacity.between(day,day):errors.append(issue('routine_conflict',f'Routines need {minutes} minutes on {day}, exceeding available capacity. Adjust the routines or availability.'))
    for week,minutes in weekly.items():
        if minutes>capacity.week_left(week):errors.append(issue('routine_conflict',f'Routines need {minutes} minutes in the week of {week}, exceeding the weekly budget.'))
    for key,minutes in effort.items():
        if minutes>max(0,lookup[key].estimated_minutes-allocated.get(key,0)):errors.append(issue('routine_effort_exceeds_milestone',f"Routine effort for '{key}' exceeds the milestone estimate. Increase the estimate or adjust the routine."))
    return errors[:100]

def outline_reservations(plan):
    from app.planning.tasks import ensure_tasks
    if not plan:return []
    return [dict(slot) for task in ensure_tasks(copy.deepcopy(plan)) if not task.get('removed') for slot in task.get('schedule',[])]

def authorized_exclusions(outline):
    # The saved outline was validated on generation against the user's original message.
    return {(e['requirement_ref'],e['quote']) for e in (outline or {}).get('exclusions',[])}

def draft_from_outline(outline):
    fields=('summary','gaps','milestones','routine_rules','deadline_outcome','beyond_deadline','exclusions')
    data={k:copy.deepcopy(outline[k]) for k in fields}
    for m in data['milestones']:
        m.pop('id',None);m.pop('outcome',None)
        for checkpoint in m.get('checkpoints',[]):checkpoint.pop('reached_at',None)
    return OutlineDraft.model_validate(data)

def build_outline(draft,result,config,first_week,operation_id,attempts,active,confirmations,progress_plan=None):
    data=draft.model_dump(mode='json')
    previous={m['key']:m for m in (active or {}).get('milestones',[])}
    previous.update({m['key']:m for m in (progress_plan or {}).get('milestones',[])})
    old_rules={r['id']:r for r in (active or {}).get('routine_rules',[])}
    for rule in data['routine_rules']:
        old=old_rules.get(rule['id'])
        if old:
            before={k:v for k,v in old.items() if k!='revision'}
            after={k:v for k,v in rule.items() if k!='revision'}
            rule['revision']=old.get('revision',1)+(before!=after)
        else:rule['revision']=1
    for m in data['milestones']:
        old=previous.get(m['key'],{});outcome=copy.deepcopy(old.get('outcome') or {'demonstrated':False})
        if outcome.get('demonstrated') and old.get('demonstrable_outcome')!=m['demonstrable_outcome']:
            outcome['definition_review_required']=True;outcome.setdefault('previous_definition',old.get('demonstrable_outcome'))
        old_checkpoints={c['key']:c for c in old.get('checkpoints',[])}
        for checkpoint in m.get('checkpoints',[]):
            previous_checkpoint=old_checkpoints.get(checkpoint['key']) or {}
            if previous_checkpoint.get('reached_at') and previous_checkpoint.get('title')==checkpoint['title'] and str(previous_checkpoint.get('date'))==str(checkpoint['date']):
                checkpoint['reached_at']=previous_checkpoint['reached_at']
        m.update(id=m['key'],outcome=outcome)
    return {**data,'id':str(uuid5(NAMESPACE_URL,operation_id+':outline')),'revision':(active or {}).get('revision',0)+1,
        'status':'preview','assessment_id':result['id'],'assessment_hash':result['input_hash'],
        'assessment':{k:result.get(k) for k in ASSESSMENT_FIELDS},'config':config.model_dump(mode='json'),
        'config_hash':config_digest(config),'confirmations_hash':digest(confirmations),'base_active_id':(active or {}).get('id'),
        'base_progress_hash':digest(progress_plan),
        'created_at':stamp(),'first_planning_week':first_week,'generation':{'prompt_version':'roadmap-outline-v1','attempts':attempts}}

async def prepare_outline(app,row,account,assess,read_context,*,config=None,instruction=None,user_message=None):
    owner=account['id'];state=planner_state(row);config=config or saved_config(state);operation_id=row['pending']['id']
    await set_stage(app,row,owner,'assessing')
    result=await assess(account,operation_id,row['pending']['body'].get('allow_partial_assessment',False))
    source=await read_context(account)
    if not source['ready'] or source.get('input_hash')!=result['input_hash']:raise Problem('Your selected inputs changed. Refresh before planning.',409,'inputs_changed')
    await set_stage(app,row,owner,'writing')
    state=planner_state(row);active=state['active'];accepted=state['outline_active'];confirmations=state['confirmations'];now=app.state.clock()
    completed=completed_sessions(active);capacity=Capacity(config,now,outline_reservations(active))
    report=capacity.report(allow_past_start=bool(active or accepted))
    if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
    context={'current_date':capacity.today.isoformat(),'time_zone':config.time_zone,'goal':source['goal'],
        'assessment':{k:result.get(k) for k in ASSESSMENT_FIELDS},'settings':config.model_dump(mode='json'),
        'runway':{k:report[k] for k in ('calendar','study')},'weekly_capacity':report['weeks'],
        'completed_work':completed,'confirmations':confirmations,'current_outline':state['outline_candidate'] or accepted,
        'instruction':instruction,'user_message':user_message}
    errors=[];previous=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        request={**context,'attempt':attempt}
        if errors:
            await set_stage(app,row,owner,'correcting');request.update(validation_errors=errors,previous_output=previous)
        draft=await app.state.model.generate(OutlineDraft,OUTLINE_INSTRUCTIONS,request,max_tokens=PLAN_MAX_TOKENS)
        errors=validate_outline(draft,capacity,result,confirmations,completed,user_message,active,authorized_exclusions(state['outline_candidate'] or accepted))
        if not errors:break
        previous=draft.model_dump(mode='json')
    else:raise Problem(('Could not produce a valid outline. '+' '.join(e['message'] for e in errors[:3]))[:1500],502,'outline_validation')
    latest=await app.state.upstream.account(account['token']);fresh=await read_context(latest)
    if latest['id']!=owner:raise Problem('Your account changed while preparing this outline.',401,'session')
    if fresh.get('input_hash')!=source['input_hash']:raise Problem('Your evidence or goal changed. Retry with the latest inputs.',409,'inputs_changed')
    planner_state(row)['config']=config.model_dump(mode='json')
    planner_state(row)['outline_candidate']=build_outline(draft,result,config,report['first_planning_week'],operation_id,attempt,accepted,confirmations,active)
    row['assessment']={k:result.get(k) for k in ASSESSMENT_FIELDS}

def register_outline_routes(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner/outlines'
    @app.post(prefix+'/generate',status_code=202,response_model=OperationAccepted)
    async def generate(body:GeneratePlan,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        repeated=any(r['id']==str(body.mutation_id) for r in row['receipts']) or (row.get('pending') or {}).get('id')==str(body.mutation_id)
        if not repeated:
            source=await context(account)
            if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
            report=Capacity(saved_config(state),app.state.clock(),completed_sessions(state['active'])).report(allow_past_start=bool(state['active'] or state['outline_active']))
            if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
        row=await thread(begin,app.state.store,account['id'],body,'outline_generate',PLANNING_SECONDS,True)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}
    @app.patch(prefix+'/{identifier}',response_model=Workspace)
    async def edit(identifier:str,body:EditOutline,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row);candidate=state['outline_candidate'];active=state['outline_active']
            original=candidate if candidate and candidate['id']==identifier else active if active and active['id']==identifier else None
            if not original:raise Problem('This outline was not found.',404,'not_found')
            if source.get('input_hash')!=original['assessment_hash'] or config_digest(saved_config(state))!=original['config_hash']:
                raise Problem('Planning inputs changed. Generate a fresh outline.',409,'inputs_changed')
            capacity=Capacity(PlannerConfig.model_validate(original['config']),app.state.clock(),outline_reservations(state['active']))
            errors=validate_outline(body.outline,capacity,original['assessment'],state['confirmations'],completed_sessions(state['active']),existing=state['active'],authorized_exclusions=authorized_exclusions(original))
            if errors:raise Problem(' '.join(e['message'] for e in errors[:3]),422,errors[0]['code'])
            state['outline_candidate']=build_outline(body.outline,original['assessment'],PlannerConfig.model_validate(original['config']),original['first_planning_week'],str(body.mutation_id),0,active,state['confirmations'],state['active'])
            return row
        return await mutate(body,account,apply,operation='outline.edit:'+identifier)
    @app.post(prefix+'/{identifier}/accept',response_model=Workspace)
    async def accept(identifier:str,body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row);candidate=state['outline_candidate'];active=state['outline_active']
            if not candidate or candidate['id']!=identifier:raise Problem('This outline preview was not found.',404,'not_found')
            if not source.get('ready') or source.get('input_hash')!=candidate['assessment_hash'] or config_digest(saved_config(state))!=candidate['config_hash'] or digest(state['confirmations'])!=candidate['confirmations_hash'] or (active or {}).get('id')!=candidate['base_active_id']:
                raise Problem('The outline inputs changed. Generate a fresh preview.',409,'inputs_changed')
            if candidate['base_progress_hash']!=digest(state['active']):
                raise Problem('Your saved progress changed. Review a fresh outline preview.',409,'progress_changed')
            capacity=Capacity(PlannerConfig.model_validate(candidate['config']),app.state.clock(),outline_reservations(state['active']))
            errors=validate_outline(draft_from_outline(candidate),capacity,candidate['assessment'],state['confirmations'],completed_sessions(state['active']),existing=state['active'],authorized_exclusions=authorized_exclusions(candidate))
            if errors:raise Problem(' '.join(e['message'] for e in errors[:3]),409,errors[0]['code'])
            if active:
                history=state.setdefault('outline_history',[])
                if len(history)>=100:raise Problem('This workspace reached its outline revision capacity.',413,'workspace_capacity')
                history.append(copy.deepcopy(active))
                # Only future blocks intersecting a changed milestone or routine need review.
                def indexed(items,key):return {item[key]:item for item in items}
                def clean(item):return {k:v for k,v in item.items() if k not in ('id','revision','outcome')}
                changed=[]
                for field,key in (('milestones','key'),('routine_rules','id')):
                    before=indexed(active.get(field,[]),key);after=indexed(candidate.get(field,[]),key)
                    for ident in before.keys()|after.keys():
                        old=before.get(ident);new=after.get(ident)
                        if old is None or new is None or clean(old)!=clean(new):
                            for item in (old,new):
                                if item:changed.append((item.get('projected_start',item.get('start_date')),item.get('projected_end',item.get('end_date'))))
                today=Capacity(PlannerConfig.model_validate(candidate['config']),app.state.clock()).today.isoformat()
                for block in state.get('month_blocks',[]):
                    if block.get('end_exclusive','')>today and any(first and last and first<block.get('end_exclusive','') and last>=block.get('start_date','') for first,last in changed):
                        block['needs_review']=True
            candidate['status']='accepted';candidate['accepted_at']=stamp();state['outline_active']=candidate;state['outline_candidate']=None
            return row
        return await mutate(body,account,apply,operation='outline.accept:'+identifier)

"""Previews of changes to an accepted roadmap. Nothing here touches the plan until a proposal is accepted.

Each proposal holds the changed fields of a private copy. Accepting applies them in one write, and only
if the plan has not changed since the proposal was prepared.
"""
from datetime import date, timedelta
from uuid import NAMESPACE_URL, uuid5
from elo_shared.runtime import Problem
from app.planning.capacity import normalized, split_buffer, week_of
from app.planning.metrics import Forecast, milestone_totals, pace, plan_budget_minutes, projection
from app.planning.schedule import add_event, by_id, config_of, day_of, future_weeks, paused_weeks, placed, plan_capacity, private_copy, replan_future, to_backlog
from app.planning.state import config_digest

PATCH_FIELDS=('config','config_hash','assignments','outline','milestones','deferred_scope','week_states','deadline_outcome')

def proposal_id(key):
    return str(uuid5(NAMESPACE_URL,f'proposal:{key}'))
def build_proposal(before,after,kind,now,key,summary,*,message=None,week=None,moved=(),backlogged=(),added=(),removed=(),decisions=(),warnings=(),**extra):
    old=projection(before,now);new=projection(after,now)
    effect={'summary':summary,'finish_before':old['projected_finish'],'finish_after':new['projected_finish'],'target_before':old['target_date'],'target_after':new['target_date'],
        'capacity_before_minutes':plan_budget_minutes(before,now),'capacity_after_minutes':plan_budget_minutes(after,now),'tasks_moved':list(moved),'tasks_backlogged':list(backlogged),
        'tasks_added':list(added),'tasks_removed':list(removed),'decisions':list(decisions),'warnings':list(warnings),'week_start':week,**extra}
    return {'id':proposal_id(key),'kind':kind,'base_revision':before.get('revision',0),'created_at':now.isoformat(),'message':message,'week_start':week,'effect':effect,
        'patch':{field:after[field] for field in PATCH_FIELDS if field in after and after[field]!=before.get(field)}}
def overflow_warning(plan,now):
    view=projection(plan,now)
    if view['fits_target']:return []
    return [f"About {view['remaining_active_minutes']/60:g} hours of accepted work remain, and they won't all fit before {view['target_date']} on this schedule. Consider Cut scope or Move the date."]

def align_outline(plan,now):
    """Keep one outline row per week through the target date. New rows reuse the plan's own milestones."""
    capacity=plan_capacity(plan,now);target=capacity.target
    open_milestones=[m for m in plan['milestones'] if not m.get('completion')]
    rows={row['week_start']:row for row in plan.get('outline',[])}
    result=[];start=week_of(date.fromisoformat(str(plan['config']['start_date'])))
    first=min([start,*[date.fromisoformat(k) for k in rows]]) if rows else start
    week=first
    while week<=target:
        key=week.isoformat();planned=capacity.week_minutes(week)[1];row=rows.get(key)
        if row:
            result.append({**row,'target_minutes':min(row['target_minutes'],planned) if week>=week_of(capacity.today) else row['target_minutes']})
        elif week>=week_of(capacity.today):
            lead=open_milestones[-1] if open_milestones else None
            result.append({'week_start':key,'theme':f"Continue: {lead['title']}" if lead else 'Catch up and consolidate','milestone_keys':[lead['key']] if lead else [],'target_minutes':planned,
                'expected_output':lead['demonstrable_outcome'] if lead else 'Finish anything left over.'})
        week+=timedelta(days=7)
    plan['outline']=result
def clamp_milestones(plan):
    target=str(plan['config']['target_date'])
    for milestone in plan['milestones']:
        if str(milestone['projected_end'])>target:milestone['projected_end']=target
        if str(milestone['projected_start'])>target:milestone['projected_start']=target

def pause_proposal(plan,week,now,key):
    capacity=plan_capacity(plan,now);current=week_of(capacity.today)
    if week<current or week>capacity.target:raise Problem('Choose this week or a later week before your target date.',409,'pause_invalid')
    code=week.isoformat()
    if code in paused_weeks(plan):raise Problem('That week is already paused.',409,'pause_invalid')
    after=private_copy(plan)
    after.setdefault('week_states',{}).setdefault(code,{}).update(paused=True)
    last=week+timedelta(days=6);decisions=[]
    for task in after['assignments']:
        if placed(task) and week<=day_of(task)<=last and (task['origin']=='custom' or task.get('pinned')):
            decisions.append({'task_id':task['id'],'title':task['task'],'date':str(task['date']),'start_time':task['start_time'],'origin':task['origin']})
    moved,sent=replan_future(after,now)
    align_outline(after,now)
    return build_proposal(plan,after,'pause',now,key,f'Pause the week of {code}. Its automatic planning capacity becomes zero and your target date stays the same.',week=code,moved=moved,backlogged=sent,decisions=decisions,warnings=overflow_warning(after,now))
def unpause_proposal(plan,week,now,key):
    code=week.isoformat()
    if code not in paused_weeks(plan):raise Problem('That week isn’t paused.',409,'pause_invalid')
    after=private_copy(plan);after['week_states'][code].update(paused=False,exception_task_ids=[])
    return build_proposal(plan,after,'unpause',now,key,f'Restore the week of {code}. Rolling detail fills it when it enters your two-week window.',week=code)

def apply_config(plan,config,now):
    """A private copy using new settings. Generated tasks that no longer fit are re-placed."""
    after=private_copy(plan)
    after['config']=config.model_dump(mode='json');after['config_hash']=config_digest(config)
    moved,sent=replan_future(after,now)
    custom_late=[]
    target=str(after['config']['target_date'])
    for task in after['assignments']:
        if placed(task) and task['origin']=='custom' and str(task['date'])>target:
            to_backlog(after,task,'Your new target date is before this task.',now,'replanned');custom_late.append(task['task'])
    align_outline(after,now);clamp_milestones(after)
    return after,moved,[*sent,*custom_late]
def edit_proposal(plan,config,now,key):
    capacity=plan_capacity(plan,now);config=normalized(config,capacity.today)
    report=type(capacity)(config,now,[t for t in plan['assignments'] if t['status']=='completed'],paused_weeks(plan)).report(allow_past_start=True)
    if report['issues']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'edit_invalid')
    after,moved,sent=apply_config(plan,config,now)
    return build_proposal(plan,after,'edit',now,key,'Update this roadmap’s settings. Your progress and history stay as they are.',moved=moved,backlogged=sent,warnings=overflow_warning(after,now))

def cut_scope(plan,now,key):
    view=projection(plan,now);recent=pace(plan,now)['recent']
    room=plan_budget_minutes(plan,now)
    if recent['status']=='available' and recent['weekly_minutes'] is not None:
        weeks=len([w for w in future_weeks(plan,now)]);room=min(room,recent['weekly_minutes']*weeks)
    excess=view['remaining_active_minutes']-room
    if excess<=0:raise Problem('Your remaining work already fits before your target date, so nothing needs cutting.',409,'nothing_to_cut')
    after=private_copy(plan);totals=milestone_totals(after);removed=[];cut=[]
    depends=lambda key:any(key in m['prerequisite_keys'] for m in after['milestones'])
    linked=lambda key:[t for t in after['assignments'] if t.get('milestone_key')==key]
    for milestone in sorted(after['milestones'],key=lambda m:(str(m['projected_end']),m['key']),reverse=True):
        if excess<=0:break
        code=milestone['key']
        if milestone.get('completion') or totals[code]['done'] or depends(code):continue
        if any(t.get('pinned') or t['origin']=='custom' for t in linked(code)):continue
        minutes=totals[code]['planned']
        after['milestones'].remove(milestone)
        after['deferred_scope'].append({'id':f'deferred-{code}','key':code,'title':milestone['title'],'gap_ids':milestone['gap_ids'],'reason':'Moved beyond your target date so the remaining work fits.','estimated_minutes':minutes,'dependencies':milestone['prerequisite_keys'],'source_milestone':milestone})
        for task in linked(code):
            if task['status'] in ('scheduled','backlog'):
                task.update(status='removed',removed_reason='scope_cut',action_needed=None);removed.append(task['task'])
        for row in after.get('outline',[]):
            if code in row['milestone_keys']:row['milestone_keys'].remove(code)
        cut.append(milestone['title']);excess-=minutes
    if not cut:raise Problem('No remaining milestone can be cut without touching completed, pinned or custom work, or a milestone that depends on it.',409,'nothing_to_cut')
    after['deadline_outcome']={**after['deadline_outcome'],'fits_in_runway':False}
    return build_proposal(plan,after,'pace_cut_scope',now,key,'Move '+', '.join(cut)+' to deferred scope so the rest fits before your target date.',removed=removed,warnings=overflow_warning(after,now))
def add_hours(plan,extra,now,key):
    if not extra:raise Problem('Choose how much time to add each week.',422,'validation')
    config=config_of(plan).model_copy(update={'weekly_minutes':(config_of(plan).weekly_minutes or 0)+extra})
    after,moved,sent=apply_config(plan,config,now)
    capacity=plan_capacity(plan,now);week=week_of(capacity.today)+timedelta(days=7)
    gained=plan_capacity(after,now).between(week,week+timedelta(days=6))-capacity.between(week,week+timedelta(days=6))
    short=gained<extra
    warnings=[*(['Your study blocks can’t hold all of that time. Add a study block in Edit plan to use it.'] if short else []),*overflow_warning(after,now)]
    return build_proposal(plan,after,'pace_add_hours',now,key,f'Raise your weekly maximum by {extra/60:g} hours.',moved=moved,backlogged=sent,warnings=warnings,add_block_suggested=short)
def move_date(plan,target,now,key):
    current=date.fromisoformat(str(plan['config']['target_date']))
    if not target:
        view=pace(plan,now)['recent'];suggested=view.get('finish_date') or projection(plan,now)['scheduled_finish']
        target=date.fromisoformat(suggested) if suggested else None
    if not target or target<=current:raise Problem('Choose a target date after your current one.',409,'date_invalid')
    capacity=plan_capacity(plan,now)
    if (target-date.fromisoformat(str(capacity.start_date))).days>366:raise Problem('Plan at most one year at a time.',409,'date_invalid')
    config=config_of(plan).model_copy(update={'target_date':target,'duration':None})
    after,moved,sent=apply_config(plan,config,now)
    return build_proposal(plan,after,'pace_move_date',now,key,f'Move your target date to {target}.',moved=moved,backlogged=sent,warnings=overflow_warning(after,now))
def scope_proposal(plan,deferred_id,target,now,key):
    item=next((d for d in plan.get('deferred_scope',[]) if d['id']==deferred_id),None)
    if not item:raise Problem('This deferred work was not found.',404,'not_found')
    waiting=[d['title'] for d in plan['deferred_scope'] if d['key'] in item.get('dependencies',[])]
    if waiting:raise Problem('Bring '+', '.join(waiting)+' into your roadmap first; this work depends on it.',409,'dependency_deferred')
    after=private_copy(plan)
    if target:
        current=date.fromisoformat(str(plan['config']['target_date']))
        if target<=current:raise Problem('Choose a target date after your current one.',409,'date_invalid')
        config=config_of(plan).model_copy(update={'target_date':target,'duration':None})
        after['config']=config.model_dump(mode='json');after['config_hash']=config_digest(config)
    capacity=plan_capacity(after,now);end=str(capacity.target);begin=str(max(capacity.today,capacity.start_date))
    milestone=item.get('source_milestone') or {'id':item['key'],'key':item['key'],'title':item['title'],'gap_ids':item['gap_ids'],'prerequisite_keys':item.get('dependencies',[]),'demonstrable_outcome':item['reason'],'outcome':{'demonstrated':False},'completion':None}
    after['milestones'].append({**milestone,'estimated_minutes':item['estimated_minutes'],'projected_start':begin,'projected_end':end})
    after['deferred_scope']=[d for d in after['deferred_scope'] if d['id']!=deferred_id]
    if not after['deferred_scope']:after['deadline_outcome']={**after['deadline_outcome'],'fits_in_runway':True}
    for task in after['assignments']:
        if task['status']=='removed' and task.get('removed_reason')=='scope_cut' and task.get('milestone_key')==item['key']:
            task.update(status='backlog',date=None,start_time=None,removed_reason=None,backlog_reason='Back in your roadmap. Choose a time for it.')
    align_outline(after,now)
    for row in reversed(after['outline']):
        if item['key'] not in row['milestone_keys']:row['milestone_keys'].append(item['key'])
        break
    return build_proposal(plan,after,'scope',now,key,f"Bring “{item['title']}” into your active roadmap.",warnings=overflow_warning(after,now))

def proposal_blockers(state,now):
    proposal=state.get('proposal');active=state.get('active')
    if not proposal:return []
    if not active or active.get('revision',0)!=proposal['base_revision']:
        return [{'code':'proposal_stale','message':'Your roadmap changed after this preview was prepared. Prepare a fresh preview.'}]
    if proposal['kind']=='checkin':
        from app.planning.checkin import expiry
        capacity=plan_capacity(active,now);week=date.fromisoformat(proposal['week_start'])
        if (capacity.today,capacity.now_minute)>=expiry(active,week):
            return [{'code':'checkin_expired','message':'This check-in has closed, so its proposal can no longer apply. Your workload target is unchanged.'}]
    return []
EVENTS={'pause':'pause','unpause':'unpause','pace_cut_scope':'scope_change','pace_add_hours':'plan_edit','pace_move_date':'plan_edit','edit':'plan_edit','scope':'scope_change','checkin':'checkin_applied','revision':'revision_applied'}
def apply_proposal(state,keep_task_ids,now):
    """Accept the current proposal: hours, tasks and settings change in this one write."""
    plan=state['active'];proposal=state['proposal'];patch=proposal['patch']
    before={t['id']:t for t in plan['assignments']}
    plan.update(patch)
    for task in plan['assignments']:
        old=before.get(task['id'])
        if task['status']=='scheduled' and task.get('date') and (not old or str(old.get('date'))!=str(task['date']) or old.get('start_time')!=task.get('start_time')):
            task['baseline']=f"{task['date']} {task['start_time']}"
    if 'config' in patch:state['config']=patch['config']
    if proposal['kind']=='pause':
        row=plan['week_states'][proposal['week_start']]
        row['exception_task_ids']=[]
        for decision in proposal['effect']['decisions']:
            task=by_id(plan,decision['task_id'])
            if task['id'] in keep_task_ids:row['exception_task_ids'].append(task['id'])
            elif task['status']=='scheduled':to_backlog(plan,task,'Moved out of a paused week. Choose a new time.',now,'paused')
    plan['revision']=plan.get('revision',0)+1
    add_event(plan,f"proposal:{proposal['id']}",EVENTS[proposal['kind']],now,proposal['effect']['summary'])
    if proposal['kind']=='checkin':
        record=plan.setdefault('checkins',{}).setdefault(proposal['week_start'],{})
        record.update(status='completed',completed_at=now.isoformat(),applied=True)
    state['proposal']=None

"""To-do sessions: the roadmap page's read model, and the rules for adding, editing, moving and skipping them.

A session is one scheduled slot of an editable task, or the day of a task without a set time.
Editable tasks stay the saved record; nothing here is stored separately.
"""
from datetime import date, timedelta
from uuid import NAMESPACE_URL, uuid5
from elo_shared.runtime import Problem, stamp
from elo_shared.skills import normalize, resolve
from app.planning.capacity import Capacity, merge, subtract, to_clock, to_minute, week_of
from app.planning.milestone_membership import mark_membership_review
from app.planning.tasks import ensure_tasks, gap_skill, requirement_ids, validate_links
from app.schemas.roadmap import PlannerConfig

STEP=15
SKIP_REASON='Skipped missed session.'

def calendar(plan,now):
    return Capacity(PlannerConfig.model_validate(plan['config']),now)

def slot_id(task,index):
    return task['id'] if not index else str(uuid5(NAMESPACE_URL,task['id']+':slot:'+str(index)))

def task_day(task,index):
    """The local date of one session, as text."""
    return str(task['anytime_date']) if index is None else str(task['schedule'][index]['date'])

def effective_skills(plan,task,linked=None):
    """Chosen skills, or the single gap the task's requirement link resolves to."""
    if task.get('skills') is not None:return task['skills']
    gaps={gap['id']:gap for gap in plan.get('gaps',[])}
    return [gap_skill(plan,gaps[key]) for key in (linked or {}).get('skill_gap_ids') or [] if key in gaps]

def session_views(plan,now):
    """One row per session of every current task. Expects a plan whose assignments were just projected."""
    today=calendar(plan,now).today.isoformat()
    projected={item['id']:item for item in plan.get('assignments',[])}
    rows=[]
    for task in ensure_tasks(plan):
        if task.get('removed'):continue
        places=[(index,str(slot['date']),slot['start_time'],slot['duration_minutes']) for index,slot in enumerate(task.get('schedule') or [])]
        if not places and task.get('anytime_date'):places=[(None,str(task['anytime_date']),None,task['estimated_minutes'])]
        source=task.get('source_assignment') or {};original=task.get('original');rating=task.get('self_rating') or {}
        done=task['status']=='completed'
        edited=bool(original and (original['title']!=task['title'] or original['completion_outcome']!=task['completion_outcome']))
        for index,day,start,minutes in places:
            ident=slot_id(task,index)
            rows.append({'id':ident,'task_id':task['id'],'title':task['title'],'instructions':task['instructions'],
                'completion_criterion':task['completion_outcome'],'date':day,'start_time':start,'duration_minutes':minutes,
                'status':'completed' if done else 'scheduled','completed_at':task.get('completed_at'),'missed':not done and day<today,
                'origin':task.get('origin','generated'),'kind':source.get('kind') or 'study','milestone_key':task.get('milestone_key'),
                'skills':effective_skills(plan,task,projected.get(ident)),'edited':edited,
                'original':{'title':original['title'],'completion_criterion':original['completion_outcome']} if edited else None,
                'notes':task.get('notes'),'confidence':rating.get('confidence'),'difficulty':rating.get('difficulty'),'rated_at':rating.get('recorded_at'),
                'moved_from_backlog':bool(task.get('backlog_moved_at')),'slots':max(len(places),1)})
    return sorted(rows,key=lambda row:(row['date'],row['start_time'] or '99:99',row['title']))

def locate(plan,session_id):
    """The task and slot index behind a session id; the index is None for an anytime task."""
    for task in ensure_tasks(plan):
        if task.get('removed'):continue
        slots=task.get('schedule') or []
        if not slots and task.get('anytime_date') and task['id']==session_id:return task,None
        for index in range(len(slots)):
            if slot_id(task,index)==session_id:return task,index
    raise Problem('This task was not found in your active roadmap.',404,'not_found')

def record_edit(task,previous):
    """History and override bookkeeping shared with the task edit route."""
    if not previous:return
    task.setdefault('history',[]).append({'at':stamp(),'event':'edited','fields':list(previous),'previous':previous})
    task['overrides']=sorted(set(task.get('overrides',[]))|set(previous))

# Skills

def known_skills(plan,source):
    """Skills a task may name: this plan's gaps, then the Skills Profile as assessed and as currently saved."""
    found={}
    for gap in plan.get('gaps',[]):found.setdefault(normalize(gap['name']),gap_skill(plan,gap))
    def add(name,identifier=None):
        if name:found.setdefault(normalize(name),{'name':name[:160],'canonical_skill_id':identifier or resolve(name),'gap_id':None})
    for item in ((plan.get('assessment') or {}).get('skill_profile') or {}).get('skills') or []:add(item.get('name'),item.get('canonical_skill_id'))
    for record in ((source or {}).get('evidence') or {}).values():
        if record.get('kind') in ('skill','user_declaration'):add(record.get('name'),record.get('canonical_skill_id'))
    return found

def choose_skills(plan,source,names,current=()):
    """Resolve submitted names. A skill the task already has stays valid if its source is unavailable."""
    known=known_skills(plan,source);kept={normalize(skill['name']):skill for skill in current or ()};chosen={}
    for name in names:
        key=normalize(name)
        skill=known.get(key) or kept.get(key)
        if not skill:raise Problem('Choose skills from this plan or your Skills Profile.',422,'validation')
        chosen.setdefault(key,skill)
    return list(chosen.values())

def link_own_task(plan,task):
    """A user's task follows its plan skills: their requirements, and the first one's milestone."""
    gaps={gap['id']:gap for gap in plan.get('gaps',[])};known=requirement_ids(plan)
    linked=[gaps[skill['gap_id']] for skill in task.get('skills') or [] if skill.get('gap_id') in gaps]
    before=task.get('milestone_key')
    task['requirement_refs']=list(dict.fromkeys(gap['requirement_ref'] for gap in linked if gap.get('requirement_ref') in known))
    task['requirement_source_hash']=plan.get('assessment_hash');task['requirement_source_id']=plan.get('assessment_id')
    task['milestone_key']=next((m['key'] for gap in linked[:1] for m in plan.get('milestones',[]) if gap['id'] in m.get('gap_ids',[])),None)
    validate_links(plan,task)
    if before!=task['milestone_key']:mark_membership_review(plan,[before,task['milestone_key']])

# Time

def busy_on(plan,day,skip=None):
    """Scheduled time of every current task on a day, except the one session being placed."""
    spans=[]
    for task in ensure_tasks(plan):
        if task.get('removed'):continue
        for index,slot in enumerate(task.get('schedule') or []):
            if str(slot['date'])!=day.isoformat() or skip==(task['id'],index):continue
            begin=to_minute(slot['start_time']);spans.append((begin,begin+slot['duration_minutes'],task['title']))
    return spans

def check_time(plan,capacity,task,index,day,start,minutes,*,strict,allow_overlap=False):
    """Reject a time the day cannot hold. Moves are strict; a detail edit may keep a past time or a confirmed overlap."""
    begin=to_minute(start);end=begin+minutes
    if end>1440:raise Problem('A task must end by midnight. Choose an earlier start or a shorter duration.',422,'validation')
    upcoming=day>capacity.today or (day==capacity.today and begin>=capacity.now_minute)
    if strict and not upcoming:raise Problem('That time has already passed. Choose a later time.',409,'time_passed')
    if strict and capacity.target and day>capacity.target:raise Problem('That day is after your target date.',409,'outside_plan')
    if day>=capacity.today and any(begin<high and low<end for low,high in capacity.blackout_windows(day)):
        raise Problem('That time is blocked out in your plan settings. Choose another time.',409,'blackout')
    clash=next((title for low,high,title in busy_on(plan,day,(task['id'],index)) if begin<high and low<end),None)
    if clash and (strict or not allow_overlap):
        raise Problem(f'That time overlaps “{clash}”. Choose another time.' if strict else f'That time overlaps “{clash}”.',409,'slot_taken' if strict else 'overlap')

def place(task,index,day,start,minutes):
    slot={'date':day.isoformat(),'start_time':start,'duration_minutes':minutes}
    if index is None or not task.get('schedule'):task['schedule']=[slot]
    else:task['schedule'][index]=slot
    task['anytime_date']=None
    if len(task['schedule'])==1:task['estimated_minutes']=minutes

def study_spans(capacity,day):
    blocks=[b for b in capacity.config.blocks if b.day==day.weekday() and (b.kind=='preferred' or capacity.config.use_backup)]
    return merge([(to_minute(b.start_time),to_minute(b.start_time)+b.duration_minutes) for b in blocks])

def free_starts(spans,holes,minutes):
    starts=[]
    for low,high in subtract(spans,holes):
        minute=-(-low//STEP)*STEP
        while minute+minutes<=high:
            starts.append(minute);minute+=STEP
    return starts

def day_options(plan,capacity,day,minutes,skip=None,extra=()):
    """Free start times on one day: inside study blocks, after them only when they are full, never in a blackout."""
    holes=[(low,high) for low,high,_ in busy_on(plan,day,skip)]+list(capacity.blackout_windows(day))+list(extra)
    if day==capacity.today:holes.append((0,capacity.now_minute))
    study=study_spans(capacity,day)
    if not study:
        config=capacity.config
        starts=free_starts([(to_minute(config.overflow_start),to_minute(config.overflow_end))],holes,minutes)
        return {'rest_day':True,'kind':'rest_day' if starts else 'none','starts':starts}
    starts=free_starts(study,holes,minutes)
    if starts:return {'rest_day':False,'kind':'study','starts':starts}
    late=free_starts([(study[-1][1],1440)],holes,minutes)
    return {'rest_day':False,'kind':'after_block' if late else 'none','starts':late}

def horizon(capacity):
    """Today to the Sunday of next week, stopping at the target date."""
    last=week_of(capacity.today)+timedelta(days=13)
    if capacity.target:last=min(last,capacity.target)
    day=capacity.today
    while day<=last:
        yield day
        day+=timedelta(days=1)

def free_times(plan,now,minutes,session_id=None):
    capacity=calendar(plan,now);skip=None
    if session_id:
        task,index=locate(plan,session_id);skip=(task['id'],index)
    days=[]
    for day in horizon(capacity):
        options=day_options(plan,capacity,day,minutes,skip)
        days.append({'date':day.isoformat(),'rest_day':options['rest_day'],'kind':options['kind'],'starts':[to_clock(m) for m in options['starts']]})
    return {'today':capacity.today.isoformat(),'days':days}

def backlog_plan(plan,now,session_ids=None):
    """Earliest free study time for each backlog item, with at most one moved task a day while there is room."""
    capacity=calendar(plan,now)
    wanted=None if session_ids is None else set(session_ids)
    items=[row for row in session_views(plan,now) if row['missed'] and (wanted is None or row['id'] in wanted)]
    days=list(horizon(capacity));taken={};used=set();moves=[]
    for row in items:
        task,index=locate(plan,row['id']);choice=None
        for spread in (True,False):
            for day in days:
                if spread and day in used:continue
                options=day_options(plan,capacity,day,row['duration_minutes'],(task['id'],index),taken.get(day,()))
                if options['kind']=='study':
                    choice=(day,options['starts'][0]);break
            if choice:break
        if choice:
            day,start=choice;used.add(day);taken.setdefault(day,[]).append((start,start+row['duration_minutes']))
        moves.append({'session_id':row['id'],'title':row['title'],'duration_minutes':row['duration_minutes'],
            'date':choice[0].isoformat() if choice else None,'start_time':to_clock(choice[1]) if choice else None})
    return moves

# Writes

def move_session(plan,capacity,session_id,day,start):
    task,index=locate(plan,session_id)
    if task['status']=='completed':raise Problem('A finished task cannot be moved. Untick it first.',409,'session_completed')
    old_day=task_day(task,index)
    minutes=task['estimated_minutes'] if index is None else task['schedule'][index]['duration_minutes']
    check_time(plan,capacity,task,index,day,start,minutes,strict=True)
    previous={'schedule':[dict(slot) for slot in task.get('schedule') or []]}
    if index is None:previous['anytime_date']=old_day
    place(task,index,day,start,minutes)
    if old_day<capacity.today.isoformat():task['backlog_moved_at']=stamp()
    record_edit(task,previous)

def skip_session(plan,capacity,session_id):
    task,index=locate(plan,session_id)
    if task['status']=='completed' or task_day(task,index)>=capacity.today.isoformat():
        raise Problem('Only a missed session can be skipped.',409,'not_missed')
    now=stamp()
    if index is not None and len(task['schedule'])>1:
        previous={'schedule':[dict(slot) for slot in task['schedule']]}
        task['schedule'].pop(index);record_edit(task,previous)
        return
    task['removed']=True;task['removal']={'at':now,'reason':SKIP_REASON}
    task.setdefault('history',[]).append({'at':now,'event':'removed','reason':SKIP_REASON})
    mark_membership_review(plan,[task.get('milestone_key')])

def save_session(plan,capacity,source,session_id,changes,allow_overlap=False):
    """Apply one saved draft of a task's details: wording, skills, time, notes and self-ratings."""
    task,index=locate(plan,session_id)
    if any(changes.get(name,'') is None for name in ('title','completion_criterion','skills','date','duration_minutes')):
        raise Problem('Task fields cannot be empty.',422,'validation')
    previous={};had_original=bool(task.get('original'))
    wording={'title':changes.get('title',task['title']),'completion_outcome':changes.get('completion_criterion',task['completion_outcome'])}
    if changes.get('restore_original') and task.get('original'):wording=dict(task['original'])
    for name,value in wording.items():
        if value==task[name]:continue
        if task.get('origin')!='user' and not task.get('original'):
            task['original']={'title':task['title'],'completion_outcome':task['completion_outcome']}
        previous[name]=task[name];task[name]=value
        if name=='completion_outcome' and task['status']=='completed':task['definition_review_required']=True
    if task.get('original') and all(task['original'][name]==task[name] for name in ('title','completion_outcome')):
        task['original']=None
    if 'skills' in changes:
        shown=effective_skills(plan,task,next((item for item in plan.get('assignments',[]) if item['id']==session_id),None))
        chosen=choose_skills(plan,source,changes['skills'],shown)
        if chosen!=shown:
            previous['skills']=task.get('skills');task['skills']=chosen
            if task.get('origin')=='user':link_own_task(plan,task)
    day_text=task_day(task,index)
    start=None if index is None else task['schedule'][index]['start_time']
    minutes=task['estimated_minutes'] if index is None else task['schedule'][index]['duration_minutes']
    new_day=changes.get('date',day_text);new_start=changes['start_time'] if 'start_time' in changes else start
    new_minutes=changes.get('duration_minutes',minutes)
    if (str(new_day),new_start,new_minutes)!=(day_text,start,minutes):
        day=date.fromisoformat(str(new_day))
        previous['schedule']=[dict(slot) for slot in task.get('schedule') or []]
        if index is None:previous['anytime_date']=day_text
        if new_start is None:
            if len(task.get('schedule') or [])>1:raise Problem('This task has several sessions, so each one needs a time.',409,'task_status_required')
            if index is not None:previous['anytime_date']=None
            task['schedule']=[];task['anytime_date']=day.isoformat();task['estimated_minutes']=new_minutes
        else:
            check_time(plan,capacity,task,index,day,new_start,new_minutes,strict=False,allow_overlap=allow_overlap)
            place(task,index,day,new_start,new_minutes)
    record_edit(task,previous)
    if had_original and not task.get('original'):
        # Back to the generated wording, so a later revision may rewrite it again.
        task['overrides']=[name for name in task.get('overrides',[]) if name not in ('title','completion_outcome')]
    if 'notes' in changes and changes['notes'] is not None and task.get('notes')!=changes['notes']:
        task['notes']=changes['notes'];task['notes_updated_at']=stamp()
    if 'confidence' in changes or 'difficulty' in changes:
        old=task.get('self_rating') or {}
        rating={name:changes.get(name,old.get(name)) for name in ('confidence','difficulty')}
        if rating!={name:old.get(name) for name in rating}:
            task['self_rating']={**rating,'recorded_at':stamp()} if any(rating.values()) else None

def new_task(plan,capacity,source,identifier,session,allow_overlap=False):
    """A task of the user's own, on one day, timed or anytime."""
    day=date.fromisoformat(str(session['date']))
    if day<capacity.today:raise Problem('Add tasks to today or a later day.',422,'validation')
    title=session['title'];minutes=session['duration_minutes']
    task={'id':identifier,'title':title,'instructions':title,'completion_outcome':session['completion_criterion'].strip() or f'You finished “{title}”.',
        'estimated_minutes':minutes,'requirement_refs':[],'requirement_source_hash':plan.get('assessment_hash'),'requirement_source_id':plan.get('assessment_id'),
        'prerequisites':[],'milestone_key':None,'schedule':[],'anytime_date':None,'skills':choose_skills(plan,source,session['skills']),
        'status':'not_started','completed_at':None,'evidence_note':None,'history':[],'removed':False,'removal':None,'definition_review_required':False,
        'origin':'user','generated_key':None,'overrides':[],'source_assignment':None}
    if session.get('notes'):task['notes']=session['notes'];task['notes_updated_at']=stamp()
    if session['start_time'] is None:task['anytime_date']=day.isoformat()
    else:
        check_time(plan,capacity,task,None,day,session['start_time'],minutes,strict=False,allow_overlap=allow_overlap)
        place(task,None,day,session['start_time'],minutes)
    ensure_tasks(plan).append(task)
    link_own_task(plan,task)
    return task

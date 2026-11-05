"""Schedule diagnostics stay bounded and retain affected task identities."""
from datetime import date
import random

from app.planning.tasks import schedule_warnings
from planner_fixtures import NOW, settings


def task(ident, slots, prerequisites=(), status='not_started'):
    return {'id':ident, 'schedule':slots, 'estimated_minutes':60000, 'status':status,
            'prerequisites':list(prerequisites), 'removed':False}


def slot(day, start, minutes):
    return {'date':day, 'start_time':start, 'duration_minutes':minutes}


def plan(tasks):
    return {'editable_tasks':tasks, 'config':settings(), 'milestones':[]}


def test_overlap_sweep_matches_pairwise_ground_truth():
    randomizer=random.Random(42)
    tasks=[]
    intervals=[]
    for index in range(150):
        minute=randomizer.randrange(0, 1400)
        duration=randomizer.randrange(1, 41)
        day=f'2030-01-{9 + randomizer.randrange(3):02d}'
        ident=str(index)
        tasks.append(task(ident,[slot(day, f'{minute//60:02d}:{minute%60:02d}', duration)]))
        intervals.append((date.fromisoformat(day),minute,minute+duration,ident))
    expected=set()
    for index,(day,start,end,ident) in enumerate(intervals):
        for day2,start2,end2,ident2 in intervals[index+1:]:
            if day==day2 and start<end2 and start2<end:expected.update((ident,ident2))
    warnings=schedule_warnings(plan(tasks),NOW)
    overlap=next(w for w in warnings if w['code']=='overlap')
    assert set(overlap['task_ids'])==expected


def test_many_coincident_segments_have_bounded_warnings_with_every_task_identified():
    tasks=[task(str(index),[slot('2030-01-09','19:00',30)]*100) for index in range(1000)]
    warnings=schedule_warnings(plan(tasks),NOW)
    assert len(warnings)<=9
    overlap=next(w for w in warnings if w['code']=='overlap')
    assert set(overlap['task_ids'])=={t['id'] for t in tasks}
    assert all(len(w['task_ids'])<=len(tasks) for w in warnings)


def test_prerequisite_order_warns_without_treating_dates_as_completion():
    prerequisite=task('first',[slot('2030-01-10','10:00',60)])
    dependent=task('second',[slot('2030-01-10','10:30',30)],['first'])
    warnings=schedule_warnings(plan([prerequisite,dependent]),NOW)
    assert set(next(w for w in warnings if w['code']=='prerequisite_order')['task_ids'])=={'first','second'}
    prerequisite['schedule']=[]
    warnings=schedule_warnings(plan([prerequisite,dependent]),NOW)
    assert set(next(w for w in warnings if w['code']=='prerequisite_unscheduled')['task_ids'])=={'first','second'}
    prerequisite['status']='completed'
    assert not any(w['code'].startswith('prerequisite_') for w in schedule_warnings(plan([prerequisite,dependent]),NOW))


def test_milestone_prerequisite_order_is_warned_and_all_tasks_are_retained():
    first=task('first',[slot('2030-01-10','12:00',60)])
    first['milestone_key']='foundation'
    second=task('second',[slot('2030-01-10','10:00',30)])
    second['milestone_key']='advanced'
    roadmap=plan([first,second])
    roadmap['milestones']=[{'key':'foundation','prerequisite_keys':[]},
                           {'key':'advanced','prerequisite_keys':['foundation']}]
    warnings=schedule_warnings(roadmap,NOW)
    assert set(next(w for w in warnings if w['code']=='prerequisite_order')['task_ids'])=={'first','second'}
    first['schedule']=[]
    warnings=schedule_warnings(roadmap,NOW)
    assert set(next(w for w in warnings if w['code']=='prerequisite_unscheduled')['task_ids'])=={'first','second'}

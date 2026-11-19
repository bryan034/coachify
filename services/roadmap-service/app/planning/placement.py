"""Saved-time reservations and weekly targets for session placement (see `capacity.Placer`)."""
import copy
from datetime import timedelta
from app.planning.capacity import Placer
from app.planning.tasks import ensure_tasks

def reservations(plan):
    """Saved time that new sessions must not overlap. Removed tasks hold no time."""
    if not plan:return []
    return [dict(slot) for task in ensure_tasks(copy.deepcopy(plan)) if not task.get('removed') for slot in (task.get('schedule') or ([{'date':task['anytime_date'],'start_time':None,'duration_minutes':task['estimated_minutes']}] if task.get('anytime_date') else []))]

def week_target(config,now,reserved,start,end):
    """How much study this week should hold, with the reasons it differs from the weekly hours.

    The target is the agreed weekly hours unless less can be placed: a partial week, a
    reduced-availability period, saved work already using the time, or too few free windows.
    """
    placer=Placer(config,now,reserved,start,end)
    capacity=placer.capacity;week=capacity.week(start)
    agreed=config.weekly_minutes or 0;cap=capacity.cap_for(week);left=capacity.week_left(week)
    room=placer.room();reasons=[]
    add=lambda code,message:reasons.append({'code':code,'message':message})
    hours=lambda minutes:f'{minutes//60}h {minutes%60:02d}m' if minutes%60 else f'{minutes//60}h'
    if cap<agreed:add('reduced_availability',f'A reduced-availability period lowers this week to {hours(cap)}.')
    if left<cap:add('saved_work',f'{hours(cap-left)} of this week is already scheduled.')
    if room<left:
        partial=start>week or end<week+timedelta(days=7)
        if partial:add('partial_week',f'Part of this week has passed or falls outside your roadmap, so {hours(room)} fits.')
        else:add('limited_time',f'Your study times, session length, breaks and blocked-out times leave room for {hours(room)}. Add study time or allow extra time to reach {hours(left)}.')
    return {'weekly_minutes':agreed,'target_minutes':room,'shortfall_minutes':max(0,left-room),'reasons':reasons}

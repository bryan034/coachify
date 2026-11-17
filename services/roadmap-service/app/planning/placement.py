"""Deterministic session placement for a planned week.

The model decides what to study and for how long. This module alone decides when: it
splits work into sessions no longer than the configured session length, leaves the
configured break after each one, and keeps every session inside a free window from
`Capacity`. Study blocks are filled first, in date order; extra time is used only when
they are full, and is spread across the least busy days.
"""
from datetime import date, timedelta
from app.planning.capacity import Capacity, session_break, shortest_session, to_clock, to_minute

STEP=5

def reservations(plan,skip=()):
    """Saved time that new sessions must not overlap. Removed tasks hold no time."""
    if not plan:return []
    from app.planning.tasks import ensure_tasks
    import copy
    return [dict(slot) for task in ensure_tasks(copy.deepcopy(plan)) if not task.get('removed') and task['id'] not in skip for slot in (task.get('schedule') or ([{'date':task['anytime_date'],'start_time':None,'duration_minutes':task['estimated_minutes']}] if task.get('anytime_date') else []))]

def session_lengths(minutes,config):
    """Split an estimate into sessions of roughly equal length, none above the session limit."""
    longest=config.preferred_session_minutes
    if minutes<=longest:return [minutes]
    count=-(-minutes//longest)
    size=-(-minutes//count//STEP)*STEP
    lengths=[]
    while minutes>0:
        part=min(size,longest,minutes);lengths.append(part);minutes-=part
    return lengths

class Placer:
    """Places sessions one at a time between start (inclusive) and end (exclusive)."""
    def __init__(self,config,now,reserved,start,end):
        self.config=config;self.start=start;self.end=end
        self.capacity=Capacity(config,now,reserved)
        self.busy={};self.day_used={};self.week_used={}
        for slot in reserved:
            day=date.fromisoformat(str(slot['date']))
            if slot.get('start_time') is not None:
                begin=to_minute(slot['start_time'])
                self.busy.setdefault(day,[]).append((begin,begin+slot['duration_minutes']))
            self.day_used[day]=self.day_used.get(day,0)+slot['duration_minutes']
        earliest=self.capacity.now_minute+config.lead_minutes
        self.earliest=(self.capacity.today+timedelta(days=earliest//1440),earliest%1440)
    def days(self):
        day=max(self.start,self.earliest[0],self.capacity.start)
        while day<self.end:
            if day in self.capacity.days:yield day
            day+=timedelta(days=1)
    def clear(self,day,begin,minutes):
        """No overlap, and a break on both sides of any neighbouring session."""
        end=begin+minutes+session_break(minutes,self.config)
        return all(begin>=high+session_break(high-low,self.config) or end<=low for low,high in self.busy.get(day,[]))
    def allowed(self,day,minutes):
        week=self.capacity.week(day)
        if self.week_used.get(week,0)+minutes>self.capacity.week_left(week):return False
        limit=self.config.max_daily_minutes
        if limit is not None and self.day_used.get(day,0)+minutes>limit:return False
        if self.config.rest_days_per_week and not self.day_used.get(day):
            used=sum(1 for offset in range(7) if self.day_used.get(week+timedelta(days=offset)))
            if used>=7-self.config.rest_days_per_week:return False
        return True
    def slot(self,day,minutes,kind):
        if not self.start<=day<self.end or day not in self.capacity.days or day<self.earliest[0]:return None
        if not self.allowed(day,minutes):return None
        for low,high,found in self.capacity.eligible(day) or []:
            if found!=kind:continue
            begin=-(-max(low,self.earliest[1] if day==self.earliest[0] else 0)//STEP)*STEP
            while begin+minutes<=high:
                if self.clear(day,begin,minutes):return begin
                # Jump directly beyond conflicting sessions instead of scanning every five minutes.
                conflicts=[high+session_break(high-low,self.config) for low,high in self.busy.get(day,[])
                    if begin<high+session_break(high-low,self.config) and begin+minutes+session_break(minutes,self.config)>low]
                begin=-(-max([begin+STEP,*conflicts])//STEP)*STEP
        return None
    def find(self,minutes,only=None,kind=None):
        """The next session time: the earliest study block, otherwise extra time on the least busy day."""
        days=[only] if only else list(self.days())
        for day in days if kind!='overflow' else []:
            begin=self.slot(day,minutes,'preferred')
            if begin is not None:return day,begin
        for day in sorted(days,key=lambda item:(self.day_used.get(item,0),item)) if kind!='preferred' else []:
            begin=self.slot(day,minutes,'overflow')
            if begin is not None:return day,begin
        return None
    def take(self,day,begin,minutes):
        self.busy.setdefault(day,[]).append((begin,begin+minutes))
        self.day_used[day]=self.day_used.get(day,0)+minutes
        week=self.capacity.week(day);self.week_used[week]=self.week_used.get(week,0)+minutes
    def release(self,day,begin,minutes):
        self.busy[day].remove((begin,begin+minutes))
        self.day_used[day]-=minutes
        week=self.capacity.week(day);self.week_used[week]-=minutes
    def accepts(self,day,begin,minutes):
        """Validate a fixed proposed slot using the same rules as generation."""
        return (self.start<=day<self.end and day in self.capacity.days and day>=self.earliest[0]
            and (day!=self.earliest[0] or begin>=self.earliest[1])
            and shortest_session(self.config)<=minutes<=self.config.preferred_session_minutes
            and self.allowed(day,minutes) and self.capacity.fits(day,begin,begin+minutes)
            and self.clear(day,begin,minutes))
    def place(self,minutes,only=None):
        """Place all of a task, splitting further when shorter windows require it."""
        minimum=shortest_session(self.config)
        if minutes<minimum:return None
        taken=[]
        def rollback():
            for day,begin,size in taken:self.release(day,begin,size)
            taken.clear()
        for length in session_lengths(minutes,self.config):
            if length<minimum:break
            found=self.find(length,only)
            if not found:break
            self.take(*found,length);taken.append((*found,length))
        else:
            return [{'date':day.isoformat(),'start_time':to_clock(begin),'duration_minutes':size} for day,begin,size in sorted(taken)]
        rollback()
        remaining=minutes;minimum=shortest_session(self.config)
        while remaining:
            found=None
            for length in range(min(self.config.preferred_session_minutes,remaining),minimum-1,-1):
                if 0<remaining-length<minimum:continue
                found=self.find(length,only)
                if found:break
            if not found:
                rollback();return None
            self.take(*found,length);taken.append((*found,length));remaining-=length
        return [{'date':day.isoformat(),'start_time':to_clock(begin),'duration_minutes':size} for day,begin,size in sorted(taken)]
    def room_details(self):
        """Measure placeable study time, restoring all reservations afterwards."""
        best=(0,0);minimum=shortest_session(self.config)
        days=list(self.days());by_week={};longest=0
        for day in days:
            spans=self.capacity.eligible(day) or []
            available=sum(high-low for low,high,_ in spans)
            if self.config.max_daily_minutes is not None:
                available=min(available,max(0,self.config.max_daily_minutes-self.day_used.get(day,0)))
            longest=max(longest,min(available,max((high-low for low,high,_ in spans),default=0)))
            by_week.setdefault(self.capacity.week(day),[]).append((day,available))
        ceiling=0
        for week,rows in by_week.items():
            occupied={day for day,minutes in self.day_used.items() if minutes and self.capacity.week(day)==week}
            new_days=max(0,7-self.config.rest_days_per_week-len(occupied))
            available=sum(minutes for day,minutes in rows if day in occupied)
            available+=sum(sorted((minutes for day,minutes in rows if day not in occupied),reverse=True)[:new_days])
            ceiling+=min(self.capacity.week_left(week),available)
        if ceiling<minimum:return best
        limit=min(self.config.preferred_session_minutes,longest,max(self.capacity.week_left(week) for week in by_week))
        seeds=[limit,*range(self.config.preferred_session_minutes,minimum-1,-STEP),minimum]
        for maximum in dict.fromkeys(seed for seed in seeds if minimum<=seed<=limit):
            taken=[];preferred=0;overflow=0
            for kind in ('preferred','overflow'):
                length=maximum
                while length>=minimum:
                    found=self.find(length,kind=kind)
                    if found:
                        self.take(*found,length);taken.append((*found,length))
                        if kind=='preferred':preferred+=length
                        else:overflow+=length
                    else:length-=1
            for day,begin,size in taken:self.release(day,begin,size)
            if (preferred+overflow,preferred)>(sum(best),best[0]):best=(preferred,overflow)
            if sum(best)>=ceiling:break
        return best
    def room(self):
        return sum(self.room_details())

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

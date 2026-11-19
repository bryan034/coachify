"""Runway, study-capacity arithmetic and deterministic session placement.

Times are wall-clock minutes on real local dates. A date is available only inside its
configured blocks, so overlapping blocks merge and repeated daylight-saving hours count once.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.schemas.roadmap import Duration

MAX_RUNWAY_DAYS=366
STEP=5

def to_minute(text):
    hours,minutes=text.split(':')
    return int(hours)*60+int(minutes)
def to_clock(minute):
    return f'{minute//60:02d}:{minute%60:02d}'
def week_of(day,first=0):
    """The first day of the week holding this date. Weeks start on Monday (0) unless the user chose another day."""
    return day-timedelta(days=(day.weekday()-first)%7)
def session_break(minutes,config):
    """Rest owed after a session: the configured minutes per hour studied, rounded up to five minutes."""
    return -(-minutes*config.break_minutes_per_hour//300)*5
def shortest_session(config):
    return min(config.min_session_minutes,config.preferred_session_minutes)
def add_duration(start,duration):
    if duration.unit=='weeks':return start+timedelta(weeks=duration.value)
    index=start.month-1+duration.value
    year,month=start.year+index//12,index%12+1
    return date(year,month,min(start.day,monthrange(year,month)[1]))
def matched_duration(start,target):
    days=(target-start).days
    if days>0 and days%7==0 and days//7<=52:return Duration(value=days//7,unit='weeks')
    for value in range(1,13):
        months=Duration(value=value,unit='months')
        if add_duration(start,months)==target:return months
    return None
def merge(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],end))
        else:merged.append((start,end))
    return merged
def subtract(intervals,holes):
    result=[]
    for start,end in merge(intervals):
        cursor=start
        for low,high in merge(holes):
            if high<=cursor or low>=end:continue
            if low>cursor:result.append((cursor,low))
            cursor=max(cursor,high)
        if cursor<end:result.append((cursor,end))
    return result
def missing_local_minutes(day,zone):
    """Local minutes a forward clock change skips on this date."""
    opening=datetime(day.year,day.month,day.day,tzinfo=zone)
    closing=opening+timedelta(days=1)
    if opening.utcoffset()==closing.utcoffset():return []
    missing=[]
    for minute in range(1440):
        local=datetime(day.year,day.month,day.day,minute//60,minute%60,tzinfo=zone)
        if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=local.replace(tzinfo=None):
            missing.append((minute,minute+1))
    return merge(missing)
def blackout_problem(rule):
    """Why a blackout rule cannot apply, phrased to follow its name, or None."""
    if rule.end_date and rule.end_date<rule.start_date:return 'ends before it starts'
    if (rule.start_time is None)!=(rule.end_time is None):return 'needs both a start and an end time'
    if rule.start_time and rule.end_time<=rule.start_time:return 'must end after it starts on the same day'
    if rule.frequency=='weekly' and not rule.weekdays:return 'needs at least one weekday'
    return None
def blackout_occurs(rule,day):
    first=rule.start_date
    if day<first or (rule.end_date and day>rule.end_date):return False
    if rule.frequency=='once':return day==first
    if rule.frequency=='daily':return (day-first).days%rule.interval==0
    if rule.frequency=='weekly':
        return day.weekday() in rule.weekdays and (week_of(day)-week_of(first)).days//7%rule.interval==0
    months=(day.year-first.year)*12+day.month-first.month
    return months%rule.interval==0 and day.day==min(first.day,monthrange(day.year,day.month)[1])
def blackout_span(rule):
    """Local minutes a rule removes on a day it occurs; 23:59 means midnight."""
    if rule.start_time is None:return (0,1440)
    return (to_minute(rule.start_time),1440 if rule.end_time=='23:59' else to_minute(rule.end_time))
def resolve_dates(config,today):
    start=config.start_date or today
    target=add_duration(start,config.duration) if config.duration else config.target_date
    return start,target
def normalized(config,today):
    start,target=resolve_dates(config,today)
    return config.model_copy(update={'start_date':start,'target_date':target})

class Capacity:
    """Eligible study time for one configuration, from now until the target date.

    Every path that places or checks a session reads its windows from here: study blocks
    first, then the extra-time window when it is enabled. Blackouts, elapsed time, saved
    work and zero-hour reduced periods are already removed.
    """
    def __init__(self,config,now,completed=()):
        self.config=config
        self.now=now
        self.zone=ZoneInfo(config.time_zone)
        local=now.astimezone(self.zone)
        self.today=local.date()
        self.now_minute=local.hour*60+local.minute+(1 if local.second or local.microsecond else 0)
        self.start_date,self.target=resolve_dates(config,self.today)
        self.start=max(self.start_date,self.today)
        self.cap=config.weekly_minutes or 0
        self.first=config.week_start_day
        self.reduced=list(config.reduced_periods) if config.apply_reduced_periods else []
        self.completed_by_date={}
        self.completed_by_week={}
        self.busy_minutes={}
        self.reserved=list(completed)
        self._capacity_cache={}
        for session in self.reserved:
            day=date.fromisoformat(str(session['date']))
            if session.get('start_time') is not None:
                begin=to_minute(session['start_time'])
                self.completed_by_date.setdefault(day,[]).append((begin,begin+session['duration_minutes']))
            self.busy_minutes[day]=self.busy_minutes.get(day,0)+session['duration_minutes']
            week=self.week(day)
            self.completed_by_week[week]=self.completed_by_week.get(week,0)+session['duration_minutes']
        self.blackouts=[rule for rule in config.blackouts if not blackout_problem(rule)]
        self.days={}
        if self.target and self.target>=self.start and (self.target-self.start).days<=MAX_RUNWAY_DAYS:
            day=self.start
            while day<=self.target:
                self.days[day]=self._windows(day)
                day+=timedelta(days=1)
    def week(self,day):
        return week_of(day,self.first)
    def reduced_for(self,week):
        """Non-zero reduced periods that touch this week."""
        return [p for p in self.reduced if p.weekly_minutes and p.start_date<=week+timedelta(days=6) and p.end_date>=week]
    def cap_for(self,week):
        """The weekly target, lowered by any reduced-availability period that touches the week."""
        return min([self.cap,*[p.weekly_minutes for p in self.reduced_for(week)]])
    def closed(self,day):
        """A zero-hour reduced period removes the whole day."""
        return any(not p.weekly_minutes and p.start_date<=day<=p.end_date for p in self.reduced)
    def blackout_windows(self,day):
        return merge([blackout_span(rule) for rule in self.blackouts if blackout_occurs(rule,day)])
    def _windows(self,day):
        blocks=[b for b in self.config.blocks if b.day==day.weekday()]
        span=lambda b:(to_minute(b.start_time),to_minute(b.start_time)+b.duration_minutes)
        holes=[*missing_local_minutes(day,self.zone),*self.completed_by_date.get(day,[]),*self.blackout_windows(day)]
        if day==self.today:holes.append((0,self.now_minute))
        if self.closed(day):holes.append((0,1440))
        preferred=merge([span(b) for b in blocks])
        overflow=subtract([(to_minute(self.config.overflow_start),to_minute(self.config.overflow_end))],preferred) if self.config.allow_overflow else []
        return {'preferred':subtract(preferred,holes),'overflow':subtract(overflow,holes)}
    def eligible(self,day,overflow=True):
        """Free windows on one day as (start, end, kind), study blocks before extra time."""
        try:windows=self.days[day] if day in self.days else self._windows(day)
        except OverflowError:return None
        return [(low,high,kind) for kind in (('preferred','overflow') if overflow else ('preferred',)) for low,high in windows[kind]]
    def fits(self,day,begin,end):
        windows=self.eligible(day)
        return windows is not None and any(low<=begin and end<=high for low,high,_ in windows)
    def week_left(self,week):
        return max(0,self.cap_for(week)-self.completed_by_week.get(week,0))
    def _week_minutes(self,first,last):
        """Use the session placer for breaks, saved commitments, rest days and limits."""
        key=(first,last)
        if key in self._capacity_cache:return self._capacity_cache[key]
        weeks={}
        for day in self.days:
            if first<=day<=last:weeks.setdefault(self.week(day),[]).append(day)
        result={}
        for week,days in weeks.items():
            start=max(first,min(days));end=min(last,max(days))+timedelta(days=1)
            result[week]=Placer(self.config,self.now,self.reserved,start,end).room_details()
        self._capacity_cache[key]=result
        return result
    def between(self,first,last):
        """Usable minutes from first to last, inclusive, honouring each week's remaining target."""
        return sum(min(self.week_left(week),preferred+overflow) for week,(preferred,overflow) in self._week_minutes(first,last).items())
    def weeks(self):
        result=[]
        if not self.target or self.target<self.start or not self.days and (self.target-self.start).days>MAX_RUNWAY_DAYS:return result
        rows=self._week_minutes(self.start,self.target)
        week=self.week(self.start)
        while week<=self.target:
            preferred,overflow=rows.get(week,(0,0))
            left=self.week_left(week);usable=min(left,preferred+overflow)
            result.append({'week_start':week.isoformat(),'weekly_cap':self.cap_for(week),'completed_minutes':self.completed_by_week.get(week,0),
                'preferred_minutes':min(left,preferred),'overflow_minutes':usable-min(left,preferred),'usable_minutes':usable,
                'partial':week<self.start or week+timedelta(days=6)>self.target,'reduced':bool(self.reduced_for(week))})
            week+=timedelta(days=7)
        return result
    def windows_for_week(self,week):
        """Exact eligible windows for one week, study blocks before extra time."""
        result=[]
        for offset in range(7):
            day=week+timedelta(days=offset)
            if day not in self.days:continue
            for start,end,kind in self.eligible(day):
                result.append({'date':day.isoformat(),'start_time':to_clock(start),'end_time':to_clock(end),'kind':kind,'minutes':end-start})
        return sorted(result,key=lambda w:({'preferred':0,'overflow':1}[w['kind']],w['date'],w['start_time']))
    def report(self,allow_past_start=False):
        config=self.config;issues=[];notices=[]
        add=lambda code,message:issues.append({'code':code,'message':message})
        dates_valid=False
        if not self.target:add('missing_target','Choose a target date or a duration.')
        elif self.target<=self.start_date:add('target_before_start','Choose a target date after the start date.')
        elif self.target<self.today:add('target_elapsed','This target date has passed. Choose a new one.')
        elif (self.target-self.start_date).days>MAX_RUNWAY_DAYS:add('runway_too_long','Plan at most one year at a time.')
        elif self.start_date<self.today and not allow_past_start:add('start_in_past','Choose a start date of today or later.')
        else:dates_valid=True
        if not config.weekly_minutes:add('no_budget','Set a weekly study budget above zero.')
        if not config.blocks and not config.allow_overflow:add('no_blocks','Add at least one recurring study block.')
        for number,rule in enumerate(config.blackouts,1):
            problem=blackout_problem(rule)
            if problem:add('blackout_invalid',f'Blackout {number} {problem}.')
        weeks=self.weeks() if dates_valid else []
        study={'preferred_minutes':sum(w['preferred_minutes'] for w in weeks),
            'overflow_minutes':sum(w['overflow_minutes'] for w in weeks),
            'usable_minutes':sum(w['usable_minutes'] for w in weeks)}
        if dates_valid and config.weekly_minutes and (config.blocks or config.allow_overflow) and not study['usable_minutes']:
            add('no_usable_time','No usable study time remains between these dates.')
        short=[w for w in weeks if not w['partial'] and w['usable_minutes']<w['weekly_cap']-w['completed_minutes']]
        if short and study['usable_minutes']:
            least=min(w['usable_minutes'] for w in short)
            notices.append({'code':'windows_below_target','message':f"{len(short)} of your weeks can hold less than your weekly hours (as little as {least//60}h {least%60:02d}m) once session length, breaks and blocked-out times are counted. Add study time, allow extra time or lower your weekly hours."})
        if any(w['reduced'] for w in weeks):
            notices.append({'code':'reduced_periods','message':'Weeks that overlap a reduced-availability period in your Profile use its lower weekly hours.'})
        calendar=None
        if dates_valid:
            days=(self.target-self.start).days+1
            parts=[f'{days//7} week'+('s' if days//7!=1 else '')] if days>=7 else []
            if days%7 or not parts:parts.append(f'{days%7} day'+('s' if days%7!=1 else ''))
            calendar={'days':days,'weeks':days//7,'extra_days':days%7,'label':', '.join(parts),'partial_first_week':self.start.weekday()!=self.first}
        first=next((w['week_start'] for w in weeks if w['usable_minutes']),None)
        matched=matched_duration(self.start_date,self.target) if self.target and self.target>self.start_date else None
        return {'windows':[window for row in weeks for window in self.windows_for_week(date.fromisoformat(row['week_start']))],'can_generate':not issues,'issues':issues,'notices':notices,'calendar':calendar,'study':study,'weeks':weeks,'first_planning_week':first,
            'resolved':{'today':self.today.isoformat(),'start_date':self.start_date.isoformat(),
                'target_date':self.target.isoformat() if self.target else None,
                'matched_duration':matched.model_dump() if matched else None}}

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
    """Places sessions one at a time between start (inclusive) and end (exclusive).

    The model decides what to study and for how long; the placer alone decides when. It
    splits work into sessions no longer than the configured session length, leaves the
    configured break after each one, and keeps every session inside a free window from
    `Capacity`. Study blocks are filled first, in date order; extra time is used only when
    they are full, and is spread across the least busy days.
    """
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
                # Jump directly beyond conflicting sessions.
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
    def longest_fit(self,low,high,kind):
        """The longest session from low to high minutes that fits somewhere, or None. A shorter session fits wherever a longer one does."""
        if high<low or not self.find(low,kind=kind):return None
        while low<high:
            middle=(low+high+1)//2
            if self.find(middle,kind=kind):low=middle
            else:high=middle-1
        return low
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
                while length is not None:
                    found=self.find(length,kind=kind)
                    if not found:
                        length=self.longest_fit(minimum,length-1,kind)
                        continue
                    self.take(*found,length);taken.append((*found,length))
                    if kind=='preferred':preferred+=length
                    else:overflow+=length
            for day,begin,size in taken:self.release(day,begin,size)
            if (preferred+overflow,preferred)>(sum(best),best[0]):best=(preferred,overflow)
            if sum(best)>=ceiling:break
        return best
    def room(self):
        return sum(self.room_details())

"""Runway and study-capacity arithmetic. This is the only source of these numbers.

Times are wall-clock minutes on real local dates. A date is available only inside its
configured blocks, so overlapping blocks merge and repeated daylight-saving hours count once.
Local minutes a forward clock change skips are removed. A week runs Monday to Sunday in the
plan's time zone. Each week's eligible time is capped by the weekly maximum, then the buffer
share is reserved for catch-up, leaving the planned workload.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.schemas.roadmap import Duration

MAX_RUNWAY_DAYS=366

def to_minute(text):
    hours,minutes=text.split(':')
    return int(hours)*60+int(minutes)
def to_clock(minute):
    return f'{minute//60:02d}:{minute%60:02d}'
def week_of(day):
    return day-timedelta(days=day.weekday())
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
def total(intervals):
    return sum(end-start for start,end in intervals)
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
    """Local minutes a rule removes on a day it occurs. 23:59 is the latest a time field can say, so it means midnight."""
    if rule.start_time is None:return (0,1440)
    return (to_minute(rule.start_time),1440 if rule.end_time=='23:59' else to_minute(rule.end_time))
def split_buffer(eligible,percent):
    """Planned and reserved minutes for eligible time. The buffer rounds up, so the plan never eats into it."""
    buffer=-(-eligible*percent//100)
    return eligible-buffer,buffer
def resolve_dates(config,today):
    start=config.start_date or today
    target=add_duration(start,config.duration) if config.duration else config.target_date
    return start,target
def normalized(config,today):
    start,target=resolve_dates(config,today)
    return config.model_copy(update={'start_date':start,'target_date':target})

class Capacity:
    """Eligible study time for one configuration, from now until the target date."""
    def __init__(self,config,now,completed=(),paused=()):
        self.config=config
        self.paused={date.fromisoformat(str(week)) for week in paused}
        self.zone=ZoneInfo(config.time_zone)
        local=now.astimezone(self.zone)
        self.today=local.date()
        self.now_minute=local.hour*60+local.minute+(1 if local.second or local.microsecond else 0)
        self.start_date,self.target=resolve_dates(config,self.today)
        self.start=max(self.start_date,self.today)
        self.cap=config.weekly_minutes or 0
        self.completed_by_date={}
        self.completed_by_week={}
        for session in completed:
            if not session.get('date'):continue
            day=date.fromisoformat(str(session['date']))
            if session.get('start_time'):
                begin=to_minute(session['start_time'])
                self.completed_by_date.setdefault(day,[]).append((begin,begin+session['duration_minutes']))
            if session.get('count_hours',True):
                week=week_of(day)
                self.completed_by_week[week]=self.completed_by_week.get(week,0)+session['duration_minutes']
        self.blackouts=[rule for rule in config.blackouts if not blackout_problem(rule)]
        self.days={}
        if self.target and self.target>=self.start and (self.target-self.start).days<=MAX_RUNWAY_DAYS:
            day=self.start
            while day<=self.target:
                self.days[day]=self._windows(day)
                day+=timedelta(days=1)
    def blackout_windows(self,day):
        return merge([blackout_span(rule) for rule in self.blackouts if blackout_occurs(rule,day)])
    def _windows(self,day):
        if week_of(day) in self.paused:return {'preferred':[],'backup':[]}
        blocks=[b for b in self.config.blocks if b.day==day.weekday()]
        span=lambda b:(to_minute(b.start_time),to_minute(b.start_time)+b.duration_minutes)
        holes=[*missing_local_minutes(day,self.zone),*self.completed_by_date.get(day,[]),*self.blackout_windows(day)]
        if day==self.today:holes.append((0,self.now_minute))
        preferred=merge([span(b) for b in blocks if b.kind=='preferred'])
        backup=subtract([span(b) for b in blocks if b.kind=='backup'],preferred)
        return {'preferred':subtract(preferred,holes),'backup':subtract(backup,holes)}
    def week_left(self,week):
        return max(0,self.cap-self.completed_by_week.get(week,0))
    def between(self,first,last):
        """Usable minutes from first to last, inclusive, honouring each week's remaining cap."""
        weeks={}
        for day,windows in self.days.items():
            if first<=day<=last:
                minutes=total(windows['preferred'])+(total(windows['backup']) if self.config.use_backup else 0)
                weeks[week_of(day)]=weeks.get(week_of(day),0)+minutes
        return sum(min(self.week_left(week),minutes) for week,minutes in weeks.items())
    def planned_between(self,first,last):
        """Like between, after reserving each week's buffer: what generation may plan into."""
        weeks={}
        for day,windows in self.days.items():
            if first<=day<=last:
                minutes=total(windows['preferred'])+(total(windows['backup']) if self.config.use_backup else 0)
                weeks[week_of(day)]=weeks.get(week_of(day),0)+minutes
        return sum(split_buffer(min(self.week_left(week),minutes),self.config.buffer_percent)[0] for week,minutes in weeks.items())
    def week_minutes(self,week):
        """(eligible, planned, buffer) for one week, from the time still available in it."""
        eligible=self.between(week,week+timedelta(days=6))
        planned,buffer=split_buffer(eligible,self.config.buffer_percent)
        return eligible,planned,buffer
    def weeks(self):
        rows={}
        for day,windows in self.days.items():
            row=rows.setdefault(week_of(day),{'preferred':0,'backup':0})
            row['preferred']+=total(windows['preferred'])
            row['backup']+=total(windows['backup'])
        result=[]
        if not self.target or self.target<self.start or not self.days and (self.target-self.start).days>MAX_RUNWAY_DAYS:return result
        week=week_of(self.start)
        while week<=self.target:
            row=rows.get(week,{'preferred':0,'backup':0})
            left=self.week_left(week)
            preferred=min(left,row['preferred'])
            both=min(left,row['preferred']+row['backup'])
            usable=both if self.config.use_backup else preferred
            planned,buffer=split_buffer(usable,self.config.buffer_percent)
            result.append({'week_start':week.isoformat(),'weekly_cap':self.cap,'completed_minutes':self.completed_by_week.get(week,0),
                'preferred_minutes':preferred,'backup_extra_minutes':both-preferred,'usable_minutes':usable,
                'planned_minutes':planned,'buffer_minutes':buffer,'paused':week in self.paused,
                'partial':week<self.start or week+timedelta(days=6)>self.target})
            week+=timedelta(days=7)
        return result
    def windows_for_week(self,week):
        """Exact eligible windows for one Monday-to-Sunday week."""
        result=[]
        for offset in range(7):
            day=week+timedelta(days=offset)
            windows=self.days.get(day,{'preferred':[],'backup':[]})
            kinds=('preferred','backup') if self.config.use_backup else ('preferred',)
            for kind in kinds:
                for start,end in windows[kind]:
                    result.append({'date':day.isoformat(),'start_time':to_clock(start),'end_time':to_clock(end),'kind':kind,'minutes':end-start})
        return sorted(result,key=lambda w:(w['date'],w['start_time']))
    def report(self,allow_past_start=False):
        config=self.config;issues=[]
        add=lambda code,message:issues.append({'code':code,'message':message})
        dates_valid=False
        if not self.target:add('missing_target','Choose a target date or a duration.')
        elif self.target<=self.start_date:add('target_before_start','Choose a target date after the start date.')
        elif self.target<self.today:add('target_elapsed','This target date has passed. Choose a new one.')
        elif (self.target-self.start_date).days>MAX_RUNWAY_DAYS:add('runway_too_long','Plan at most one year at a time.')
        elif self.start_date<self.today and not allow_past_start:add('start_in_past','Choose a start date of today or later.')
        else:dates_valid=True
        if not config.weekly_minutes:add('no_budget','Set a weekly study budget above zero.')
        if not config.blocks:add('no_blocks','Add at least one recurring study block.')
        for number,rule in enumerate(config.blackouts,1):
            problem=blackout_problem(rule)
            if problem:add('blackout_invalid',f'Blackout {number} {problem}.')
        weeks=self.weeks() if dates_valid else []
        study={'preferred_minutes':sum(w['preferred_minutes'] for w in weeks),
            'backup_extra_minutes':sum(w['backup_extra_minutes'] for w in weeks),
            'usable_minutes':sum(w['usable_minutes'] for w in weeks)}
        if dates_valid and config.weekly_minutes and config.blocks and not study['usable_minutes']:
            add('no_usable_time','No usable study time remains between these dates.')
        calendar=None
        if dates_valid:
            days=(self.target-self.start).days+1
            parts=[f'{days//7} week'+('s' if days//7!=1 else '')] if days>=7 else []
            if days%7 or not parts:parts.append(f'{days%7} day'+('s' if days%7!=1 else ''))
            calendar={'days':days,'weeks':days//7,'extra_days':days%7,'label':', '.join(parts),'partial_first_week':self.start.weekday()!=0}
        first=next((w['week_start'] for w in weeks if w['usable_minutes']),None)
        matched=matched_duration(self.start_date,self.target) if self.target and self.target>self.start_date else None
        budget={'available_weeks':sum(1 for w in weeks if w['usable_minutes']),'eligible_minutes':study['usable_minutes'],
            'planned_minutes':sum(w['planned_minutes'] for w in weeks),'buffer_minutes':sum(w['buffer_minutes'] for w in weeks)}
        return {'can_generate':not issues,'issues':issues,'calendar':calendar,'study':study,'budget':budget,'weeks':weeks,'first_planning_week':first,
            'resolved':{'today':self.today.isoformat(),'start_date':self.start_date.isoformat(),
                'target_date':self.target.isoformat() if self.target else None,
                'matched_duration':matched.model_dump() if matched else None}}

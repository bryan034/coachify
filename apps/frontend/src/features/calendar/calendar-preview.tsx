"use client";
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { Icon } from '@/components/ui/icon';
import { useProfile } from '@/features/profile/profile-provider';
import { blockedOn } from '@/features/roadmap/blackout-rules';
import { addDays, addMonths, clockRange, fullDate, monthKey, monthTitle, monthWeeks, shortDate, weekDates } from '@/features/roadmap/roadmap-calendar';
import type { BlackoutRule, PlanAssignment } from '@/features/roadmap/types';
import { loadGoal, loadRoadmap, loadApplications, useSection } from '@/lib/api/workspace-summary';
import '@/styles/calendar.css';
import { PageSkeleton } from '@/components/ui/workspace-ui';

const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const views = ['Day', 'Week', 'Month'] as const;
type View = typeof views[number];
const dateKinds: Record<string, string> = { application_deadline: 'Application deadline', interview: 'Interview', job_start: 'Job starts' };
const DEADLINE_DAYS = 14;
const daysAway = (from: string, to: string) => { const days = Math.round((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86400000); return days > 0 ? `${days} ${days === 1 ? 'day' : 'days'} away` : days === 0 ? 'Today' : 'Passed'; };
const localToday = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const longDay = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-SG', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
const toMinutes = (clock: string) => { const [hour, minute] = clock.split(':').map(Number); return hour * 60 + minute; };
export type DatedMark = { date: string; label: string; kind: 'deadline' | 'milestone' | 'interview' };
const weekdayIndex = (value: string) => (new Date(`${value}T12:00:00Z`).getUTCDay() + 6) % 7;
/** Whole days the user blocked out (no start/end time), so the grid can hatch them. */
const blockedDay = (rules: BlackoutRule[], day: string) => rules.some(rule => !rule.start_time && !rule.end_time && day >= rule.start_date && (!rule.end_date || day <= rule.end_date) && (rule.frequency === 'once' ? day === rule.start_date : blockedOn(rule, weekdayIndex(day))));

function SessionBlock({ item, top, height }: { item: PlanAssignment; top: number; height: number }) {
 return <Link href="/roadmap" className={`cal-session${item.status === 'completed' ? ' is-done' : ''}${item.id.startsWith('block-') ? ' is-backup' : ''}`} style={{ top: `${top}%`, height: `${height}%` }} title={`${clockRange(item.start_time, item.duration_minutes)} ${item.task}`}>
  <small>{clockRange(item.start_time, item.duration_minutes)}</small><span>{item.task}</span>
 </Link>;
}

/** Hours widen beyond 08:00 to 21:00 only when a saved session falls outside them. */
function TimeGrid({ days, today, sessions, marks, blackouts }: { days: string[]; today: string; sessions: PlanAssignment[]; marks: DatedMark[]; blackouts: BlackoutRule[] }) {
 const visible = sessions.filter(item => days.includes(item.date));
 const start = Math.min(8 * 60, ...visible.map(item => Math.floor(toMinutes(item.start_time) / 60) * 60));
 const end = Math.max(24 * 60, ...visible.map(item => Math.ceil((toMinutes(item.start_time) + item.duration_minutes) / 60) * 60));
 const span = end - start;
 const hours = Array.from({ length: Math.floor(span / 120) + 1 }, (_, index) => start + index * 120).filter(value => value < end);
 const hasMarks = days.some(day => marks.some(mark => mark.date === day));
 return <div className={`cal-time${days.length === 1 ? ' is-day' : ''}`} style={{ gridTemplateColumns: `44px repeat(${days.length},minmax(84px,1fr))` }}>
  <span/>{days.map(day => <div key={day} className={`cal-head${day === today ? ' is-today' : ''}`} aria-current={day === today ? 'date' : undefined}><small>{dayNames[weekDates(day).indexOf(day)]}</small><b>{Number(day.slice(8))}</b></div>)}
  {hasMarks && <><span className="cal-hour-label">All day</span>{days.map(day => <div key={day} className="cal-allday">{marks.filter(mark => mark.date === day).map(mark => <span key={mark.label} className={`cal-mark is-${mark.kind}`}>{mark.label}</span>)}</div>)}</>}
  <div className="cal-hours">{hours.map(value => <span key={value} style={{ top: `${(value - start) / span * 100}%` }}>{String(Math.floor(value / 60)).padStart(2, '0')}:00</span>)}</div>
  {days.map(day => <div key={day} className={`cal-column${day === today ? ' is-today' : ''}${blockedDay(blackouts, day) ? ' is-blocked' : ''}`} style={{ backgroundSize: `100% ${120 / span * 100}%` }}>
   {visible.filter(item => item.date === day).map(item => <SessionBlock key={item.id} item={item} top={(toMinutes(item.start_time) - start) / span * 100} height={Math.max(item.duration_minutes / span * 100, 5)}/>)}
  </div>)}
 </div>;
}

function MonthGrid({ focus, today, sessions, marks }: { focus: string; today: string; sessions: PlanAssignment[]; marks: DatedMark[] }) {
 return <div className="month">{dayNames.map(day => <div className="dh" key={day}>{day}</div>)}
  {monthWeeks(focus).flatMap(weekDates).map(day => { const entries = [...marks.filter(mark => mark.date === day).map(mark => ({ key: mark.label, label: mark.label, kind: mark.kind as string })), ...sessions.filter(item => item.date === day).map(item => ({ key: item.id, label: item.task, kind: item.status === 'completed' ? 'done' : 'session' }))];
   return <div key={day} aria-current={day === today ? 'date' : undefined} className={`${day === today ? 'today ' : ''}${monthKey(day) !== monthKey(focus) ? 'out' : ''}`}><b>{Number(day.slice(8))}</b>
    {entries.slice(0, 2).map(entry => <span key={entry.key} className={`cal-mark is-${entry.kind}`}>{entry.label}</span>)}{entries.length > 2 && <small>+{entries.length - 2} more</small>}
   </div>; })}
 </div>;
}

function MiniMonth({ focus, today, onPick }: { focus: string; today: string; onPick: (date: string) => void }) {
 return <section className="cal-card cal-mini" aria-label={`${monthTitle(focus)} date picker`}><h2>{monthTitle(focus)}</h2><div className="cal-mini-grid">{dayNames.map(day => <span key={day} className="cal-mini-name">{day[0]}</span>)}
  {monthWeeks(focus).flatMap(weekDates).map(day => monthKey(day) === monthKey(focus) ? <button type="button" key={day} className={`${day === focus ? 'is-focus ' : ''}${day === today ? 'is-today' : ''}`} aria-label={longDay(day)} aria-pressed={day === focus} onClick={() => onPick(day)}>{Number(day.slice(8))}</button> : <span key={day}/>)}
 </div></section>;
}

export function CalendarPreview() {
 const { token } = useProfile();
 const applications=useSection(loadApplications,token);
 const [view, setView] = useState<View>('Week');
 const [today, setToday] = useState<string | null>(null);
 const [focus, setFocus] = useState<string | null>(null);
 useEffect(() => { const now = localToday(); setToday(now); setFocus(now); if (window.innerWidth < 640) setView('Day'); }, []);
 const roadmap = useSection(loadRoadmap, token), goal = useSection(loadGoal, token);
 const plan = roadmap.state.status === 'ready' ? roadmap.state.data.planner.active : null;
 const sessions = useMemo(() => [
  ...(plan?.assignments??[]),
  ...(roadmap.state.status==='ready'?(roadmap.state.data.planner.runway.windows??[]).filter(window=>window.kind!=='overflow'&&!(plan?.assignments??[]).some(item=>item.date===window.date&&item.start_time===window.start_time)).map((window,index)=>({id:`block-${index}`,key:`block-${index}`,milestone_key:'',gap_id:null,kind:'study' as const,date:window.date,start_time:window.start_time,duration_minutes:window.minutes,task:window.kind==='preferred'?'Preferred study time':'Backup study time',completion_criterion:'',status:'scheduled' as const,completed_at:null,evidence_note:null})):[])
 ], [plan,roadmap.state]);
 const jobDates = useMemo(() => goal.state.status === 'ready' ? (goal.state.data.goal?.job_dates ?? []).filter(item => item.date) : [], [goal.state]);
 const role = goal.state.status === 'ready' ? goal.state.data.goal?.role : undefined;
 const blackouts = roadmap.state.status === 'ready' ? roadmap.state.data.planner.config.blackouts ?? [] : [];
 const target = roadmap.state.status === 'ready' ? roadmap.state.data.planner.runway.resolved.target_date : null;
 const marks = useMemo<DatedMark[]>(() => [
  ...(applications.state.status==='ready'?applications.state.data.filter(item=>item.deadline).map(item=>({date:item.deadline!,label:`${item.snapshot.title} deadline`,kind:'deadline' as const})):[]),
  ...jobDates.map(item => ({ date: item.date!, label: dateKinds[item.kind] ?? item.kind, kind: item.kind === 'interview' ? 'interview' as const : 'deadline' as const })),
  ...(target ? [{ date: target, label: 'Roadmap target date', kind: 'deadline' as const }] : []),
  ...(plan?.milestones ?? []).map(item => ({ date: item.projected_end, label: item.title, kind: 'milestone' as const })),
 ], [jobDates, target, plan,applications.state]);
 if (!today || !focus) return <section className="page on calendar-page"><h1>Calendar</h1><PageSkeleton label="Loading calendar…"/></section>;
 const step = (direction: number) => setFocus(view === 'Day' ? addDays(focus, direction) : view === 'Week' ? addDays(focus, direction * 7) : addMonths(focus, direction));
 const horizon = addDays(today, DEADLINE_DAYS);
 const deadlines = marks.filter(mark => mark.kind !== 'milestone' && mark.date >= today && mark.date <= horizon).sort((a, b) => a.date.localeCompare(b.date));
 const remaining = sessions.filter(item => !item.id.startsWith('block-') && item.status === 'scheduled' && item.date >= today).sort((a, b) => a.date.localeCompare(b.date) || a.start_time.localeCompare(b.start_time));
 const dueToday = remaining.filter(item => item.date === today).length;
 const milestones = (plan?.milestones ?? []).filter(item => !item.outcome.demonstrated).sort((a, b) => a.projected_end.localeCompare(b.projected_end));
 const failure = [roadmap, goal].find(section => section.state.status === 'error');
 return <section className="page on calendar-page">
  <div className="cal-title">
   <div className="cal-title-name"><h1>Calendar</h1><p>Study sessions from your roadmap, saved-job deadlines and interviews.</p></div>
   <div className="cal-controls">
    <div className="cal-views" role="group" aria-label="Calendar view">{views.map(name => <button key={name} type="button" className={view === name ? 'on' : ''} aria-pressed={view === name} onClick={() => setView(name)}>{name}</button>)}</div>

   </div>
  </div>
  {failure && <div className="cal-failure" role="alert"><p>{failure === roadmap ? 'Your roadmap sessions could not be loaded, so some dates may be missing.' : 'Your job dates could not be loaded, so some dates may be missing.'}</p><button type="button" className="btn ghost sm" onClick={failure.retry}>Retry loading</button></div>}
  <div className="cal-layout">
   <div className="cal-main">
    <section className="cal-card cal-board">
     <header><div><h2>{view === 'Month' ? monthTitle(focus) : longDay(focus)}</h2>{view !== 'Month' && <small>{monthTitle(focus)}</small>}</div>
      <div className="cal-nav">{focus !== today && <button type="button" className="cal-today" onClick={() => setFocus(today)}>Today</button>}<button type="button" aria-label={`Previous ${view.toLowerCase()}`} onClick={() => step(-1)}>‹</button><button type="button" aria-label={`Next ${view.toLowerCase()}`} onClick={() => step(1)}>›</button></div>
     </header>
     <div className="calendar-grid-wrap" aria-label={`${view} calendar`}>
      {view === 'Month' ? <MonthGrid focus={focus} today={today} sessions={sessions} marks={marks}/> : <TimeGrid days={view === 'Day' ? [focus] : weekDates(focus)} today={today} sessions={sessions} marks={marks} blackouts={blackouts}/>}
     </div>
     {roadmap.state.status === 'ready' && !plan && <p className="cal-hint">Your study sessions appear here once you have a roadmap. <Link href="/roadmap">Plan your roadmap</Link></p>}
    </section>
    <section className="cal-events"><h2>Events</h2><p className="small">Event discovery is coming soon.</p></section>
   </div>
   <aside className="cal-rail">
    {target && <section className="cal-target" aria-labelledby="cal-target-title"><p id="cal-target-title">Target date</p><b>{fullDate(target)}</b><span>{daysAway(today, target)}</span></section>}
    <MiniMonth focus={focus} today={today} onPick={setFocus}/>
    <section className="cal-card cal-key" aria-labelledby="cal-key-title"><h2 id="cal-key-title">Key</h2>
     <ul>{[['study', 'Study session'], ['backup', 'Session in a backup block'], ['interview', 'Interview'], ['deadline', 'Application deadline'], ['blocked', 'Blocked out']].map(([kind, label]) => <li key={kind}><i className={`is-${kind}`} aria-hidden="true"/>{label}</li>)}</ul>
     <Link href="/roadmap">Change study times in Roadmap</Link>
    </section>
    <section className="cal-card cal-row" aria-labelledby="cal-deadlines-title">
     <span className="cal-row-icon"><Icon name="brief"/></span><div><h2 id="cal-deadlines-title">Deadlines</h2>{deadlines.length ? <ul>{deadlines.slice(0, 3).map(item => <li key={`${item.label}:${item.date}`}>{item.label}<b>{shortDate(item.date)}</b></li>)}</ul> : <small>{role ? `Nothing due for ${role} in ${DEADLINE_DAYS} days` : 'Nothing due'}</small>}</div><em>{DEADLINE_DAYS} days</em>
    </section>
    <section className="cal-card cal-row" aria-labelledby="cal-todo-title">
     <span className="cal-row-icon"><Icon name="book"/></span><div><h2 id="cal-todo-title">To-do</h2>{remaining[0] ? <small>{dueToday ? `${dueToday} ${dueToday === 1 ? 'session' : 'sessions'} today` : `Next on ${shortDate(remaining[0].date)}`}: {remaining[0].task}</small> : <small>{plan ? 'Every planned session is done.' : 'Roadmap tasks appear here.'}</small>}<Link href="/roadmap">Open your to-do list</Link></div>
    </section>
    <section className="cal-card cal-row" aria-labelledby="cal-milestones-title">
     <span className="cal-row-icon"><Icon name="road"/></span><div><h2 id="cal-milestones-title">Milestones</h2>{milestones.length ? <ul>{milestones.slice(0, 3).map(item => <li key={item.id}>{item.title}<b>{shortDate(item.projected_end)}</b></li>)}</ul> : <small>{plan ? 'All milestones reached.' : 'Your roadmap sets these.'}</small>}{target && <small>Target date {fullDate(target)}</small>}</div>
    </section>
    <section className="cal-card cal-row" aria-labelledby="cal-foryou-title">
     <span className="cal-row-icon"><Icon name="bolt"/></span><div><h2 id="cal-foryou-title">Events for you</h2><small>Your next opportunity</small></div><em>Soon</em>
    </section>
   </aside>
  </div>
 </section>;
}

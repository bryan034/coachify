"use client";
import { useState } from 'react';
import { addDays, addMonths, clockRange, dayOfMonth, fullDate, monthKey, monthTitle, monthWeeks, shortDate, weekColumns, weekDates, weekStart, weekdayName } from './roadmap-calendar';
import { hours, longDate } from './settings-panel';
import type { NotesDocument, PlanAssignment, PlanMilestone, PlanReview, PlannedRoadmap } from './types';
import { NotesEditor } from './notes-editor';

type View = 'day' | 'week' | 'month';
const views: [View, string][] = [['day', 'Daily'], ['week', 'Weekly'], ['month', 'Monthly']];
const MAX_BARS = 3;
const bySchedule = (a: PlanAssignment, b: PlanAssignment) => `${a.date}${a.start_time}`.localeCompare(`${b.date}${b.start_time}`);
const count = (value: number, noun: string) => `${value} ${noun}${value === 1 ? '' : 's'}`;

export function skillsFor(session: PlanAssignment, plan: PlannedRoadmap) {
 const milestone = plan.milestones.find(item => item.key === session.milestone_key);
 // Empty projected links explicitly suppress fallback. Older saved sessions
 // may lack the marker and can infer only a single unambiguous milestone gap.
 const fallback = session.gap_id ? [session.gap_id] : milestone?.gap_ids || [];
 const ids = session.skill_gap_ids ?? (fallback.length === 1 ? fallback : []);
 if (ids.length !== 1) return [];
 return plan.gaps.filter(gap => ids.includes(gap.id)).map(gap => gap.name);
}

type SaveNotes = ((taskId: string, notes: NotesDocument) => Promise<unknown>) | null;
function TaskItem({ session, plan, review, frozen, complete, reopen, saveNotes }: { session: PlanAssignment; plan: PlannedRoadmap; review: PlanReview; frozen: boolean; complete: ((session: PlanAssignment, note: string) => Promise<unknown>) | null; reopen: ((session: PlanAssignment) => Promise<unknown>) | null; saveNotes?: SaveNotes }) {
 const [note, setNote] = useState(''); const [ticking, setTicking] = useState<boolean | null>(null);
 // The tick shows at once. The saved status takes over when the request ends, so a failure undoes it.
 const tick = (checked: boolean) => { setTicking(checked); void (checked ? complete!(session, '') : reopen!(session)).finally(() => setTicking(null)); };
 const done = ticking ?? session.status === 'completed';
 const milestone = plan.milestones.find(item => item.key === session.milestone_key);
 const skills = skillsFor(session, plan);
 return <li className={`todo${done ? ' done' : ''}`}>
  {complete && reopen
   ? <input className="todo-check" type="checkbox" aria-label={`Mark complete: ${session.task}`} checked={done} disabled={frozen} onChange={event => tick(event.target.checked)} />
   : <span className={`todo-check-static${done ? ' done' : ''}`} aria-hidden="true" />}
  <div className="todo-body">
   <p className="todo-when"><span>{clockRange(session.start_time, session.duration_minutes)}</span><span>{hours(session.duration_minutes)}</span>
    {session.id === review.next_assignment_id && <span className="todo-flag next">Next</span>}
    {review.missed_assignment_ids.includes(session.id) && <span className="todo-flag">Passed</span>}
    {session.kind === 'diagnostic' && <span className="todo-flag">Diagnostic</span>}
   </p>
   <p className="todo-task">{session.task}</p>
   <p className="small">Done when: {session.completion_criterion}</p>
   {(skills.length > 0 || milestone) && <div className="todo-tags">{skills.map(skill => <span className="todo-skill" key={skill}>{skill}</span>)}{milestone && <span className="small">{milestone.title}</span>}</div>}
   {saveNotes && session.task_id && (() => { const task = plan.editable_tasks?.find(item => item.id === session.task_id); const has = !!task?.notes?.blocks.length;
    return <details className="todo-notes" open={has || undefined}><summary>{has ? 'Notes' : 'Add notes'}</summary><NotesEditor label={`Notes for ${session.task}`} value={task?.notes} disabled={frozen} onSave={doc => saveNotes(session.task_id!, doc)}/></details>; })()}
   {session.evidence_note && <p className="small">Your note: {session.evidence_note}</p>}
   {session.status === 'completed' && !session.evidence_note && complete && <details className="todo-note"><summary>Add what you produced</summary>
    <label>What did you produce? (optional)<textarea maxLength={2000} value={note} onChange={event => setNote(event.target.value)} /></label>
    <button type="button" className="btn ghost" disabled={frozen || !note.trim()} onClick={() => void complete(session, note)}>Save note</button>
   </details>}
  </div>
 </li>;
}

function MonthView({ cursor, today, plan, review, sessions, open }: { cursor: string; today: string; plan: PlannedRoadmap; review: PlanReview; sessions: PlanAssignment[]; open: (monday: string) => void }) {
 const usable = new Map(review.remaining.weeks.map(week => [week.week_start, week.usable_minutes]));
 return <div className="month-view">
  <div className="month-head" aria-hidden="true">{weekDates('2030-01-07').map(day => <span key={day}>{weekdayName(day)}</span>)}</div>
  <ol className="month-weeks">{monthWeeks(cursor).map(monday => {
   const dates = weekDates(monday);
   const inWeek = sessions.filter(session => dates.includes(session.date));
   const done = inWeek.filter(session => session.status === 'completed').length;
   const bars = plan.milestones.flatMap(milestone => { const columns = weekColumns(monday, milestone.projected_start, milestone.projected_end); return columns ? [{ milestone, ...columns }] : []; });
   const minutes = usable.get(monday);
   const planned = inWeek.length ? `${count(inWeek.length, 'session')}, ${done} done` : bars.length ? 'Sessions not planned yet' : 'Nothing planned';
   const label = [`Open week of ${fullDate(monday)}`, planned, minutes !== undefined && `${hours(minutes)} available`, ...bars.map(bar => bar.milestone.title)].filter(Boolean).join('. ');
   return <li key={monday}><button type="button" className={`month-week${dates.includes(today) ? ' current' : ''}`} aria-label={label} onClick={() => open(monday)}>
    <span className="month-grid" aria-hidden="true">
     {dates.map(day => { const items = inWeek.filter(session => session.date === day); return <span key={day} className={`month-day${monthKey(day) !== monthKey(cursor) ? ' outside' : ''}${day === today ? ' today' : ''}`}>
      <b>{dayOfMonth(day)}</b><span className="month-dots">{items.slice(0, 4).map(item => <i key={item.id} className={item.status === 'completed' ? 'done' : ''} />)}</span>
     </span>; })}
     {bars.slice(0, MAX_BARS).map(({ milestone, from, to, startsHere, endsHere }: { milestone: PlanMilestone; from: number; to: number; startsHere: boolean; endsHere: boolean }) => <span key={milestone.id} className={`month-bar${startsHere ? ' starts' : ''}${endsHere ? ' ends' : ''}${milestone.outcome.demonstrated ? ' reached' : ''}`} style={{ gridColumn: `${from} / ${to + 1}` }}>{milestone.title}</span>)}
     {bars.length > MAX_BARS && <span className="month-more">+{bars.length - MAX_BARS} more</span>}
    </span>
    <span className="month-summary" aria-hidden="true"><strong>{planned}</strong>{minutes !== undefined && <span>{hours(minutes)} available</span>}</span>
   </button></li>;
  })}</ol>
  <p className="small">Bars are milestones and dots are sessions. Choose a week to see its to-do list.</p>
 </div>;
}

/** The roadmap's working surface: the sessions to tick off, seen by day or week, and each week at a glance by month. */
export function TaskPlanner({ plan, review, frozen, complete, reopen, saveNotes = null }: { plan: PlannedRoadmap; review: PlanReview; frozen: boolean; complete: ((session: PlanAssignment, note: string) => Promise<unknown>) | null; reopen: ((session: PlanAssignment) => Promise<unknown>) | null; saveNotes?: SaveNotes }) {
 const today = review.remaining.resolved.today;
 const sessions = [...plan.assignments].sort(bySchedule);
 const next = sessions.find(session => session.id === review.next_assignment_id);
 const edges = [plan.config.start_date, plan.config.target_date, ...sessions.map(session => session.date), ...plan.milestones.flatMap(item => [item.projected_start, item.projected_end])].filter((value): value is string => !!value).sort();
 const first = edges[0] || today; const last = edges[edges.length - 1] || today;
 const [view, setView] = useState<View>('week');
 const [cursor, setCursor] = useState(next?.date || (today >= first && today <= last ? today : plan.first_planning_week));

 const week = weekDates(cursor);
 const shown = view === 'day' ? sessions.filter(session => session.date === cursor) : sessions.filter(session => week.includes(session.date));
 const done = shown.filter(session => session.status === 'completed');
 const left = shown.filter(session => session.status === 'scheduled').reduce((total, session) => total + session.duration_minutes, 0);
 const milestones = plan.milestones.filter(item => weekColumns(weekStart(cursor), item.projected_start, item.projected_end));
 const available = review.remaining.weeks.find(item => item.week_start === weekStart(cursor))?.usable_minutes;

 const noun = view === 'day' ? 'day' : view;
 const previous = view === 'day' ? addDays(cursor, -1) : view === 'week' ? addDays(weekStart(cursor), -7) : addMonths(cursor, -1);
 const following = view === 'day' ? addDays(cursor, 1) : view === 'week' ? addDays(weekStart(cursor), 7) : addMonths(cursor, 1);
 const canGoBack = view === 'day' ? previous >= first : view === 'week' ? addDays(previous, 6) >= first : monthKey(previous) >= monthKey(first);
 const canGoOn = view === 'month' ? monthKey(following) <= monthKey(last) : following <= last;
 const sameWeek = week.includes(today);
 const onToday = view === 'day' ? cursor === today : view === 'week' ? sameWeek : monthKey(cursor) === monthKey(today);
 const title = view === 'month' ? monthTitle(cursor)
  : view === 'day' ? (cursor === today ? 'Today' : longDate(cursor))
  : sameWeek ? 'This week' : `Week of ${shortDate(weekStart(cursor))}`;
 const days = [...new Set(shown.map(session => session.date))];
 const item = (session: PlanAssignment) => <TaskItem key={session.id} session={session} plan={plan} review={review} frozen={frozen} complete={complete} reopen={reopen} saveNotes={saveNotes} />;

 return <section className="task-planner" aria-label="To-do list">
  <header className="task-head">
   <div className="task-title">
    <h2>{title}</h2>
    {view !== 'month' && shown.length > 0 && <p className="small">{done.length} of {count(shown.length, 'session')} done{left > 0 ? `, ${hours(left)} left` : ''}</p>}
   </div>
   <div className="task-controls">
    <div className="task-views" role="group" aria-label="To-do view">{views.map(([value, label]) => <button key={value} type="button" aria-pressed={view === value} onClick={() => setView(value)}>{label}</button>)}</div>
    <div className="task-nav">
     {!onToday && today >= first && today <= last && <button type="button" className="task-today" onClick={() => setCursor(today)}>Today</button>}
     <button type="button" aria-label={`Previous ${noun}`} disabled={!canGoBack} onClick={() => setCursor(previous)}>‹</button>
     <button type="button" aria-label={`Next ${noun}`} disabled={!canGoOn} onClick={() => setCursor(following)}>›</button>
    </div>
   </div>
  </header>
  {view !== 'month' && shown.length > 0 && <div className="task-progress" aria-hidden="true"><i style={{ width: `${done.length / shown.length * 100}%` }} /></div>}

  {view === 'day' && <div className="day-strip" role="group" aria-label="Choose a day">{week.map(day => { const items = sessions.filter(session => session.date === day); return <button key={day} type="button" aria-pressed={day === cursor} className={day === today ? 'today' : undefined} aria-label={`${longDate(day)}, ${count(items.length, 'session')}`} onClick={() => setCursor(day)}><span>{weekdayName(day)}</span><b>{dayOfMonth(day)}</b><span className="month-dots">{items.slice(0, 4).map(entry => <i key={entry.id} className={entry.status === 'completed' ? 'done' : ''} />)}</span></button>; })}</div>}

  {view === 'month' && <MonthView cursor={cursor} today={today} plan={plan} review={review} sessions={sessions} open={monday => { setCursor(sessions.find(session => weekDates(monday).includes(session.date))?.date || monday); setView('week'); }} />}

  {view === 'week' && days.map(day => <div className="todo-day" key={day}>
   <h3><button type="button" className="todo-day-link" aria-label={`Open ${longDate(day)}`} onClick={() => { setCursor(day); setView('day'); }}>{day === today ? 'Today' : weekdayName(day)}<span>{shortDate(day)}</span></button></h3>
   <ul className="todo-list">{shown.filter(session => session.date === day).map(item)}</ul>
  </div>)}
  {view === 'day' && shown.length > 0 && <ul className="todo-list">{shown.map(item)}</ul>}

  {view === 'day' && !shown.length && <p className="task-empty">Nothing is planned for {longDate(cursor)}.</p>}
  {view === 'week' && !shown.length && <div className="task-empty">
   {addDays(weekStart(cursor), 6) < today ? <p>No sessions were planned for this week.</p> : <p>Sessions for this week aren’t planned yet. Elo plans one week at a time, so preview an updated roadmap when you get here.</p>}
   {available !== undefined && <p className="small">{hours(available)} available this week.</p>}
   {milestones.length > 0 && <><h3>Milestones this week</h3><ul>{milestones.map(entry => <li key={entry.id}>{entry.title}</li>)}</ul></>}
  </div>}
  {view !== 'month' && shown.length > 0 && complete && <p className="small task-foot">Ticking a session records what you did. It doesn’t change your assessed skills.</p>}
  {!complete && <p className="small task-foot">Accept this plan to start ticking off sessions.</p>}
 </section>;
}

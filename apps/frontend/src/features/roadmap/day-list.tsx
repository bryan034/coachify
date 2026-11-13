"use client";
import { useCallback, useEffect, useRef, useState } from 'react';
import { shortDate, weekdayName } from './roadmap-calendar';
import { blockLabel, busyRanges, hourWidths, isDone, listOrder, nextFree, onDay, shortLength, studyBlocks, timeRange, timelineLanes, toClock } from './roadmap-day';
import { TaskForm, UnsavedDialog, blankDraft, changedParts, changesOf, draftOf, isDirty, newSessionOf, type SkillOption, type TaskDraft } from './task-form';
import type { BacklogPlan, FreeTimes, NewSession, PlanGap, PlanMilestone, PlanReview, PlannedRoadmap, Session, SessionChanges, Confirmation } from './types';

export type RoadmapActions = {
 setDone: (session: Session, done: boolean) => Promise<boolean>;
 saveSession: (id: string, changes: SessionChanges, allowOverlap: boolean) => Promise<boolean>;
 addSession: (session: NewSession, allowOverlap: boolean) => Promise<boolean>;
 move: (moves: { session_id: string; date: string; start_time: string }[]) => Promise<boolean>;
 skip: (id: string) => Promise<boolean>;
 freeTimes: (minutes: number, sessionId?: string) => Promise<FreeTimes | null>;
 backlogPlan: (sessionIds?: string[]) => Promise<BacklogPlan | null>;
 recordOutcome: (milestone: PlanMilestone, demonstrated: boolean, note: string) => void;
 reachCheckpoint: (milestone: PlanMilestone, key: string, reached: boolean) => void;
 confirm: (gap: PlanGap, answer: Confirmation['answer']) => void;
};
export type ViewName = 'day' | 'week' | 'month' | 'milestones' | 'progress';
/** What every roadmap view needs: the plan, its to-do rows, the plan's own "today" and the writes. */
export type ViewContext = { plan: PlannedRoadmap; review: PlanReview; sessions: Session[]; today: string; nowMinute: number | null; version: number; catalog: SkillOption[]; frozen: boolean; actions: RoadmapActions; go: (view: ViewName, date?: string) => void };

/** The current minute in the plan's time zone, refreshed each minute. Null where the zone is unknown to the browser. */
export function useNowMinute(timeZone: string) {
 const read = useCallback(() => {
  try { const parts = new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date()); return Number(parts.find(part => part.type === 'hour')?.value) * 60 + Number(parts.find(part => part.type === 'minute')?.value); }
  catch { return null; }
 }, [timeZone]);
 const [minute, setMinute] = useState<number | null>(read);
 useEffect(() => { setMinute(read()); const timer = setInterval(() => setMinute(read()), 60000); return () => clearInterval(timer); }, [read]);
 return minute;
}
export const dayPhrase = (day: string, today: string) => day === today ? 'today' : `on ${weekdayName(day)} ${shortDate(day)}`;

type Editing = { id: string; draft: TaskDraft; base: TaskDraft };
type Adding = { date: string; draft: TaskDraft; base: TaskDraft };
/** One open task (or one new task) per view, with the unsaved-changes rule applied to every way of leaving it. */
export function useTaskEditor(context: ViewContext) {
 const { sessions, actions, plan, today, nowMinute } = context;
 const [editing, setEditing] = useState<Editing | null>(null);
 const [adding, setAdding] = useState<Adding | null>(null);
 const [pending, setPending] = useState<(() => void) | null>(null);
 const [busy, setBusy] = useState(false); const [problem, setProblem] = useState('');
 const session = editing ? sessions.find(item => item.id === editing.id) : undefined;
 const dirty = !!editing && isDirty(editing.draft, editing.base);
 // The task can disappear in another session; an editor without its task closes.
 useEffect(() => { if (editing && !session) setEditing(null); }, [editing, session]);
 const leave = (next: () => void) => { if (dirty) setPending(() => next); else next(); };
 const close = () => { setEditing(null); setProblem(''); };
 const scrollTo = (id: string) => setTimeout(() => document.getElementById(`row-${id}`)?.scrollIntoView?.({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }), 60);
 const open = (id: string, scroll = false) => {
  if (editing?.id === id) { if (scroll) scrollTo(id); else leave(close); return; }
  const target = sessions.find(item => item.id === id); if (!target) return;
  leave(() => { const base = draftOf(target); setAdding(null); setProblem(''); setEditing({ id, draft: base, base }); if (scroll) scrollTo(id); });
 };
 const startNew = (date: string) => leave(() => {
  const base = blankDraft(nextFree(plan.config, date, onDay(sessions, date), 30, date === today ? nowMinute ?? 0 : 0));
  setEditing(null); setProblem(''); setAdding({ date, draft: base, base });
 });
 async function save(allowOverlap = false, then?: () => void) {
  if (!editing || !session || busy) return;
  const changes = changesOf(editing.draft, editing.base, session);
  setBusy(true); setProblem('');
  const saved = Object.keys(changes).length ? await actions.saveSession(session.id, changes, allowOverlap) : true;
  setBusy(false);
  if (!saved) { setPending(null); setProblem('This wasn’t saved. Your changes are still here, so you can try again.'); return; }
  close(); setPending(null); then?.();
 }
 async function add(allowOverlap: boolean) {
  if (!adding || busy) return;
  setBusy(true); setProblem('');
  const saved = await actions.addSession(newSessionOf(adding.draft, adding.date), allowOverlap);
  setBusy(false);
  if (saved) setAdding(null); else setProblem('This task wasn’t added. Your details are still here, so you can try again.');
 }
 const dialog = pending && editing && <UnsavedDialog text={`You changed ${changedParts(editing.draft, editing.base)} for “${editing.base.title}”. These changes haven’t been saved.`} canSave={!!editing.draft.title.trim() && !busy}
  save={() => { const next = pending; void save(true, next); }} discard={() => { const next = pending; setPending(null); close(); next(); }} keep={() => setPending(null)} />;
 return { editing, adding, busy, problem, open, close, leave, startNew, save, add, dialog,
  change: (patch: Partial<TaskDraft>) => setEditing(current => current && { ...current, draft: { ...current.draft, ...patch } }),
  changeNew: (patch: Partial<TaskDraft>) => setAdding(current => current && { ...current, draft: { ...current.draft, ...patch } }),
  cancelNew: () => { setAdding(null); setProblem(''); } };
}
export type TaskEditor = ReturnType<typeof useTaskEditor>;

export function BusyLabels({ sessions }: { sessions: Session[] }) {
 const ranges = busyRanges(sessions);
 if (!ranges.length) return null;
 return <span className="rv-busy"><span className="rv-vh">Busy times:</span>{ranges.map(range => <span className="rv-blk" key={range}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>{range}</span>)}</span>;
}

const Tick = ({ size = 14 }: { size?: number }) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10" /></svg>;
export { Tick };

/** A day's to-do rows. A row's title or ⓘ opens its details underneath; the dashed row adds a task of the user's own. */
export function TaskList({ day, items, context, editor, nextId = null, canAdd = true, addLabel = 'New task', readOnly = false }: { day: string; items: Session[]; context: ViewContext; editor: TaskEditor | null; nextId?: string | null; canAdd?: boolean; addLabel?: string; readOnly?: boolean }) {
 const { actions, frozen, today, sessions, plan, nowMinute, catalog } = context;
 const [ticking, setTicking] = useState<Record<string, boolean>>({});
 // The tick shows at once. The saved status takes over when the request ends, so a failure undoes it.
 const tick = (session: Session, done: boolean) => { setTicking(current => ({ ...current, [session.id]: done })); void actions.setDone(session, done).finally(() => setTicking(current => { const next = { ...current }; delete next[session.id]; return next; })); };
 const shown = items.map(item => item.id in ticking ? { ...item, status: ticking[item.id] ? 'completed' as const : 'scheduled' as const } : item).sort(listOrder);
 const where = dayPhrase(day, today);
 const adding = editor?.adding?.date === day ? editor.adding : null;
 return <ul className="rv-list">
  {shown.map(session => {
   const done = isDone(session); const open = editor?.editing?.id === session.id;
   return [<li key={session.id} id={`row-${session.id}`} className={`rv-task${done ? ' done' : ''}`}>
    {readOnly ? <span className="rv-ck static" aria-hidden="true" /> : <button type="button" className="rv-ck" aria-pressed={done} aria-label={`${done ? 'Mark not done' : 'Mark done'}: ${session.title}`} disabled={frozen} onClick={() => tick(session, !done)}>{done && <Tick />}</button>}
    <div className="rv-task-body">
     {editor ? <button type="button" className="rv-ttl" aria-expanded={open} onClick={() => editor.open(session.id)}>{session.title}</button> : <div className="rv-ttl">{session.title}</div>}
     <div className="rv-task-meta"><span>{timeRange(session)}</span><span>{shortLength(session.duration_minutes)}</span>
      {session.skills.map(skill => <span className="rv-tag sk" key={skill.name}>{skill.name}</span>)}
      {session.id === nextId && !done && <span className="rv-tag dk">Up next</span>}
      {session.kind === 'diagnostic' && <span className="rv-tag">Diagnostic</span>}
      {session.moved_from_backlog && <span className="rv-tag am">Moved from backlog</span>}
      {session.origin === 'user' && !session.moved_from_backlog && <span className="rv-tag">Your task</span>}
     </div>
    </div>
    {editor && <button className="rv-ico" type="button" aria-label={`Details for ${session.title}`} aria-expanded={open} onClick={() => editor.open(session.id)}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h0" /></svg></button>}
   </li>,
   open && editor && <li key={`${session.id}-veil`} aria-hidden="true" style={{ listStyle: 'none' }}><button type="button" tabIndex={-1} className="rv-backdrop" onClick={() => editor.leave(editor.close)} /></li>,
   open && editor && <li key={`${session.id}-details`} className="rv-det-wrap">
    <TaskForm mode="edit" draft={editor.editing!.draft} base={editor.editing!.base} session={session} date={day} where={where} others={onDay(sessions, day).filter(item => item.id !== session.id)} config={plan.config} nowMinute={null}
     catalog={catalog} disabled={frozen || editor.busy} problem={editor.problem} onChange={editor.change} onSubmit={allow => void editor.save(allow)} onCancel={editor.close} onEscape={() => editor.leave(editor.close)} />
   </li>];
  })}
  {editor && !readOnly && canAdd && !adding && <li style={{ listStyle: 'none' }}><button type="button" className="rv-addrow" disabled={frozen} onClick={() => editor.startNew(day)}><span className="rv-ring" aria-hidden="true" />{addLabel}</button></li>}
  {editor && adding && <li style={{ listStyle: 'none' }}>
   <TaskForm mode="new" draft={adding.draft} base={adding.base} date={day} where={where} others={onDay(sessions, day)} config={plan.config} nowMinute={day === today ? nowMinute : null}
    catalog={catalog} disabled={frozen || editor.busy} problem={editor.problem} onChange={editor.changeNew} onSubmit={allow => void editor.add(allow)} onCancel={editor.cancelNew} onEscape={editor.cancelNew} />
  </li>}
 </ul>;
}

const HOUR = 60;
/** The day as a 00:00–24:00 track. Hovering an hour magnifies it; choosing a task opens it in the list. */
export function DayTimeline({ day, items, context, editor }: { day: string; items: Session[]; context: ViewContext; editor: TaskEditor }) {
 const [hovered, setHovered] = useState<number | null>(null);
 const scroller = useRef<HTMLDivElement>(null);
 const { items: placed, lanes } = timelineLanes(items);
 const scale = hourWidths(HOUR, hovered);
 const blocks = studyBlocks(context.plan.config, day);
 const anytime = items.filter(item => !item.start_time);
 const first = placed[0]?.start ?? blocks[0]?.[0] ?? 19 * 60;
 // Opens with the day's first task near the middle of what is visible.
 useEffect(() => { const box = scroller.current; if (box) box.scrollLeft = Math.max(0, first / 60 * HOUR - box.clientWidth * 0.45); }, [day, first]);
 const label = placed.length ? `${placed.length} ${placed.length === 1 ? 'task' : 'tasks'} with a set time: ${placed.map(item => `${timeRange(item.session)} ${item.session.title}`).join('; ')}` : 'No tasks with a set time';
 return <section className="rv-dl" aria-label="Your day, 00:00 to 24:00">
  <div className="rv-row-between" style={{ alignItems: 'baseline' }}><h3>Your day</h3><span className="rv-note" style={{ fontSize: 12 }}>Hover over an hour to zoom in. Scroll sideways for all 24 hours; choose a task to open it below.</span></div>
  <div className="rv-dl-scroll" ref={scroller}>
   <div className="rv-dl-track" role="group" aria-label={label} style={{ width: scale.total, height: 44 + lanes * 40 + 6 }}
    onMouseMove={event => { const cell = (event.target as HTMLElement).closest?.('[data-h]'); const hour = cell ? Number(cell.getAttribute('data-h')) : null; if (hour !== hovered) setHovered(hour); }} onMouseLeave={() => setHovered(null)}>
    {scale.widths.map((width, hour) => <span key={hour} className={`rv-dl-hour${hour === hovered ? ' hot' : ''}`} aria-hidden="true" data-h={hour} style={{ left: scale.edges[hour], width }}>{toClock(hour * 60)}</span>)}
    {blocks.map(([start, end]) => <span key={start} className="rv-dl-study" aria-hidden="true" style={{ left: scale.x(start), width: scale.x(Math.min(end, 1439)) - scale.x(start) }}>Study block</span>)}
    {day === context.today && context.nowMinute !== null && <span className="rv-dl-now" aria-hidden="true" style={{ left: scale.x(context.nowMinute) }}><b>Now</b></span>}
    {placed.map(({ session, start, end, lane }) => <button key={session.id} type="button" data-h={Math.floor(start / 60)} className={`rv-dl-task${isDone(session) ? ' done' : ''}${editor.editing?.id === session.id ? ' open' : ''}`}
     style={{ left: scale.x(start) + 1, width: Math.max(scale.x(Math.min(end, 1439)) - scale.x(start) - 2, 24), top: 44 + lane * 40 }} title={`${session.title} · ${timeRange(session)}`}
     aria-label={`${session.title}, ${timeRange(session)}${isDone(session) ? ', done' : ''}. Open this task in the list.`} onFocus={() => setHovered(Math.floor(start / 60))} onBlur={() => setHovered(null)} onClick={() => editor.open(session.id, true)}>{session.title}</button>)}
   </div>
  </div>
  {anytime.length > 0 && <div className="rv-dl-any">No set time: {anytime.map(session => <button key={session.id} className="rv-opt" type="button" onClick={() => editor.open(session.id, true)}>{session.title}</button>)}</div>}
 </section>;
}

export const studyBlockLine = (context: ViewContext, day: string) => { const blocks = studyBlocks(context.plan.config, day); return blocks.length ? `Your study ${blocks.length === 1 ? 'block' : 'blocks'} ${blockLabel(blocks)}` : 'A rest day in your plan'; };

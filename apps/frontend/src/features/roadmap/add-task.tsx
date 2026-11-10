"use client";
import { useId, useState, type FormEvent } from 'react';
import { clockRange } from './roadmap-calendar';
import { hours, longDate } from './settings-panel';
import type { PlannedRoadmap } from './types';

/** What the roadmap service needs to add one scheduled task of the user's own. */
export type NewTask = { title: string; instructions: string; completion_outcome: string; estimated_minutes: number; requirement_refs: string[]; prerequisites: string[]; milestone_key: string | null; schedule: { date: string; start_time: string; duration_minutes: number }[] };
export type AddTask = (task: NewTask) => Promise<boolean>;

const DURATIONS = [15, 30, 45, 60, 90, 120];
const toMinutes = (clock: string) => { const [hour, minute] = clock.split(':').map(Number); return hour * 60 + minute; };
const weekdayOf = (value: string) => (new Date(`${value}T12:00:00Z`).getUTCDay() + 6) % 7;
const clock12 = (clock: string) => { const [hour, minute] = clock.split(':').map(Number); return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'am' : 'pm'}`; };

/** Builds the task from the form. Exported for tests; the backend still validates every field. */
export function newTask(plan: PlannedRoadmap, { title, date, start, minutes, gapId }: { title: string; date: string; start: string; minutes: number; gapId: string }): NewTask {
 const name = title.trim();
 const gap = plan.gaps.find(item => item.id === gapId);
 const milestone = gap ? plan.milestones.find(item => item.gap_ids.includes(gap.id)) : undefined;
 return { title: name, instructions: name, completion_outcome: `You finished “${name}”.`, estimated_minutes: minutes,
  requirement_refs: gap?.requirement_ref ? [gap.requirement_ref] : [], prerequisites: [], milestone_key: milestone?.key ?? null,
  schedule: [{ date, start_time: start, duration_minutes: minutes }] };
}

/** A small page for one new task: big title, then a property list, as in the redesign canvas. */
export function AddTaskForm({ plan, date, add, cancel }: { plan: PlannedRoadmap; date: string; add: AddTask; cancel: () => void }) {
 const id = useId();
 const blocks = plan.config.blocks.filter(block => block.day === weekdayOf(date)).sort((a, b) => a.start_time.localeCompare(b.start_time));
 const [title, setTitle] = useState('');
 const [slot, setSlot] = useState<string>(blocks[0] ? `block:${blocks[0].start_time}` : 'custom');
 const [custom, setCustom] = useState('19:00');
 const [minutes, setMinutes] = useState(plan.config.preferred_session_minutes || 60);
 const [gapId, setGapId] = useState('');
 const [busy, setBusy] = useState(false);
 const [problem, setProblem] = useState('');
 const start = slot === 'custom' ? custom : slot.slice(6);
 const endsTooLate = !!start && toMinutes(start) + minutes > 1440;
 const ready = title.trim().length > 0 && !!start && !endsTooLate && !busy;
 const weekly = plan.config.weekly_minutes;

 async function submit(event: FormEvent) {
  event.preventDefault();
  if (!ready) return;
  setBusy(true); setProblem('');
  const saved = await add(newTask(plan, { title, date, start, minutes, gapId }));
  setBusy(false);
  if (saved) cancel(); else setProblem('This task wasn’t added. Your details are still here, so you can try again.');
 }

 return <li className="add-task">
  <form aria-label={`New task for ${longDate(date)}`} onSubmit={event => void submit(event)} onKeyDown={event => { if (event.key === 'Escape') cancel(); }}>
   <div className="add-task-crumb"><span>Roadmap <span aria-hidden="true">/</span> {longDate(date)} <span aria-hidden="true">/</span> <strong>New task</strong></span><button type="button" className="add-task-close" aria-label="Cancel new task" onClick={cancel}>×</button></div>
   <label className="visually-hidden" htmlFor={`${id}-title`}>What would you like to do?</label>
   <input id={`${id}-title`} className="add-task-title" type="text" maxLength={160} autoFocus value={title} onChange={event => setTitle(event.target.value)} placeholder="What would you like to do?" />
   <div className="add-task-props">
    <div className="add-task-prop"><span className="add-task-key">Day</span><span>{longDate(date)}</span></div>
    <div className="add-task-prop"><label className="add-task-key" htmlFor={`${id}-skill`}>What skill does it build</label>
     <select id={`${id}-skill`} value={gapId} onChange={event => setGapId(event.target.value)}><option value="">No specific skill</option>{plan.gaps.map(gap => <option key={gap.id} value={gap.id}>{gap.name}</option>)}</select></div>
    <fieldset className="add-task-prop"><legend className="add-task-key">Time slot</legend><div className="add-task-options">
     {blocks.map(block => <button key={block.start_time} type="button" aria-pressed={slot === `block:${block.start_time}`} onClick={() => setSlot(`block:${block.start_time}`)}>{block.kind === 'preferred' ? 'Preferred' : 'Backup'} · {clock12(block.start_time)}</button>)}
     <button type="button" aria-pressed={slot === 'custom'} onClick={() => setSlot('custom')}>Custom</button>
     {slot === 'custom' && <label className="add-task-inline">Starts <input type="time" step={300} value={custom} onChange={event => setCustom(event.target.value)} /></label>}
    </div></fieldset>
    <fieldset className="add-task-prop"><legend className="add-task-key">Duration</legend><div className="add-task-options">
     {DURATIONS.map(value => <button key={value} type="button" aria-pressed={minutes === value} onClick={() => setMinutes(value)}>{hours(value)}</button>)}
     {!DURATIONS.includes(minutes) && <button type="button" aria-pressed="true">{hours(minutes)}</button>}
    </div></fieldset>
   </div>
   {start && !endsTooLate && <p className="small">{clockRange(start, minutes)} on {longDate(date)}.</p>}
   {endsTooLate && <p className="small" role="alert">A task must end by midnight. Choose an earlier start or a shorter duration.</p>}
   <p className="small">{weekly ? `Counts towards your ${hours(weekly)} a week. ` : ''}Blocked-out times can’t be used.</p>
   {problem && <p role="alert">{problem}</p>}
   <div className="add-task-actions"><button type="button" className="btn ghost" onClick={cancel}>Cancel</button><button type="submit" className="btn pri" disabled={!ready}>{busy ? 'Adding…' : 'Add to roadmap'}</button></div>
  </form>
 </li>;
}

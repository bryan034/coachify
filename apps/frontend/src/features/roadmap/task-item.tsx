"use client";
import { useRef, useState } from 'react';
import { longDate } from './settings-panel';
import type { ActionResult, PlanAssignment, PlanMilestone, TaskFeedback } from './types';

export type Act = (path: string, data: Record<string, unknown>) => Promise<ActionResult>;
const endTime = (start: string, minutes: number) => { const [hour, minute] = start.split(':').map(Number); const end = hour * 60 + minute + minutes; return `${String(Math.floor(end / 60) % 24).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}`; };
export const taskWhen = (task: { date: string | null; start_time: string | null; duration_minutes: number }) => task.date && task.start_time ? `${longDate(task.date)}, ${task.start_time}–${endTime(task.start_time, task.duration_minutes)}` : 'Not scheduled';
const feedbackChoices: [TaskFeedback, string][] = [['too_easy', 'Too easy'], ['about_right', 'About right'], ['too_hard', 'Too hard']];
const confirmable = ['outside_study_blocks', 'paused_week'];

/** Choose a date and time. The backend validates the slot and explains any problem here. */
export function MoveForm({ task, act, frozen, close, suggested }: { task: PlanAssignment; act: Act; frozen: boolean; close: () => void; suggested?: { date: string; start_time: string } | null }) {
 const [date, setDate] = useState(suggested?.date || task.date || ''); const [time, setTime] = useState(suggested?.start_time || task.start_time || '');
 const [problem, setProblem] = useState<{ code: string; message: string } | null>(null);
 async function submit(confirm: boolean) {
  const result = await act('/planner/tasks/move', { task_id: task.id, date, start_time: time, confirm_outside_blocks: confirm });
  if (result.ok) close(); else setProblem(result);
 }
 const asking = !!problem && confirmable.includes(problem.code);
 return <form className="task-form" aria-label={`Move ${task.task}`} onSubmit={event => { event.preventDefault(); void submit(false); }}>
  <label>Date<input type="date" required autoFocus value={date} onChange={event => { setDate(event.target.value); setProblem(null); }} /></label>
  <label>Time<input type="time" required value={time} onChange={event => { setTime(event.target.value); setProblem(null); }} /></label>
  <div className="task-form-actions">
   {asking
    ? <button type="button" className="btn" disabled={frozen} onClick={() => void submit(true)}>Place it there anyway</button>
    : <button className="btn" disabled={frozen || !date || !time}>Save time</button>}
   <button type="button" className="btn ghost" onClick={close}>Cancel</button>
  </div>
  {problem && <p className="task-problem" role="alert">{problem.message}</p>}
 </form>;
}

export function TaskItem({ task, milestone, act, frozen, next, readOnly, suggested }: { task: PlanAssignment; milestone?: PlanMilestone; act: Act; frozen: boolean; next?: boolean; readOnly?: boolean; suggested?: { date: string; start_time: string } | null }) {
 const [panel, setPanel] = useState<'move' | 'note' | null>(null); const [note, setNote] = useState(task.note || ''); const [problem, setProblem] = useState('');
 const [justCompleted, setJustCompleted] = useState(false);
 const opener = useRef<HTMLButtonElement>(null);
 const open = task.status === 'scheduled' || task.status === 'backlog';
 const closed = task.status === 'skipped' || task.status === 'removed';
 const name = task.task;
 async function run(path: string, data: Record<string, unknown>) { const result = await act(path, data); setProblem(result.ok ? '' : result.message); return result.ok; }
 const closePanel = () => { setPanel(null); requestAnimationFrame(() => opener.current?.focus()); };
 return <li className={`task-item ${task.status}${task.action_needed ? ' needs-action' : ''}`}>
  <div className="task-when"><strong>{taskWhen(task)}</strong><span>{task.duration_minutes} min</span>
   <span className="task-badges">{next && <span className="pill n">Next</span>}{task.status === 'completed' && <span className="pill n">Done</span>}{task.status === 'skipped' && <span className="pill n">Skipped</span>}{task.status === 'removed' && <span className="pill n">Removed</span>}{task.pinned && <span className="pill n">Pinned</span>}{task.origin === 'custom' && <span className="pill n">Custom</span>}{task.origin === 'custom' && !task.count_hours && <span className="pill n">Not in hours</span>}{task.kind === 'diagnostic' && <span className="pill n">Diagnostic</span>}</span>
  </div>
  <p className="task-title">{name}</p>
  {task.completion_criterion && <p className="small">Done when: {task.completion_criterion}</p>}
  {milestone && <p className="small">Milestone: {milestone.title}</p>}
  {!!task.depends_on?.length && <p className="small">Follows earlier work in this plan.</p>}
  {task.refresher_reason && <p className="small">Why it returns: {task.refresher_reason}</p>}
  {task.note && <p className="small">Your note: {task.note}</p>}
  {task.evidence_note && <p className="small">What you produced: {task.evidence_note}</p>}
  {task.action_needed && <p className="task-action-needed">{task.action_needed.message}</p>}
  {!readOnly && <>
   {open && <div className="task-actions">
    <button type="button" className="btn" disabled={frozen} aria-label={`Complete ${name}`} onClick={async () => { if (await run('/planner/assignments/status', { assignment_id: task.id, status: 'completed' })) setJustCompleted(true); }}>Complete</button>
    <button type="button" className="btn ghost" disabled={frozen} aria-label={`Skip ${name}`} onClick={() => void run('/planner/tasks/skip', { task_id: task.id })}>Skip</button>
    <button ref={opener} type="button" className="btn ghost" disabled={frozen} aria-expanded={panel === 'move'} aria-label={`${task.status === 'backlog' ? 'Place' : 'Move'} ${name}`} onClick={() => setPanel(panel === 'move' ? null : 'move')}>{task.status === 'backlog' ? 'Place' : 'Move'}</button>
    <button type="button" className="btn ghost" disabled={frozen} aria-pressed={task.pinned} aria-label={`${task.pinned ? 'Unpin' : 'Pin'} ${name}`} onClick={() => void run('/planner/tasks/update', { task_id: task.id, pinned: !task.pinned })}>{task.pinned ? 'Unpin' : 'Pin'}</button>
    <button type="button" className="btn ghost" disabled={frozen} aria-expanded={panel === 'note'} aria-label={`Note on ${name}`} onClick={() => setPanel(panel === 'note' ? null : 'note')}>Note</button>
    {task.origin === 'custom' && <label className="settings-check task-hours"><input type="checkbox" disabled={frozen} checked={task.count_hours} onChange={event => void run('/planner/tasks/update', { task_id: task.id, count_hours: event.target.checked })} />Count in hours</label>}
   </div>}
   {panel === 'move' && <MoveForm task={task} act={act} frozen={frozen} close={closePanel} suggested={suggested} />}
   {panel === 'note' && <form className="task-form" aria-label={`Note on ${name}`} onSubmit={async event => { event.preventDefault(); if (await run('/planner/tasks/update', { task_id: task.id, note })) closePanel(); }}>
    <label>Note (optional)<textarea autoFocus maxLength={2000} value={note} onChange={event => setNote(event.target.value)} /></label>
    <div className="task-form-actions"><button className="btn" disabled={frozen}>Save note</button><button type="button" className="btn ghost" onClick={closePanel}>Cancel</button></div>
   </form>}
   {task.status === 'completed' && <div className="task-feedback" role="group" aria-label={`How was ${name}?`}>
    <span className="small">{justCompleted && !task.feedback ? 'Done. How was it? (optional)' : 'How was it? (optional)'}</span>
    {feedbackChoices.map(([value, label]) => <button key={value} type="button" className={`chip sm${task.feedback === value ? ' selected' : ''}`} aria-pressed={task.feedback === value} disabled={frozen} onClick={() => void run('/planner/tasks/update', { task_id: task.id, feedback: value })}>{label}</button>)}
    <button type="button" className="settings-link" disabled={frozen} onClick={() => void run('/planner/assignments/status', { assignment_id: task.id, status: 'scheduled' })}>Reopen</button>
   </div>}
   {closed && <div className="task-actions"><button type="button" className="btn ghost" disabled={frozen} aria-label={`Return ${name} to Backlog`} onClick={() => void run('/planner/tasks/restore', { task_id: task.id })}>Return to Backlog</button></div>}
   {problem && <p className="task-problem" role="alert">{problem}</p>}
  </>}
 </li>;
}

/** Add a custom task to a week, with an optional placement. */
export function AddTaskForm({ week, milestones, act, frozen, close }: { week: string; milestones: PlanMilestone[]; act: Act; frozen: boolean; close: () => void }) {
 const [title, setTitle] = useState(''); const [minutes, setMinutes] = useState(60); const [date, setDate] = useState(''); const [time, setTime] = useState(''); const [note, setNote] = useState(''); const [milestone, setMilestone] = useState(''); const [counted, setCounted] = useState(true);
 const [problem, setProblem] = useState<{ code: string; message: string } | null>(null);
 async function submit(confirm: boolean) {
  const result = await act('/planner/tasks/custom', { title: title.trim(), duration_minutes: minutes, week_start: week, date: date || null, start_time: time || null, note: note.trim() || null, milestone_key: milestone || null, count_hours: counted, confirm_outside_blocks: confirm });
  if (result.ok) close(); else setProblem(result);
 }
 const asking = !!problem && confirmable.includes(problem.code);
 return <form className="task-form task-add" aria-label={`Add a task to the week of ${longDate(week)}`} onSubmit={event => { event.preventDefault(); void submit(false); }}>
  <label className="task-add-title">Title<input autoFocus required maxLength={160} value={title} onChange={event => setTitle(event.target.value)} /></label>
  <label>Minutes<input type="number" required min={5} max={480} step={5} value={minutes} onChange={event => setMinutes(Math.round(Number(event.target.value)))} /></label>
  <label>Date (optional)<input type="date" value={date} onChange={event => { setDate(event.target.value); setProblem(null); }} /></label>
  <label>Time (optional)<input type="time" value={time} onChange={event => { setTime(event.target.value); setProblem(null); }} /></label>
  <label>Milestone (optional)<select value={milestone} onChange={event => setMilestone(event.target.value)}><option value="">No milestone</option>{milestones.map(item => <option key={item.key} value={item.key}>{item.title}</option>)}</select></label>
  <label className="task-add-title">Note (optional)<textarea maxLength={2000} value={note} onChange={event => setNote(event.target.value)} /></label>
  <label className="settings-check task-add-title"><input type="checkbox" checked={counted} onChange={event => setCounted(event.target.checked)} />Count in scheduled hours</label>
  <p className="small task-add-title">Without a date and time, it waits in Backlog for this week.</p>
  <div className="task-form-actions task-add-title">
   {asking
    ? <button type="button" className="btn" disabled={frozen} onClick={() => void submit(true)}>Place it there anyway</button>
    : <button className="btn" disabled={frozen || !title.trim() || !!date !== !!time}>Add task</button>}
   <button type="button" className="btn ghost" onClick={close}>Cancel</button>
  </div>
  {problem && <p className="task-problem task-add-title" role="alert">{problem.message}</p>}
 </form>;
}

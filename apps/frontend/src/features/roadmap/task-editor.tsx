"use client";
import { useState, type FormEvent } from 'react';
import type { PlanMilestone } from './types';
import './task-editor.css';

/** The editable part of a canonical task. Other fields stay on the server. */
export type EditableRoadmapTask = {
 id: string; title: string; instructions: string; completion_outcome: string;
 estimated_minutes: number; milestone_key: string | null; removed?: boolean;
 status: 'not_started' | 'in_progress' | 'completed';
 schedule: { date: string; start_time: string; duration_minutes: number }[];
};
type Fields = Pick<EditableRoadmapTask, 'title' | 'instructions' | 'completion_outcome' | 'estimated_minutes' | 'milestone_key'>;
type Draft = { original: Fields | null; taskId: string | null; fields: Fields };
type Change = (path: string, data: Record<string, unknown>) => Promise<boolean>;
const blank = (): Fields => ({ title: '', instructions: '', completion_outcome: '', estimated_minutes: 60, milestone_key: null });
const fieldsOf = (task: EditableRoadmapTask): Fields => ({ title: task.title, instructions: task.instructions, completion_outcome: task.completion_outcome, estimated_minutes: task.estimated_minutes, milestone_key: task.milestone_key });
const wordCount = (value: string) => value.trim() ? value.trim().split(/\s+/u).length : 0;
const fieldNames: (keyof Fields)[] = ['title', 'instructions', 'completion_outcome', 'estimated_minutes', 'milestone_key'];

export function TaskEditor({ tasks, milestones, frozen, change }: { tasks: EditableRoadmapTask[]; milestones: PlanMilestone[]; frozen: boolean; change: Change }) {
 const [draft, setDraft] = useState<Draft | null>(null);
 const [error, setError] = useState('');
 const current = draft?.taskId ? tasks.find(t => t.id === draft.taskId && !t.removed) : undefined;
 const edited = draft?.original ? fieldNames.filter(k => draft.fields[k] !== draft.original![k]) : [];
 // Conflicted when saved work changed or a field was changed in another session since this editor opened.
 const conflicted = !!draft?.taskId && (!current || edited.some(k => fieldsOf(current)[k] !== draft.original![k]));
 const titleChanged = !draft?.original || draft.fields.title !== draft.original.title;
 const words = draft ? wordCount(draft.fields.title) : 0;
 const titleInvalid = !!draft && titleChanged && (words < 1 || words > 11 || Array.from(draft.fields.title.trim()).length > 160);
 const update = (fields: Partial<Fields>) => { setDraft(d => d && ({ ...d, fields: { ...d.fields, ...fields } })); setError(''); };
 const edit = (task: EditableRoadmapTask) => { const original = fieldsOf(task); setDraft({ taskId: task.id, original, fields: { ...original } }); setError(''); };
 const submit = async (event: FormEvent) => {
  event.preventDefault(); if (!draft || frozen) return;
  const values = draft.fields;
  if (conflicted) { setError('This task changed while you were editing it. Copy your changes, then reopen it to use the latest version.'); return; }
  if (titleInvalid) { setError('Use 1–11 words and at most 160 characters for the title.'); return; }
  if (!values.instructions.trim() || !values.completion_outcome.trim() || Array.from(values.instructions.trim()).length > 4000 || Array.from(values.completion_outcome.trim()).length > 4000 || !Number.isInteger(values.estimated_minutes) || values.estimated_minutes < 1 || values.estimated_minutes > 60000) {
   setError('Add instructions, a completion outcome and an estimate between 1 and 60,000 minutes. Each description can contain at most 4,000 characters.'); return;
  }
  let path: string; let body: Record<string, unknown>;
  if (draft.taskId && draft.original) {
   const changes: Record<string, unknown> = {};
   for (const key of edited) changes[key] = values[key];
   if (!Object.keys(changes).length) { setDraft(null); return; }
   path = '/planner/tasks/edit'; body = { task_id: draft.taskId, changes };
  } else {
   path = '/planner/tasks/add'; body = { task: { ...values, requirement_refs: [], prerequisites: [], schedule: [] } };
  }
  if (await change(path, body)) { setDraft(null); setError(''); }
 };
 return <section className="review-card review-section task-editor" aria-labelledby="task-editor-heading">
  <h2 id="task-editor-heading">Edit tasks</h2>
  <p className="small">Add work or update an existing task. New tasks start unscheduled; existing timing and progress are kept.</p>
  {!draft && <button type="button" className="btn ghost" disabled={frozen} onClick={() => { setError(''); setDraft({ taskId: null, original: null, fields: blank() }); }}>Add task</button>}
  {!tasks.some(t => !t.removed) && <p>No tasks yet.</p>}
  <ul className="task-editor-list">{tasks.filter(t => !t.removed).map(task => <li key={task.id}>
   <div><strong>{task.title}</strong><span className="small">{task.schedule.length ? task.schedule.map(s => `${s.date} ${s.start_time}`).join(', ') : 'Unscheduled'} · {task.status.replaceAll('_', ' ')}</span></div>
   <button type="button" className="btn ghost" disabled={frozen || !!draft} aria-label={`Edit ${task.title}`} onClick={() => edit(task)}>Edit</button>
  </li>)}</ul>
  {draft && <form onSubmit={event => void submit(event)} noValidate>
   <h3>{draft.taskId ? 'Edit task' : 'Add task'}</h3>
   <label>Title <input value={draft.fields.title} onChange={e => update({ title: e.target.value })} aria-describedby="task-title-count" /></label>
   <p className="small" id="task-title-count" aria-live="polite">{words} of 11 words · {Array.from(draft.fields.title.trim()).length} of 160 characters{!titleChanged && words > 11 ? ' · saved title; shorten it only if you change it' : ''}</p>
   <label>Instructions <textarea value={draft.fields.instructions} onChange={e => update({ instructions: e.target.value })} /></label>
   <label>Completion outcome <textarea value={draft.fields.completion_outcome} onChange={e => update({ completion_outcome: e.target.value })} /></label>
   <label>Estimated minutes <input type="number" min="1" max="60000" step="1" value={draft.fields.estimated_minutes || ''} onChange={e => update({ estimated_minutes: Number(e.target.value) })} /></label>
   <label>Milestone <select value={draft.fields.milestone_key || ''} onChange={e => update({ milestone_key: e.target.value || null })}><option value="">No milestone</option>{milestones.map(m => <option key={m.key} value={m.key}>{m.title}</option>)}</select></label>
   {(error || conflicted) && <p role="alert">{error || 'This task changed while you were editing it. Copy your changes, then reopen it to use the latest version.'}</p>}
   <div className="task-editor-actions"><button className="btn" type="submit" disabled={frozen || conflicted}>Save task</button><button className="btn ghost" type="button" onClick={() => { setDraft(null); setError(''); }}>Cancel</button></div>
  </form>}
 </section>;
}

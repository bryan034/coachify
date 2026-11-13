"use client";
import { useId, useState, type KeyboardEvent } from 'react';
import { NotesEditor } from './notes-editor';
import { clashWith, nextFree, shortLength, timeRange, toClock, toMinutes } from './roadmap-day';
import type { NewSession, NotesDocument, PlannerConfig, Session, SessionChanges } from './types';

/** One layout for an opened task and a new one. Everything stays a draft until Save or Add task. */
export type TaskDraft = { title: string; doneWhen: string; skills: string[]; time: string | null; minutes: number; notes: NotesDocument; confidence: number | null; difficulty: number | null };
export type SkillOption = { name: string; group: string };
const DURATIONS = [15, 30, 45, 60, 90, 120, 150];
const emptyNotes = (): NotesDocument => ({ blocks: [] });

export const draftOf = (session: Session): TaskDraft => ({ title: session.title, doneWhen: session.completion_criterion, skills: session.skills.map(skill => skill.name), time: session.start_time, minutes: session.duration_minutes, notes: session.notes ?? emptyNotes(), confidence: session.confidence ?? null, difficulty: session.difficulty ?? null });
export const blankDraft = (time: string | null): TaskDraft => ({ title: '', doneWhen: '', skills: [], time, minutes: 30, notes: emptyNotes(), confidence: null, difficulty: null });
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export const isDirty = (draft: TaskDraft, base: TaskDraft) => !same(draft, base);

/** What changed, in the words the unsaved-changes dialog uses. */
export function changedParts(draft: TaskDraft, base: TaskDraft) {
 const parts: string[] = [];
 if (draft.title !== base.title) parts.push('the task name');
 if (draft.doneWhen !== base.doneWhen) parts.push('Done when');
 if (draft.time !== base.time || draft.minutes !== base.minutes) parts.push('the time');
 if (!same(draft.skills, base.skills)) parts.push('the skills');
 if (!same(draft.notes, base.notes)) parts.push('your notes');
 if (draft.confidence !== base.confidence || draft.difficulty !== base.difficulty) parts.push('your ratings');
 return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0] || 'this task';
}
/** Only the fields that differ are sent. Returning to elo's wording is sent as a restore. */
export function changesOf(draft: TaskDraft, base: TaskDraft, session: Session): SessionChanges {
 const changes: SessionChanges = {};
 const title = draft.title.trim(), doneWhen = draft.doneWhen.trim();
 const original = session.original;
 if (original && (title !== base.title || doneWhen !== base.doneWhen) && title === original.title && doneWhen === original.completion_criterion) changes.restore_original = true;
 else { if (title !== base.title) changes.title = title; if (doneWhen !== base.doneWhen && doneWhen) changes.completion_criterion = doneWhen; }
 if (!same(draft.skills, base.skills)) changes.skills = draft.skills;
 if (draft.time !== base.time) changes.start_time = draft.time;
 if (draft.minutes !== base.minutes) changes.duration_minutes = draft.minutes;
 if (!same(draft.notes, base.notes)) changes.notes = draft.notes;
 if (draft.confidence !== base.confidence) changes.confidence = draft.confidence;
 if (draft.difficulty !== base.difficulty) changes.difficulty = draft.difficulty;
 return changes;
}
export const newSessionOf = (draft: TaskDraft, date: string): NewSession => ({ title: draft.title.trim(), completion_criterion: draft.doneWhen.trim(), skills: draft.skills, date, start_time: draft.time, duration_minutes: draft.minutes, ...(draft.notes.blocks.length ? { notes: draft.notes } : {}) });

function SkillPicker({ id, value, catalog, onChange }: { id: string; value: string[]; catalog: SkillOption[]; onChange: (skills: string[]) => void }) {
 const [query, setQuery] = useState(''); const [open, setOpen] = useState(false); const [active, setActive] = useState(0);
 const needle = query.trim().toLowerCase();
 const options = catalog.filter(option => !value.some(name => name.toLowerCase() === option.name.toLowerCase()) && (!needle || option.name.toLowerCase().includes(needle))).slice(0, 8);
 const current = Math.min(active, Math.max(options.length - 1, 0));
 const shown = open && (options.length > 0 || !!needle);
 const add = (name: string) => { onChange([...value, name]); setQuery(''); setActive(0); setOpen(false); };
 function key(event: KeyboardEvent<HTMLInputElement>) {
  if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); if (shown && options[current]) add(options[current].name); }
  else if (event.key === 'ArrowDown') { event.preventDefault(); setActive(Math.min(current + 1, options.length - 1)); setOpen(true); }
  else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(Math.max(current - 1, 0)); }
  else if (event.key === 'Backspace' && !query && value.length) onChange(value.slice(0, -1));
  else if (event.key === 'Escape' && shown) { event.stopPropagation(); setOpen(false); }
 }
 return <div>
  <label htmlFor={id} className="rv-flab">Skills it works on</label>
  <div style={{ position: 'relative' }}>
   <div className="rv-skillbox">
    {value.map(name => <span className="rv-pick" key={name}>{name}<button type="button" aria-label={`Remove ${name}`} onClick={() => onChange(value.filter(item => item !== name))}>×</button></span>)}
    <input id={id} type="text" role="combobox" aria-expanded={shown} aria-controls={`${id}-list`} aria-autocomplete="list" autoComplete="off" placeholder={value.length ? 'Add another skill' : 'Search your skills'} value={query}
     onChange={event => { setQuery(event.target.value); setOpen(true); setActive(0); }} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={key} />
   </div>
   {shown && <ul id={`${id}-list`} role="listbox" aria-label="Your skills" className="rv-opts">
    {options.map((option, index) => <li key={option.name} role="option" aria-selected={index === current}><button type="button" tabIndex={-1} className={index === current ? 'act' : undefined} onMouseDown={event => { event.preventDefault(); add(option.name); }}>{option.name}<span>{option.group}</span></button></li>)}
    {!options.length && <li className="none">No skill in your profile matches “{query.trim()}”.</li>}
   </ul>}
  </div>
  <p className="rv-note" style={{ marginTop: 6, fontSize: 12 }}>Search your skills and press Return to add one.</p>
 </div>;
}

function Scale({ label, value, low, high, onChange }: { label: string; value: number | null; low: string; high: string; onChange: (value: number | null) => void }) {
 const id = useId();
 return <div role="radiogroup" aria-labelledby={id}>
  <div className="rv-row-between" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}><h4 id={id}>{label}</h4><strong style={{ fontSize: 13, whiteSpace: 'nowrap' }}>{value ? `${value} / 10` : 'Not rated'}</strong></div>
  <div className="rv-scale">{Array.from({ length: 10 }, (_, index) => index + 1).map(step => <button key={step} type="button" role="radio" aria-checked={value === step} aria-label={`${step} out of 10`} onClick={() => onChange(value === step ? null : step)}>{step}</button>)}</div>
  <div className="rv-ends"><span>1 · {low}</span><span>10 · {high}</span></div>
 </div>;
}

export function TaskForm({ mode, draft, base, session, date, where, others, config, nowMinute, catalog, disabled, problem, onChange, onSubmit, onCancel, onEscape }: {
 mode: 'edit' | 'new'; draft: TaskDraft; base: TaskDraft; session?: Session; date: string; where: string; others: Session[]; config: PlannerConfig; nowMinute: number | null;
 catalog: SkillOption[]; disabled: boolean; problem?: string; onChange: (patch: Partial<TaskDraft>) => void; onSubmit: (allowOverlap: boolean) => void; onCancel: () => void; onEscape: () => void;
}) {
 const id = useId();
 const free = nextFree(config, date, others, draft.minutes, nowMinute ?? 0);
 const [custom, setCustom] = useState(mode === 'edit' && !!draft.time);
 const clash = clashWith(others, draft.time, draft.minutes);
 const tooLate = !!draft.time && toMinutes(draft.time) + draft.minutes > 1440;
 const named = draft.title.trim().length > 0;
 const dirty = isDirty(draft, base);
 const durations = DURATIONS.includes(draft.minutes) ? DURATIONS : [...DURATIONS, draft.minutes].sort((a, b) => a - b);
 const original = session?.original ?? null;
 const reworded = mode === 'edit' && session?.origin === 'generated' && !!original && (draft.title !== original.title || draft.doneWhen !== original.completion_criterion);
 const ready = named && !tooLate && !disabled && (mode === 'new' || dirty);
 const status = mode === 'new' ? (named ? 'Ready to add' : 'Give the task a name to add it') : !named ? 'The task needs a name' : dirty ? 'Unsaved changes' : 'No changes yet';
 const summary = `${draft.time ? `${draft.time}–${toClock(toMinutes(draft.time) + draft.minutes)}` : 'Anytime'} ${where} · ${shortLength(draft.minutes)} · ${draft.skills.length ? draft.skills.join(', ') : 'No specific skill'}`;
 const submit = () => { if (ready) onSubmit(!!clash); };
 return <div className={`rv-det${mode === 'new' ? ' new' : ''}`} role="group" aria-label={mode === 'new' ? 'New task' : 'Edit task'} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onEscape(); } }}>
  {mode === 'new' && <h3>New task <span className="rv-soft" style={{ fontWeight: 400, fontSize: 13, color: 'var(--slate)' }}>for {where.replace(/^on /, '')}</span></h3>}
  <div><label htmlFor={`${id}-title`} className="rv-flab">Task</label><input id={`${id}-title`} type="text" className="rv-input" maxLength={160} autoFocus={mode === 'new'} placeholder="What will you do?" value={draft.title} onChange={event => onChange({ title: event.target.value })} onKeyDown={event => { if (event.key === 'Enter' && mode === 'new') { event.preventDefault(); submit(); } }} /></div>
  <div><label htmlFor={`${id}-done`} className="rv-flab">Done when</label><textarea id={`${id}-done`} className="rv-input" maxLength={4000} placeholder="How you’ll know it’s finished, e.g. the tests pass" value={draft.doneWhen} onChange={event => onChange({ doneWhen: event.target.value })} />
   {reworded && <p className="rv-note" style={{ marginTop: 4, fontSize: 12 }}>You’ve changed elo’s wording for this task. <button type="button" className="rv-link" style={{ fontSize: 12 }} onClick={() => onChange({ title: original!.title, doneWhen: original!.completion_criterion })}>Restore elo’s version</button></p>}</div>
  <SkillPicker id={`${id}-skill`} value={draft.skills} catalog={catalog} onChange={skills => onChange({ skills })} />
  <div><span className="rv-flab" id={`${id}-when`}>When</span>
   <div className="rv-chips" role="group" aria-labelledby={`${id}-when`}>
    <button type="button" className="rv-opt" aria-pressed={!custom && draft.time === null} onClick={() => { setCustom(false); onChange({ time: null }); }}>Anytime</button>
    {free && <button type="button" className="rv-opt" aria-pressed={!custom && draft.time === free} onClick={() => { setCustom(false); onChange({ time: free }); }}>Next free · {free}</button>}
    <label className={`rv-opt${custom ? ' on' : ''}`}>Pick a time <input type="time" step={300} aria-label="Start time" value={custom ? draft.time ?? '' : ''} onChange={event => { setCustom(!!event.target.value); onChange({ time: event.target.value || null }); }} /></label>
   </div>
   <span className="rv-flab" id={`${id}-dur`} style={{ marginTop: 12 }}>Duration</span>
   <div className="rv-chips" role="group" aria-labelledby={`${id}-dur`}>{durations.map(value => <button key={value} type="button" className="rv-opt" aria-pressed={draft.minutes === value} onClick={() => onChange({ minutes: value })}>{shortLength(value)}</button>)}</div>
   <p className="rv-note" style={{ marginTop: 8, color: 'var(--ink)' }}>{summary}</p>
   {clash && !tooLate && <p className="rv-clash">Overlaps “{clash.title}” ({timeRange(clash)}). You can still keep it.</p>}
   {tooLate && <p className="rv-clash" role="alert">A task must end by midnight. Choose an earlier start or a shorter duration.</p>}
  </div>
  <div><span className="rv-flab">Your notes</span><NotesEditor label={mode === 'new' ? 'Notes for the new task' : `Notes for ${base.title}`} value={base.notes} disabled={disabled} onDraft={notes => onChange({ notes })} /></div>
  {mode === 'edit' && <>
   <Scale label="How confident are you that you could do this again on your own?" value={draft.confidence} low="Not yet" high="Completely" onChange={confidence => onChange({ confidence })} />
   <Scale label="How difficult was it?" value={draft.difficulty} low="Very easy" high="Very hard" onChange={difficulty => onChange({ difficulty })} />
   <p className="rv-note" style={{ fontSize: 12 }}>Your ratings and notes are for you. They don’t change your assessed skills.</p>
  </>}
  {problem && <p role="alert" className="rv-clash">{problem}</p>}
  <div className="rv-det-foot"><span role="status">{status}</span><button className="rv-btn sm" type="button" onClick={onCancel}>Cancel</button><button className="rv-btn sm pri" type="button" disabled={!ready} onClick={submit}>{mode === 'new' ? 'Add task' : 'Save'}</button></div>
 </div>;
}

export function UnsavedDialog({ text, canSave, save, discard, keep }: { text: string; canSave: boolean; save: () => void; discard: () => void; keep: () => void }) {
 const id = useId();
 return <div className="rv-dialog-veil" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); keep(); } }}>
  <div className="rv-dialog" role="alertdialog" aria-modal="true" aria-labelledby={`${id}-h`} aria-describedby={`${id}-p`}>
   <h2 id={`${id}-h`}>Save your changes?</h2>
   <p id={`${id}-p`}>{text}</p>
   <div className="rv-dialog-actions"><button className="rv-btn sm" type="button" onClick={keep}>Keep editing</button><button className="rv-btn sm danger" type="button" onClick={discard}>Discard changes</button><button className="rv-btn sm pri" type="button" autoFocus disabled={!canSave} onClick={save}>Save changes</button></div>
  </div>
 </div>;
}

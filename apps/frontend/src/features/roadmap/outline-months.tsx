"use client";
import { useEffect, useState } from 'react';
import type { Outline, Planner, RoutineRule } from './types';

type Change = (path: string, data: Record<string, unknown>, method?: 'PATCH') => Promise<boolean>;
const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
function currentMonth(timeZone: string) {
 const parts = new Intl.DateTimeFormat('en', { timeZone, year: 'numeric', month: '2-digit' }).formatToParts(new Date());
 return `${parts.find(p => p.type === 'year')?.value}-${parts.find(p => p.type === 'month')?.value}`;
}
function lastDate(exclusive: string) {
 const date = new Date(`${exclusive}T00:00:00Z`); date.setUTCDate(date.getUTCDate() - 1);
 return date.toISOString().slice(0, 10);
}

function draftOf(outline: Outline) {
 return { summary: outline.summary, gaps: outline.gaps, milestones: outline.milestones.map(({ id: _id, outcome: _outcome, checkpoints, ...m }) => ({ ...m, ...(checkpoints ? { checkpoints: checkpoints.map(({ reached_at: _reachedAt, ...checkpoint }) => checkpoint) } : {}) })), routine_rules: outline.routine_rules, deadline_outcome: outline.deadline_outcome, beyond_deadline: outline.beyond_deadline, exclusions: outline.exclusions };
}

export function OutlineMonths({ planner, frozen, change, revise, settings }: { planner: Planner; frozen: boolean; change: Change; revise: () => void; settings: () => void }) {
 const outline = planner.outline_candidate || planner.outline_active;
 const preview = !!planner.outline_candidate;
 const [draft, setDraft] = useState(() => outline ? draftOf(outline) : null);
 const [editing, setEditing] = useState(false);
 const [month, setMonth] = useState(() => {
  const start = (planner.runway.resolved.start_date || '').slice(0, 7);
  const current = currentMonth(planner.config.time_zone);
  return start > current ? start : current;
 });
 useEffect(() => { setDraft(outline ? draftOf(outline) : null); setEditing(false); }, [outline?.id]); // eslint-disable-line react-hooks/exhaustive-deps
 if (!outline || !draft) return null;
 const updateRule = (index: number, changes: Partial<RoutineRule>) => setDraft({ ...draft, routine_rules: draft.routine_rules.map((r, i) => i === index ? { ...r, ...changes } : r) });
 const save = async () => { if (await change(`/planner/outlines/${outline.id}`, { outline: draft }, 'PATCH')) setEditing(false); };
 const addRule = () => {
  const first = draft.milestones[0]; if (!first) return;
  setDraft({ ...draft, routine_rules: [...draft.routine_rules, { id: crypto.randomUUID(), revision: 1, milestone_key: first.key, activity: '', weekdays: [0, 1, 2, 3, 4], duration_minutes: 30, topic_progression: [], difficulty: '', start_date: first.projected_start, end_date: first.projected_end, user_wording: '' }] });
 };
 return <div className="review-card review-section">
  <h2>{preview ? 'Review your milestone outline' : 'Your milestone outline'}</h2>
  <p>{outline.summary}</p><p className="small">Review the outcomes and routines before generating tasks. Accepted work stays saved when the outline changes.</p>
  {!!draft.gaps.length && <fieldset disabled={!editing || frozen}><legend>Priorities</legend>{draft.gaps.map((gap, i) => <label key={gap.id}>{gap.name} priority <input type="number" min="1" max="100" value={gap.priority} onChange={e => setDraft({ ...draft, gaps: draft.gaps.map((item, n) => n === i ? { ...item, priority: Number(e.target.value) } : item) })} /></label>)}</fieldset>}
  {draft.milestones.map((m, i) => <fieldset key={m.key} disabled={!editing || frozen}><legend>Milestone {i + 1}</legend>
   <label>Title <input value={m.title} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, title: e.target.value } : item) })} /></label>
   <label>Outcome <textarea value={m.demonstrable_outcome} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, demonstrable_outcome: e.target.value } : item) })} /></label>
   <label>Start <input type="date" value={m.projected_start} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, projected_start: e.target.value } : item) })} /></label>
   <label>Finish <input type="date" value={m.projected_end} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, projected_end: e.target.value } : item) })} /></label>
   <label>Estimated minutes <input type="number" min="0" value={m.estimated_minutes} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, estimated_minutes: Number(e.target.value) } : item) })} /></label>
  </fieldset>)}
  <h3>Routines</h3>{!draft.routine_rules.length && <p>No routines added.</p>}
  {draft.routine_rules.map((r, i) => <fieldset key={r.id} disabled={!editing || frozen}><legend>Routine {i + 1}</legend>
   <label>Activity <input value={r.activity} onChange={e => updateRule(i, { activity: e.target.value })} /></label>
   <label>Milestone <select value={r.milestone_key} onChange={e => updateRule(i, { milestone_key: e.target.value })}>{draft.milestones.map(m => <option value={m.key} key={m.key}>{m.title}</option>)}</select></label>
   <label>Minutes per session <input type="number" min="1" max="480" value={r.duration_minutes} onChange={e => updateRule(i, { duration_minutes: Number(e.target.value) })} /></label>
   <label>Difficulty <input value={r.difficulty} onChange={e => updateRule(i, { difficulty: e.target.value })} /></label>
   <label>Topics, separated by commas <input value={r.topic_progression.join(',')} onChange={e => updateRule(i, { topic_progression: e.target.value ? e.target.value.split(',') : [] })} /></label>
   <label>Start <input type="date" value={r.start_date} onChange={e => updateRule(i, { start_date: e.target.value })} /></label><label>End <input type="date" value={r.end_date} onChange={e => updateRule(i, { end_date: e.target.value })} /></label>
   <div>{days.map((day, n) => <label key={day}><input type="checkbox" checked={r.weekdays.includes(n)} onChange={e => updateRule(i, { weekdays: e.target.checked ? [...r.weekdays, n].sort() : r.weekdays.filter(d => d !== n) })} />{day}</label>)}</div>
   {editing && <button type="button" onClick={() => setDraft({ ...draft, routine_rules: draft.routine_rules.filter((_, n) => n !== i) })}>Remove routine</button>}
  </fieldset>)}
  {editing ? <div><button className="btn ghost" disabled={frozen} onClick={addRule}>Add routine</button><button className="btn" disabled={frozen} onClick={() => void save()}>Save outline changes</button><button className="btn ghost" onClick={() => { setDraft(draftOf(outline)); setEditing(false); }}>Cancel</button></div> : <button className="btn ghost" disabled={frozen} onClick={() => setEditing(true)}>Edit outline</button>}
  {preview && !editing && <button className="btn" disabled={frozen} onClick={() => void change(`/planner/outlines/${outline.id}/accept`, {})}>Accept outline</button>}
  {!preview && !editing && <><button className="btn ghost" disabled={frozen} onClick={revise}>Generate revised outline</button><button className="btn ghost" disabled={frozen} onClick={settings}>Change planning settings</button><section><h3>Plan a month</h3><label>Month <input type="month" value={month} onChange={e => setMonth(e.target.value)} /></label><button className="btn" disabled={frozen || !month || !!planner.month_candidate} onClick={() => void change('/planner/months/generate', { month })}>Generate month preview</button>
   {(planner.month_blocks || []).map(b => <div key={b.id}><p>{b.month} accepted{b.needs_review ? ' · outline changed; review needed' : ''}</p><button className="btn ghost" disabled={frozen || !!planner.month_candidate || b.month < currentMonth(planner.config.time_zone)} onClick={() => void change('/planner/months/generate', { month: b.month, revision: true })}>Revise {b.month}</button></div>)}
   {planner.month_candidate && <div><h4>Preview for {planner.month_candidate.month}</h4><p>Dates {planner.month_candidate.start_date}–{lastDate(planner.month_candidate.end_exclusive)}, {planner.month_candidate.time_zone}.</p>{planner.month_candidate.replaces_block_id && <p>This revision replaces {planner.month_candidate.replaced_task_ids?.length || 0} untouched future tasks. Completed, started, edited, removed and note-bearing work remains saved.</p>}<ul>{planner.month_candidate.tasks.map(t => <li key={t.id}><strong>{t.title}</strong> · {t.schedule.map(s => `${s.date} ${s.start_time} (${s.duration_minutes} min)`).join(', ')}<p>{t.instructions}</p><p>Complete when: {t.completion_outcome}</p></li>)}</ul><button className="btn" disabled={frozen} onClick={() => void change(`/planner/months/${planner.month_candidate!.id}/accept`, {})}>Accept month</button><button className="btn ghost" disabled={frozen} onClick={() => void change(`/planner/months/${planner.month_candidate!.id}/discard`, {})}>Discard preview</button></div>}
  </section></>}
 </div>;
}

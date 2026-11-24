"use client";
import { useState } from 'react';
import type { Outline, RoutineRule } from './types';
const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
function draftOf(outline: Outline) {
 return { weeks: (outline.weeks || []).map(({week_start,objective,expected_outcome,estimated_minutes,milestone_key,gap_ids})=>({week_start,objective,expected_outcome,estimated_minutes,milestone_key,gap_ids})), summary: outline.summary, gaps: outline.gaps, milestones: outline.milestones.map(({ id: _id, outcome: _outcome, checkpoints, ...m }) => ({ ...m, ...(checkpoints ? { checkpoints: checkpoints.map(({ reached_at: _reachedAt, ...checkpoint }) => checkpoint) } : {}) })), routine_rules: outline.routine_rules, deadline_outcome: outline.deadline_outcome, beyond_deadline: outline.beyond_deadline, exclusions: outline.exclusions };
}

export function OutlineEditor({outline,frozen,change,finishEditing}: {outline: Outline; frozen: boolean; finishEditing:()=>void; change: (path:string,data:Record<string,unknown>,method?:'PATCH')=>Promise<boolean>}) {
 const [draft,setDraft]=useState(()=>draftOf(outline));
 const updateRule=(index:number,patch:Partial<RoutineRule>)=>setDraft({...draft,routine_rules:draft.routine_rules.map((r,i)=>i===index?{...r,...patch}:r)});
 const addRule=()=>{const first=draft.milestones[0];if(first)setDraft({...draft,routine_rules:[...draft.routine_rules,{id:crypto.randomUUID(),revision:1,milestone_key:first.key,activity:'',weekdays:[0],duration_minutes:30,topic_progression:[],difficulty:'',start_date:first.projected_start,end_date:first.projected_end,user_wording:''}]});};
 const save=async()=>{if(await change(`/planner/outlines/${outline.id}`,{outline:draft},'PATCH'))finishEditing();};
 return <div className="outline-editor"><p className="small">Saving changes keeps your accepted work and clears the first-week preview. Plan it again after accepting the outline.</p>
  {draft.milestones.map((m, i) => <fieldset key={m.key} disabled={frozen}><legend>Milestone {i + 1}</legend>
   <label>Title <input value={m.title} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, title: e.target.value } : item) })} /></label>
   <label>Outcome <textarea value={m.demonstrable_outcome} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, demonstrable_outcome: e.target.value } : item) })} /></label>
   <label>Start <input type="date" value={m.projected_start} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, projected_start: e.target.value } : item) })} /></label>
   <label>Finish <input type="date" value={m.projected_end} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, projected_end: e.target.value } : item) })} /></label>
   <label>Estimated hours <input type="number" min="0" step="0.25" value={m.estimated_minutes / 60} onChange={e => setDraft({ ...draft, milestones: draft.milestones.map((item, n) => n === i ? { ...item, estimated_minutes: Math.round(Number(e.target.value) * 60) } : item) })} /></label>
  </fieldset>)}
  <h3>Weekly objectives</h3>{draft.weeks.map((week,i)=><fieldset key={week.week_start} disabled={frozen}><legend>Week of {week.week_start}</legend><label>Objective<input value={week.objective} onChange={e=>setDraft({...draft,weeks:draft.weeks.map((w,n)=>n===i?{...w,objective:e.target.value}:w)})}/></label><label>Expected outcome<textarea value={week.expected_outcome} onChange={e=>setDraft({...draft,weeks:draft.weeks.map((w,n)=>n===i?{...w,expected_outcome:e.target.value}:w)})}/></label><label>Estimated hours<input type="number" min="0" step="0.25" value={week.estimated_minutes/60} onChange={e=>setDraft({...draft,weeks:draft.weeks.map((w,n)=>n===i?{...w,estimated_minutes:Math.round(Number(e.target.value)*60)}:w)})}/></label></fieldset>)}
  <h3>Routines</h3>{!draft.routine_rules.length && <p>No routines added.</p>}
  {draft.routine_rules.map((r, i) => <fieldset key={r.id} disabled={frozen}><legend>Routine {i + 1}</legend>
   <label>Activity <input value={r.activity} onChange={e => updateRule(i, { activity: e.target.value })} /></label>
   <label>Milestone <select value={r.milestone_key} onChange={e => updateRule(i, { milestone_key: e.target.value })}>{draft.milestones.map(m => <option value={m.key} key={m.key}>{m.title}</option>)}</select></label>
   <label>Minutes per session <input type="number" min="1" max="480" value={r.duration_minutes} onChange={e => updateRule(i, { duration_minutes: Number(e.target.value) })} /></label>
   <label>Difficulty <input value={r.difficulty} onChange={e => updateRule(i, { difficulty: e.target.value })} /></label>
   <label>Topics, separated by commas <input value={r.topic_progression.join(',')} onChange={e => updateRule(i, { topic_progression: e.target.value ? e.target.value.split(',') : [] })} /></label>
   <label>Start <input type="date" value={r.start_date} onChange={e => updateRule(i, { start_date: e.target.value })} /></label><label>End <input type="date" value={r.end_date} onChange={e => updateRule(i, { end_date: e.target.value })} /></label>
   <div>{days.map((day, n) => <label key={day}><input type="checkbox" checked={r.weekdays.includes(n)} onChange={e => updateRule(i, { weekdays: e.target.checked ? [...r.weekdays, n].sort() : r.weekdays.filter(d => d !== n) })} />{day}</label>)}</div>
   <button type="button" onClick={() => setDraft({ ...draft, routine_rules: draft.routine_rules.filter((_, n) => n !== i) })}>Remove routine</button>
  </fieldset>)}
  <div><button className="btn ghost" disabled={frozen} onClick={addRule}>Add routine</button><button className="btn" disabled={frozen} onClick={() => void save()}>Save outline changes</button><button className="btn ghost" onClick={finishEditing}>Cancel</button></div>
</div>;
}

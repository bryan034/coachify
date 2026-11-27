"use client";
import { OutlineEditor } from './outline-editor';
import { useState } from 'react';
import type { Outline, Planner, WeeklyObjective } from './types';
import { hours, longDate } from './settings-panel';
import { TaskGuide } from './task-form';
import { openPremium } from '@/lib/api/premium';
type Change = (path: string, data: Record<string, unknown>, method?: 'PATCH') => Promise<boolean>;
export function PartialOutlineNotice({outline}: {outline?: Outline | null}) {
 const review=outline?.partial_review;
 if (!review) return null;
 return <section className="roadmap-notice" role="status" aria-label="Partial roadmap"><h3>Partial roadmap</h3><p>Two generation attempts included invalid assessment references. The affected items were omitted; Some parts of your goal are not included in this roadmap.</p><details><summary>What was omitted ({review.omitted_items.length})</summary><ul>{review.omitted_items.map((item,i)=><li key={`${item.kind}:${item.id}:${i}`}><strong>{item.title}</strong><p>{item.reason}</p></li>)}</ul></details>{review.uncovered_requirements.length>0 && <p>{review.uncovered_requirements.length} assessment {review.uncovered_requirements.length===1?'priority is':'priorities are'} not covered. This plan covers only part of your goal.</p>}</section>;
}
const FREE_DETAIL_WEEKS = 2;
export function detailLocked(planner: Planner, premium: boolean, weekStart: string) {
 return !premium && !(planner.outline_active?.weeks || []).map(week => week.week_start).sort().slice(0, FREE_DETAIL_WEEKS).includes(weekStart);
}
export function LockedWeek({ weekStart, objective }: { weekStart: string; objective?: WeeklyObjective }) {
 return <div className="locked-week" role="group" aria-label={`Task breakdown for the week of ${longDate(weekStart)}`}>
  {objective && <p><strong>Week goal:</strong> {objective.objective}</p>}
  <p className="small">The task breakdown for this week is part of elo Premium. You can still add your own tasks to it.</p>
  <button type="button" className="btn ghost" onClick={() => openPremium('roadmap')}>Unlock task breakdown</button>
 </div>;
}
export function WeeklyPlanning({ planner, frozen, change, settings, acceptBlocked, premium = false }: {planner: Planner; frozen: boolean; change: Change; settings: () => void; acceptBlocked?: boolean; premium?: boolean}) {
 const [editingOutlineId, setEditingOutlineId] = useState<string | null>(null);
 const [workload, setWorkload] = useState(''); const [difficulty, setDifficulty] = useState(''); const [note, setNote] = useState('');
 const outline = planner.outline_candidate; const week = planner.week_candidate; const next = planner.week_planning;
 const outlineEditing = !!outline && editingOutlineId === outline.id;
 if (outline || week) return <section className="review-card review-section weekly-review" aria-label="Review roadmap preview">
  <PartialOutlineNotice outline={outline || planner.outline_active}/><h2>{outline ? 'Review your roadmap' : 'Review your week'}</h2><p>{outline?.summary || week?.summary}</p>
  {outline && <><p>{outline.deadline_outcome.summary}</p>{outline.beyond_deadline.length > 0 && <details className="weekly-task"><summary>Beyond this roadmap</summary><ul>{outline.beyond_deadline.map(item => <li key={item.title}>{item.title} · {hours(item.estimated_minutes)}<p>{item.reason}</p></li>)}</ul><p className="small">Adjust scope, study time or the deadline if you want to include this work.</p></details>}{outlineEditing ? <OutlineEditor key={outline.id} outline={outline} frozen={frozen} change={change} finishEditing={() => setEditingOutlineId(null)}/> : <button className="btn ghost" disabled={frozen} onClick={() => setEditingOutlineId(outline.id)}>Edit outline</button>}{outline.first_week_error && <p role="alert">{outline.first_week_error}</p>}</>}
  {week && <><h3>Scheduled tasks from {longDate(week.start_date)}</h3>{outline && <p>{week.summary}</p>}<p className="small">{hours(week.tasks.reduce((total, task) => total + task.schedule.reduce((n, slot) => n + slot.duration_minutes, 0), 0) + week.carryover.reduce((total, entry) => total + entry.schedule.reduce((n, slot) => n + slot.duration_minutes, 0), 0))} scheduled of your {hours(week.target.weekly_minutes)} weekly target. Times use {planner.config.time_zone}.</p>{week.target.reasons.map(reason => <p key={reason.code} className="roadmap-notice">{reason.message}</p>)}
   {week.tasks.map(task => <details key={task.id} className="weekly-task"><summary>{task.title}{task.label && <span className="rv-tag">{task.label}</span>}</summary><p className="weekly-instructions">{task.instructions}</p><TaskGuide description={task.description} materials={task.materials} /><p><strong>Done when:</strong> {task.completion_outcome}</p><ul>{task.schedule.map((slot, i) => <li key={i}>{longDate(slot.date)} at {slot.start_time} · {hours(slot.duration_minutes)}</li>)}</ul></details>)}
   {!!week.carryover.length && <><h3>Unfinished work</h3>{week.carryover.map(item => <div key={item.task_id} className="weekly-task"><strong>{item.title}</strong><p>{item.reason}</p>{item.action === 'split' && <p className="small">{item.minutes} minutes this week. The remaining work stays in your backlog as a linked task.</p>}<label>What happens next <select disabled={frozen} value={item.action} onChange={e => void change(`/planner/weeks/${week.id}/carryover`, {decisions: [{task_id: item.task_id, action: e.target.value}]})}><option value="carry">Carry forward</option>{item.minutes && <option value="split">Split across weeks</option>}<option value="defer">Defer to backlog</option><option value="drop">Drop from plan</option></select></label>{item.schedule.map((slot,i) => <p key={i} className="small">{longDate(slot.date)} at {slot.start_time} · {hours(slot.duration_minutes)}</p>)}</div>)}</>}
   {!!week.objective_changes.length && <><h3>Proposed changes to future weeks</h3>{week.objective_changes.map(item => <div key={item.week_start} className="weekly-task"><p>{longDate(item.week_start)}</p><p>Previously: {item.previous?.objective}</p><p>Proposed: {item.objective}</p><p>{item.expected_outcome}</p><p className="small">{item.reason}</p></div>)}</>}
   {!!week.unplaced?.length && <p role="alert">Some tasks no longer fit. Defer unfinished work or generate a fresh preview before accepting.</p>}
  </>}
  {acceptBlocked && <p role="status">Your goal, evidence or evaluation changed. Update the evaluation and generate a fresh preview before accepting.</p>}
  <p className="small">Your accepted work changes only when you accept this preview. Completion records your progress; it does not establish skill mastery.</p>
  <div className="plan-actions"><button className="btn primary" disabled={frozen || outlineEditing || acceptBlocked || !!week?.unplaced?.length} onClick={() => void change(outline ? `/planner/outlines/${outline.id}/accept` : `/planner/weeks/${week!.id}/accept`, {})}>{outline ? week ? 'Accept roadmap and first week' : 'Accept weekly outline' : 'Accept week'}</button><button className="btn ghost" disabled={frozen} onClick={() => void change(outline ? `/planner/outlines/${outline.id}/discard` : `/planner/weeks/${week!.id}/discard`, {})}>Discard preview</button><button className="btn ghost" disabled={frozen} onClick={settings}>Plan settings</button></div>
 </section>;
 const revisions = (planner.week_blocks || []).filter(b => b.week_start > planner.runway.resolved.today);
 if (!next?.action && !revisions.length) return null;
 return <section className="weekly-continuation review-card" aria-label="Weekly planning"><h2>{next?.action === 'plan_this' ? 'Plan this week' : 'Plan next week'}</h2>
  <p>Use this week's progress and your feedback to curate the next plan. Review the schedule and unfinished work before accepting.</p>
  {next?.notice && <p role="status">{next.notice}</p>}
  {!next ? null : next.week_start && detailLocked(planner, premium, next.week_start) ? <LockedWeek weekStart={next.week_start} objective={planner.outline_active?.weeks?.find(week => week.week_start === next.week_start)}/> : !next.available ? <p className="small">Available on {longDate(next.plan_day)}, or when all this week's tasks are complete.</p> : <><p className="small">{next.unfinished_count} unfinished tasks to review. No progress yet? You can still plan a lighter week and review what to carry.</p><div className="weekly-feedback"><label>Workload <select value={workload} onChange={e => setWorkload(e.target.value)}><option value="">Optional</option><option value="too_much">Too much</option><option value="about_right">About right</option><option value="too_light">Too light</option></select></label><label>Difficulty <select value={difficulty} onChange={e => setDifficulty(e.target.value)}><option value="">Optional</option><option value="too_hard">Too hard</option><option value="about_right">About right</option><option value="too_easy">Too easy</option></select></label><label>Anything to adjust? <textarea maxLength={500} value={note} onChange={e => setNote(e.target.value)}/></label></div><button className="btn primary" disabled={frozen} onClick={() => void change('/planner/weeks/generate', {week_start: next.week_start, feedback: {workload: workload || null, difficulty: difficulty || null, note}})}>{next?.action === 'plan_this' ? 'Plan this week' : 'Plan next week'}</button></>}
  {revisions.map(block => <div key={block.id} className="plan-actions"><button className="btn ghost" disabled={frozen} onClick={() => detailLocked(planner, premium, block.week_start) ? openPremium('roadmap') : void change('/planner/weeks/generate', {week_start:block.week_start,revision:true})}>Review revised week of {longDate(block.week_start)}</button></div>)}
  {!!planner.week_blocks?.some(b => b.needs_review) && <p className="small">Your outline changed. Review affected accepted weeks before replacing future tasks.</p>}
 </section>;
}

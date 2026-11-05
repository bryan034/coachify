"use client";
import { useState } from 'react';
import { hours, longDate } from './settings-panel';
import type { LegacyRoadmap, PlanMilestone, PlanReview, PlannedRoadmap } from './types';

type AnyRoadmap = PlannedRoadmap | LegacyRoadmap;

const day = (value: string) => new Date(`${value}T12:00:00Z`).getTime();
const shortDate = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', timeZone: 'UTC' });

function dateScale(plan: AnyRoadmap) {
 const target = plan.config.target_date!;
 const milestones = [...plan.milestones].sort((a, b) => a.projected_end.localeCompare(b.projected_end));
 const start = [plan.config.start_date!, ...milestones.map(m => m.projected_start)].sort()[0];
 const span = Math.max(day(target) - day(start), 86400000);
 return { start, target, milestones, position: (value: string) => Math.min(100, Math.max(0, (day(value) - day(start)) / span * 100)) };
}

/** Height of the route at a point in time: the rising line of the Elo mark, as an S-curve. */
const rise = (x: number) => 86 - 72 * (1 - Math.cos(Math.PI * x / 100)) / 2;
const trace = (from: number, to: number) => {
 const points = [];
 for (let x = from; x < to; x += 2) points.push(`${x} ${rise(x).toFixed(2)}`);
 return `M${[...points, `${to} ${rise(to).toFixed(2)}`].join('L')}`;
};

/** The plan drawn as a route. Decorative for assistive technology: the milestone list carries the same facts. */
export function RouteMap({ plan, review }: { plan: AnyRoadmap; review: PlanReview }) {
 const { start, target, milestones, position } = dateScale(plan);
 const today = position(review.remaining.resolved.today);
 const count = milestones.length;
 const gap = Math.min(5, 88 / Math.max(count, 1));
 let cursor = 0;
 const stops = milestones.map((milestone, index) => {
  cursor = Math.min(94 - gap * (count - 1 - index), Math.max(position(milestone.projected_end), cursor + gap));
  return { milestone, x: cursor };
 });
 return <div className="route-map" aria-hidden="true">
  <svg viewBox="0 0 100 100" preserveAspectRatio="none">
   {today > 0 && <path className="route-walked" vectorEffect="non-scaling-stroke" d={trace(0, today)} />}
   {today < 100 && <path className="route-ahead" vectorEffect="non-scaling-stroke" d={trace(today, 100)} />}
  </svg>
  <i className="route-dot route-start" style={{ left: '0%', top: `${rise(0)}%` }} />
  <span className="route-label route-label-start">{shortDate(start)}</span>
  {today > 6 && today < 90 && <span className="route-today" style={{ left: `${today}%`, top: `${rise(today)}%` }}>Today</span>}
  {stops.map(({ milestone, x }, index) => <i key={milestone.id} className={`route-dot route-stop${milestone.outcome.demonstrated || milestone.completion ? ' reached' : ''}`} style={{ left: `${x}%`, top: `${rise(x)}%` }} title={`${milestone.title}: projected to finish ${longDate(milestone.projected_end)}`}>{index + 1}</i>)}
  <i className="route-dot route-end" style={{ left: '100%', top: `${rise(100)}%` }} />
  <span className="route-label route-label-end"><strong>{plan.assessment.role}</strong>{shortDate(target)}</span>
 </div>;
}

function OutcomeForm({ milestone, frozen, record }: { milestone: PlanMilestone; frozen: boolean; record: (demonstrated: boolean, note: string) => void }) {
 const [open, setOpen] = useState(false); const [note, setNote] = useState('');
 if (milestone.outcome.demonstrated) return <p className="timeline-outcome">Outcome recorded by you: {milestone.outcome.note}. <button type="button" className="settings-link" disabled={frozen} onClick={() => record(false, '')}>Remove</button></p>;
 if (!open) return <p className="timeline-outcome">Outcome not yet demonstrated. <button type="button" className="settings-link" disabled={frozen} onClick={() => setOpen(true)}>Record how you demonstrated it</button></p>;
 return <form className="timeline-form" onSubmit={e => { e.preventDefault(); record(true, note.trim()); }}><label>How did you demonstrate “{milestone.demonstrable_outcome}”?<textarea required maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label><div className="plan-actions"><button className="btn" disabled={frozen || !note.trim()}>Save outcome</button><button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button></div></form>;
}

export function MilestoneTimeline({ plan, review, frozen, recordOutcome, milestoneActions }: { plan: AnyRoadmap; review: PlanReview; frozen: boolean; recordOutcome: ((milestone: PlanMilestone, demonstrated: boolean, note: string) => void) | null; milestoneActions?: (milestone: PlanMilestone) => React.ReactNode }) {
 const { target, milestones, position } = dateScale(plan);
 return <section className="milestone-timeline" aria-labelledby="timeline-title">
  <div className="timeline-heading"><h3 id="timeline-title">Milestone timeline</h3><p className="timeline-target">Target date: <strong>{longDate(target)}</strong></p></div>
  <p className="timeline-legend"><span><i className="timeline-swatch completed" aria-hidden="true" />Completed sessions</span><span><i className="timeline-swatch projected" aria-hidden="true" />Projected</span></p>
  {!milestones.length && <p className="small">No milestones are needed for this plan.</p>}
  <ol>{milestones.map(milestone => {
   const progress = review.milestones[milestone.id] || { sessions_total: 0, sessions_completed: 0, completed_minutes: 0 };
   const left = position(milestone.projected_start); const width = Math.max(position(milestone.projected_end) - left, 1.5);
   const done = progress.completed_minutes;
   // A roadmap-v3 estimate is the milestone's whole effort; a roadmap-v2 estimate was what remained.
   const remaining = plan.schema_version === 'roadmap-v3' ? Math.max(0, milestone.estimated_minutes - done) : milestone.estimated_minutes;
   const share = done + remaining ? done / (done + remaining) * 100 : 0;
   return <li key={milestone.id} className={milestone.outcome.demonstrated || milestone.completion ? 'reached' : undefined}>
    <div className="timeline-row"><strong>{milestone.title}</strong><span>{hours(remaining)} remaining, projected {longDate(milestone.projected_start)} to {longDate(milestone.projected_end)}</span></div>
    <div className="timeline-track" title={`${milestone.title}: ${hours(remaining)} remaining, projected to finish ${longDate(milestone.projected_end)}`} aria-hidden="true">
     <div className="timeline-bar" style={{ left: `${left}%`, width: `${width}%` }}>{share > 0 && <span style={{ width: `${share}%` }} />}</div>
     <i className="timeline-marker" />
    </div>
    <p className="timeline-demonstrate">Show this: {milestone.demonstrable_outcome}</p>
    <p className="small">{progress.sessions_completed} of {progress.sessions_total} planned {progress.sessions_total === 1 ? 'session' : 'sessions'} complete. Finishing sessions records progress, not proficiency.</p>
    {milestoneActions?.(milestone)}
    {recordOutcome ? <OutcomeForm milestone={milestone} frozen={frozen} record={(demonstrated, note) => recordOutcome(milestone, demonstrated, note)} /> : <p className="timeline-outcome">Outcome not yet demonstrated.</p>}
   </li>;
  })}</ol>
 </section>;
}

"use client";
import { TaskList, type ViewContext } from './day-list';
import { fullDate, shortDate, weekDates, weekdayName } from './roadmap-calendar';
import { minutesOf, onDay, orderedMilestones, shortLength } from './roadmap-day';
import { GapQuestions } from './progress-views';
import type { Issue, Planner } from './types';

const signed = (value: number, sign: string) => value ? `${sign}${value}` : '0';
const count = (value: number, noun: string) => `${value} ${noun}${value === 1 ? '' : 's'}`;

/** A new plan before it is accepted: what changes, the first week and the milestones. Nothing here can be ticked. */
export function PlanPreview({ context, planner, blockers, goal, sourceChanged, accept, discard, backToSettings, keepTasks }: {
 context: ViewContext; planner: Planner; blockers: Issue[]; goal: string; sourceChanged: boolean;
 accept: () => void; discard: () => void; backToSettings: () => void; keepTasks: (decisions: { task_id: string; decision: 'keep' | 'discard' }[]) => void;
}) {
 const { plan, sessions, frozen } = context;
 const changes = plan.changes; const target = plan.config.target_date;
 const upcoming = sessions.filter(item => item.status === 'scheduled');
 const firstDay = upcoming.map(item => item.date).sort()[0] ?? plan.first_planning_week;
 const week = weekDates(firstDay).filter(day => onDay(upcoming, day).length);
 const firstWeek = upcoming.filter(item => weekDates(firstDay).includes(item.date));
 const milestones = orderedMilestones(plan);
 const review = plan.revision_review || [];
 const title = (id: string) => plan.editable_tasks?.find(task => task.id === id)?.title || sessions.find(item => item.task_id === id)?.title || 'New task';
 const shownBlockers = blockers.filter(blocker => blocker.code !== 'revision_review_required' && (!sourceChanged || blocker.code !== 'inputs_changed'));
 const lists: [string, string[]][] = changes ? [['Added sessions', changes.assignments_added], ['Moved sessions', changes.assignments_moved], ['Removed sessions', changes.assignments_removed], ['Added milestones', changes.milestones_added], ['Moved milestones', changes.milestones_moved], ['Removed milestones', changes.milestones_removed]] : [];
 return <div className="rv">
  <div className="rv-preview-bar" role="region" aria-label="Plan preview">
   <div><p className="rv-lab">Preview · not active until you accept it</p><p>New roadmap for {goal}{target ? `, to ${fullDate(target)}` : ''}</p></div>
   <div className="rv-chips">
    <button className="rv-btn" type="button" onClick={backToSettings}>Back to settings</button>
    {planner.active && <button className="rv-btn" type="button" disabled={frozen} onClick={discard}>Discard</button>}
    <button className="rv-btn accept" type="button" disabled={frozen || blockers.length > 0} onClick={accept}>Accept plan</button>
   </div>
  </div>
  {shownBlockers.length > 0 && <ul className="rv-updates" role="status">{shownBlockers.map(blocker => <li key={blocker.code}>{blocker.message}</li>)}</ul>}
  {review.length > 0 && <section className="rv-card" aria-labelledby="dup-h">
   <h2 id="dup-h">Check elo’s new tasks before accepting</h2>
   <p className="rv-note" style={{ marginTop: 6 }}>You have tasks you added, changed, finished or removed. Keep each new task below, or leave it out if it repeats work you’ve already dealt with.</p>
   <ul className="rv-review-list">{review.map(item => <li key={item.task_id}><span>{title(item.task_id)}</span><span className="rv-chips"><button className="rv-btn sm" type="button" disabled={frozen} onClick={() => keepTasks([{ task_id: item.task_id, decision: 'keep' }])}>Keep</button><button className="rv-btn sm danger" type="button" disabled={frozen} onClick={() => keepTasks([{ task_id: item.task_id, decision: 'discard' }])}>Leave out</button></span></li>)}</ul>
   {review.length > 1 && <button className="rv-btn sm pri" type="button" style={{ marginTop: 14 }} disabled={frozen} onClick={() => keepTasks(review.map(item => ({ task_id: item.task_id, decision: 'keep' as const })))}>Keep all {review.length} new tasks</button>}
  </section>}
  <section className="rv-card wide rv-preview-sum" aria-labelledby="sum-h">
   <h2 id="sum-h">{plan.summary}</h2>
   <p>{plan.deadline_outcome.summary}</p>
   <p className="rv-note">Times are in {plan.config.time_zone}. Effort and dates after this week are projections.</p>
   {changes && <>
    <h3 className="rv-lab" style={{ marginTop: 22 }}>What changes from your current plan</h3>
    <div className="rv-deltas">
     <div className="rv-delta"><strong>{signed(changes.assignments_added.length, '+')}</strong><span>sessions added</span></div>
     <div className="rv-delta"><strong>{signed(changes.assignments_removed.length, '−')}</strong><span>sessions removed</span></div>
     <div className="rv-delta"><strong>{signed(changes.milestones_added.length, '+')}</strong><span>milestones added</span></div>
     <div className="rv-delta"><strong>{signed(changes.milestones_removed.length, '−')}</strong><span>milestones removed</span></div>
     <div className="rv-delta kept"><strong>{changes.completed_preserved}</strong><span>completed {changes.completed_preserved === 1 ? 'session stays' : 'sessions stay'} as recorded</span></div>
    </div>
    <div className="rv-change-lists">{lists.filter(([, items]) => items.length).map(([label, items]) => <details key={label}><summary className="rv-sum">{label} ({items.length})</summary><ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul></details>)}</div>
   </>}
  </section>
  <div className="rv-cols">
   <section className="rv-card wide rv-main rv-first-week" aria-labelledby="wk-h">
    <div className="rv-row-between" style={{ alignItems: 'baseline' }}><h2 id="wk-h" style={{ fontSize: 18 }}>Your first week</h2><span className="rv-note">{count(firstWeek.length, 'session')} · {shortLength(minutesOf(firstWeek))}</span></div>
    {week.map(day => <div key={day}><p className="rv-lab" style={{ marginTop: 16 }}>{weekdayName(day)}, {shortDate(day)}</p><TaskList day={day} items={onDay(upcoming, day)} context={context} editor={null} readOnly /></div>)}
    {!week.length && <p className="rv-empty">No sessions are dated in this preview.</p>}
    <p className="rv-note" style={{ marginTop: 12 }}>Accept the plan to start ticking these off.</p>
   </section>
   <aside className="rv-rail" style={{ maxWidth: 400 }} aria-label="Milestones in this plan">
    <section className="rv-card" aria-labelledby="ms-h">
     <h2 id="ms-h" className="rv-lab">{count(milestones.length, 'milestone')}</h2>
     <ol className="rv-ms-mini">{milestones.map((milestone, index) => <li key={milestone.id}><span className={`rv-stop sm ${index === 0 ? 'ink' : 'plain'}`} style={{ width: 26, height: 26, fontSize: 12, flex: '0 0 auto' }}>{index + 1}</span><div><strong>{milestone.title}</strong><small>{shortDate(milestone.projected_start)} – {shortDate(milestone.projected_end)} · {shortLength(milestone.estimated_minutes)}{(milestone.checkpoints || []).length ? ` · ${count(milestone.checkpoints!.length, 'checkpoint')}` : ''}</small></div></li>)}</ol>
     <p className="rv-note" style={{ marginTop: 14, fontSize: 12 }}>{plan.deadline_outcome.fits_in_runway ? 'Fits your runway.' : 'Some work doesn’t fit before your target date.'} Dates after this week are projections.</p>
    </section>
    <GapQuestions gaps={plan.gaps} confirmations={planner.confirmations} frozen={frozen} confirm={context.actions.confirm} />
   </aside>
  </div>
 </div>;
}

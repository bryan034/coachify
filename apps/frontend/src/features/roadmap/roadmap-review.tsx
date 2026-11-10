"use client";
import { MilestoneTimeline, RouteMap } from './milestone-timeline';
import { clockRange } from './roadmap-calendar';
import { hours, longDate } from './settings-panel';
import { TaskPlanner } from './task-planner';
import type { Confirmation, Issue, PlanAssignment, PlanGap, PlanMilestone, PlanReview, PlannedRoadmap, Planner, NotesDocument } from './types';

const answers: [Confirmation['answer'], string][] = [['have_experience', 'Yes'], ['some_experience', 'Somewhat'], ['no_experience', 'No'], ['not_sure', 'Not sure']];

function GapItem({ gap, plan, answer, frozen, confirm }: { gap: PlanGap; plan: PlannedRoadmap; answer?: Confirmation; frozen: boolean; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void }) {
 const diagnostic = plan.assignments.find(session => session.kind === 'diagnostic' && session.gap_id === gap.id);
 return <li className="gap-item">
  <div><strong>{gap.name}</strong><span className="pill n">{gap.source === 'inferred' ? 'Inferred requirement' : 'Stated in your goal'}</span></div>
  <p>{gap.rationale}</p>
  {gap.source === 'inferred' && gap.inference_reason && <p className="small">Why it’s inferred: {gap.inference_reason}</p>}
  {diagnostic && <p className="small">A short diagnostic on {longDate(diagnostic.date)} will test this.</p>}
  {gap.resolution === 'confirm_experience' && gap.confirmation_question && <fieldset className="gap-question" disabled={frozen}>
   <legend>{gap.confirmation_question}</legend>
   {answers.map(([value, label]) => <label key={value}><input type="radio" name={`confirm-${gap.id}`} checked={answer?.answer === value} onChange={() => confirm(gap, value)} />{label}</label>)}
   <p className="small">Your answer only affects this plan. To change your saved evidence, update your Skills Profile.</p>
  </fieldset>}
 </li>;
}

/** More to show than the mock-up's week view: each skill the plan works on, with the sessions behind it. */
function SkillProgress({ plan, review }: { plan: PlannedRoadmap; review: PlanReview }) {
 const rows = plan.gaps.map(gap => {
  const stats = plan.milestones.filter(milestone => milestone.gap_ids.includes(gap.id)).map(milestone => review.milestones[milestone.id]).filter(Boolean);
  const total = stats.reduce((sum, item) => sum + item.sessions_total, 0); const done = stats.reduce((sum, item) => sum + item.sessions_completed, 0);
  return { gap, total, done };
 }).sort((a, b) => a.gap.priority - b.gap.priority);
 if (!rows.length) return null;
 return <section className="skill-progress" aria-label="Skills this plan builds">
  <h2>Skills this plan builds</h2>
  <ul>{rows.map(({ gap, total, done }) => <li key={gap.id}>
   <div><strong>{gap.name}</strong><span>{total ? `${done} of ${total} ${total === 1 ? 'session' : 'sessions'}` : 'Sessions not planned yet'}</span></div>
   <i aria-hidden="true"><b style={{ width: `${total ? done / total * 100 : 0}%` }} /></i>
  </li>)}</ul>
 </section>;
}

export function RoadmapReview({ plan, review, preview, planner, blockers, frozen, accept, discard, backToSettings, revise, complete, reopen, recordOutcome, confirm, saveNotes }: {
 saveNotes?: (taskId: string, notes: NotesDocument) => Promise<unknown>;
 plan: PlannedRoadmap; review: PlanReview; preview: boolean; planner: Planner; blockers: Issue[]; frozen: boolean;
 accept: () => void; discard: () => void; backToSettings: () => void; revise: () => void;
 complete: (session: PlanAssignment, note: string) => Promise<unknown>; reopen: (session: PlanAssignment) => Promise<unknown>;
 recordOutcome: (milestone: PlanMilestone, demonstrated: boolean, note: string) => void; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void;
}) {
 const next = plan.assignments.find(session => session.id === review.next_assignment_id);
 const remaining = review.remaining;
 const confirmed = plan.gaps.filter(gap => gap.status === 'confirmed_gap').sort((a, b) => a.priority - b.priority);
 const unknown = plan.gaps.filter(gap => gap.status === 'unknown').sort((a, b) => a.priority - b.priority);
 const target = plan.config.target_date!;
 const changes = plan.changes;
 const changeRows = changes ? [['Sessions added', changes.assignments_added], ['Sessions moved', changes.assignments_moved], ['Sessions removed', changes.assignments_removed], ['Milestones added', changes.milestones_added], ['Milestones moved', changes.milestones_moved], ['Milestones removed', changes.milestones_removed]] as const : [];
 return <div className="roadmap-review">
  <header className="review-status">
   <div className="review-summary">
    <span className={`plan-state${preview ? ' preview' : ''}`}>{preview ? 'Preview: not active until you accept it' : 'Your active roadmap'}</span>
    <h2>{plan.summary}</h2>
    <p className="small">Times are in {plan.config.time_zone}. Effort and dates after this week are projections.</p>
   </div>
   <div className="plan-actions">
    {preview ? <>
     <button type="button" className="btn primary" disabled={frozen || blockers.length > 0} onClick={accept}>Accept plan</button>
     <button type="button" className="btn ghost" onClick={backToSettings}>Back to configuration</button>
     {planner.signals.length > 0 && <button type="button" className="btn ghost" disabled={frozen} onClick={revise}>Regenerate</button>}
     {planner.active && <button type="button" className="btn ghost" disabled={frozen} onClick={discard}>Discard preview</button>}
    </> : <>
     <button type="button" className={`btn${planner.signals.length ? ' primary' : ' ghost'}`} disabled={frozen} onClick={revise}>Preview updated roadmap</button>
     <button type="button" className="btn ghost" onClick={backToSettings}>Change settings</button>
    </>}
   </div>
   {preview && blockers.map(blocker => <p className="roadmap-notice" key={blocker.code}>{blocker.message}</p>)}
   {!preview && planner.signals.map(signal => <p className="roadmap-notice" key={signal.kind + signal.message}>{signal.message}</p>)}
   {preview && planner.signals.map(signal => <p className="roadmap-notice" key={signal.kind + signal.message}>{signal.message} Regenerate to include them.</p>)}
  </header>

  {preview && changes && <section className="review-card review-section" aria-label="What this preview changes">
   <h3>What this preview changes</h3>
   <p className="small">{changes.completed_preserved} completed {changes.completed_preserved === 1 ? 'session stays' : 'sessions stay'} exactly as recorded.</p>
   {changeRows.filter(([, items]) => items.length).map(([label, items]) => <div key={label}><h4>{label}</h4><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}
   {!changeRows.some(([, items]) => items.length) && <p className="small">No sessions or milestones moved.</p>}
  </section>}

  <div className="review-work">
   <TaskPlanner key={plan.id} plan={plan} review={review} frozen={frozen} complete={preview ? null : complete} reopen={preview ? null : reopen} saveNotes={preview ? null : saveNotes ?? null} />
   <div className="review-side">
    <section className="review-now" aria-label="Where you are now">
     <div className="review-next"><h3>Next assignment</h3>{next ? <><p className="review-value">{longDate(next.date)}, <span className="review-time">{clockRange(next.start_time, next.duration_minutes)}</span></p><p>{next.task}</p></> : <p className="small">No upcoming session. Preview an updated roadmap to plan your next week.</p>}</div>
     <div className="review-remaining"><h3>Remaining</h3>{remaining.calendar ? <p className="review-value">{remaining.calendar.label}</p> : <p className="review-value">The target date has passed</p>}<p>{hours(remaining.study.usable_minutes)} of usable study time</p>{plan.config.use_backup ? <p className="small">Includes {hours(remaining.study.backup_extra_minutes)} from backup blocks.</p> : remaining.study.backup_extra_minutes > 0 && <p className="small">Backup blocks could add {hours(remaining.study.backup_extra_minutes)}.</p>}<p className="small">Target date: {longDate(target)}</p></div>
    </section>
    <SkillProgress plan={plan} review={review} />
   </div>
  </div>

  <div className="review-body"><div className="review-column">
  <section className="review-card review-route" aria-label="Route to your goal"><RouteMap plan={plan} review={review} /></section>
  <div className="review-card"><MilestoneTimeline plan={plan} review={review} frozen={frozen} recordOutcome={preview ? null : recordOutcome} /></div>
  </div><div className="review-column">
  <section className="review-card review-section" aria-labelledby="outcome-title">
   <h3 id="outcome-title">What you can reach by {longDate(target)}</h3>
   <p>{plan.deadline_outcome.summary}</p>
   {!!plan.deadline_outcome.achievable_by_target.length && <ul>{plan.deadline_outcome.achievable_by_target.map((item, i) => <li key={i}>{item}</li>)}</ul>}
   <p className="small">This is a projection, not a guarantee of readiness.</p>
   {plan.beyond_deadline.length > 0 && <div className="review-beyond"><h4>Beyond your deadline</h4><p className="small">These don’t fit before your target date.</p><ul>{plan.beyond_deadline.map((item, i) => <li key={i}><strong>{item.title}</strong>, about {hours(item.estimated_minutes)}<br />{item.reason}</li>)}</ul></div>}
  </section>

  <section className="review-card review-section" aria-labelledby="gaps-title">
   <h3 id="gaps-title">Gaps this plan works on</h3>
   {!plan.gaps.length && <p className="small">No gaps were identified from your evidence.</p>}
   {confirmed.length > 0 && <><h4>Confirmed gaps</h4><ul className="gap-list">{confirmed.map(gap => <GapItem key={gap.id} gap={gap} plan={plan} answer={planner.confirmations[gap.id]} frozen={frozen} confirm={confirm} />)}</ul></>}
   {unknown.length > 0 && <><h4>Unknown skills</h4><p className="small">Your evidence doesn’t show these either way.</p><ul className="gap-list">{unknown.map(gap => <GapItem key={gap.id} gap={gap} plan={plan} answer={planner.confirmations[gap.id]} frozen={frozen} confirm={confirm} />)}</ul></>}
   {plan.assessment.constraints.length > 0 && <><h4>Conditions study can’t change</h4><ul>{plan.assessment.constraints.map(item => <li key={item.ref}>{item.name}</li>)}</ul></>}
   {plan.exclusions.length > 0 && <><h4>Left out at your request</h4><ul>{plan.exclusions.map(item => <li key={item.requirement_ref}>{item.reason}</li>)}</ul></>}
  </section>
  </div></div>
 </div>;
}

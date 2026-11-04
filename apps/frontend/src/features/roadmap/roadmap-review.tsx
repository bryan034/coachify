"use client";
import { useState } from 'react';
import { MilestoneTimeline, RouteMap } from './milestone-timeline';
import { hours, longDate } from './settings-panel';
import type { Confirmation, Issue, PlanAssignment, PlanGap, PlanMilestone, PlanReview, PlannedRoadmap, Planner } from './types';

const clock = (session: PlanAssignment) => {
 const [hour, minute] = session.start_time.split(':').map(Number); const end = hour * 60 + minute + session.duration_minutes;
 return `${session.start_time}–${String(Math.floor(end / 60)).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}`;
};
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

function SessionItem({ session, plan, next, missed, frozen, complete, reopen }: { session: PlanAssignment; plan: PlannedRoadmap; next: boolean; missed: boolean; frozen: boolean; complete: ((session: PlanAssignment, note: string) => void) | null; reopen: ((session: PlanAssignment) => void) | null }) {
 const [note, setNote] = useState('');
 const milestone = plan.milestones.find(m => m.key === session.milestone_key);
 return <li className={`session-item ${session.status}`}>
  <div className="session-when"><strong>{longDate(session.date)}</strong><span>{clock(session)}</span><span>{session.duration_minutes} min</span>{next && <span className="pill n">Next</span>}{missed && <span className="pill n">Passed</span>}{session.kind === 'diagnostic' && <span className="pill n">Diagnostic</span>}</div>
  <p className="session-task">{session.task}</p>
  <p className="small">Done when: {session.completion_criterion}</p>
  {milestone && <p className="small">Milestone: {milestone.title}</p>}
  {session.evidence_note && <p className="small">Your note: {session.evidence_note}</p>}
  {complete && <details className="session-complete"><summary>Mark session complete</summary><label>What did you produce? (optional)<textarea maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label><button type="button" className="btn" disabled={frozen} onClick={() => complete(session, note)}>Complete session</button></details>}
  {reopen && <button type="button" className="btn ghost" disabled={frozen} onClick={() => reopen(session)}>Reopen session</button>}
 </li>;
}

export function RoadmapReview({ plan, review, preview, planner, blockers, frozen, accept, discard, backToSettings, revise, complete, reopen, recordOutcome, confirm }: {
 plan: PlannedRoadmap; review: PlanReview; preview: boolean; planner: Planner; blockers: Issue[]; frozen: boolean;
 accept: () => void; discard: () => void; backToSettings: () => void; revise: () => void;
 complete: (session: PlanAssignment, note: string) => void; reopen: (session: PlanAssignment) => void;
 recordOutcome: (milestone: PlanMilestone, demonstrated: boolean, note: string) => void; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void;
}) {
 const next = plan.assignments.find(session => session.id === review.next_assignment_id);
 const remaining = review.remaining;
 const scheduled = plan.assignments.filter(session => session.status === 'scheduled').sort((a, b) => `${a.date}${a.start_time}`.localeCompare(`${b.date}${b.start_time}`));
 const completed = plan.assignments.filter(session => session.status === 'completed');
 const confirmed = plan.gaps.filter(gap => gap.status === 'confirmed_gap').sort((a, b) => a.priority - b.priority);
 const unknown = plan.gaps.filter(gap => gap.status === 'unknown').sort((a, b) => a.priority - b.priority);
 const target = plan.config.target_date!;
 const changes = plan.changes;
 const changeRows = changes ? [['Sessions added', changes.assignments_added], ['Sessions moved', changes.assignments_moved], ['Sessions removed', changes.assignments_removed], ['Milestones added', changes.milestones_added], ['Milestones moved', changes.milestones_moved], ['Milestones removed', changes.milestones_removed]] as const : [];
 return <div className="roadmap-review">
  <header className="review-hero">
   <span className={`plan-state${preview ? ' preview' : ''}`}>{preview ? 'Preview: not active until you accept it' : 'Your active roadmap'}</span>
   <h2>{plan.summary}</h2>
   <p className="small">Times are in {plan.config.time_zone}. Effort and dates after this week are projections.</p>
   {preview && blockers.map(blocker => <p className="roadmap-notice" key={blocker.code}>{blocker.message}</p>)}
   {!preview && planner.signals.map(signal => <p className="roadmap-notice" key={signal.kind + signal.message}>{signal.message}</p>)}
   {preview && planner.signals.map(signal => <p className="roadmap-notice" key={signal.kind + signal.message}>{signal.message} Regenerate to include them.</p>)}
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
   <RouteMap plan={plan} review={review} />
  </header>

  {preview && changes && <section className="review-section review-changes" aria-label="What this preview changes">
   <h3>What this preview changes</h3>
   <p className="small">{changes.completed_preserved} completed {changes.completed_preserved === 1 ? 'session stays' : 'sessions stay'} exactly as recorded.</p>
   {changeRows.filter(([, items]) => items.length).map(([label, items]) => <div key={label}><h4>{label}</h4><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}
   {!changeRows.some(([, items]) => items.length) && <p className="small">No sessions or milestones moved.</p>}
  </section>}

  <section className="review-now" aria-label="Where you are now">
   <div className="review-next"><h3>Next assignment</h3>{next ? <><p className="review-value">{longDate(next.date)}, {clock(next)}</p><p>{next.task}</p><p className="small">Done when: {next.completion_criterion}</p></> : <p className="small">No upcoming session. Preview an updated roadmap to plan your next week.</p>}</div>
   <div className="review-remaining"><h3>Remaining</h3>{remaining.calendar ? <p className="review-value">{remaining.calendar.label}</p> : <p className="review-value">The target date has passed</p>}<p>{hours(remaining.study.usable_minutes)} of usable study time</p>{plan.config.use_backup ? <p className="small">Includes {hours(remaining.study.backup_extra_minutes)} from backup blocks.</p> : remaining.study.backup_extra_minutes > 0 && <p className="small">Backup blocks could add {hours(remaining.study.backup_extra_minutes)}.</p>}<p className="small">Target date: {longDate(target)}</p></div>
  </section>

  <div className="review-body"><div className="review-column">
  <MilestoneTimeline plan={plan} review={review} frozen={frozen} recordOutcome={preview ? null : recordOutcome} />

  <section className="review-section" aria-labelledby="sessions-title">
   <h3 id="sessions-title">Upcoming sessions</h3>
   {!scheduled.length && <p className="small">No sessions are planned right now.</p>}
   <ul className="session-list">{scheduled.map(session => <SessionItem key={session.id} session={session} plan={plan} next={session.id === review.next_assignment_id} missed={review.missed_assignment_ids.includes(session.id)} frozen={frozen} complete={preview ? null : complete} reopen={null} />)}</ul>
  </section>

  {completed.length > 0 && <section className="review-section review-completed" aria-labelledby="completed-title">
   <h3 id="completed-title">Completed sessions</h3>
   <p className="small">These record what you did. They don’t change your assessed skills.</p>
   <ul className="session-list">{completed.map(session => <SessionItem key={session.id} session={session} plan={plan} next={false} missed={false} frozen={frozen} complete={null} reopen={preview ? null : reopen} />)}</ul>
  </section>}
  </div><div className="review-column">
  <section className="review-section" aria-labelledby="outcome-title">
   <h3 id="outcome-title">What you can reach by {longDate(target)}</h3>
   <p>{plan.deadline_outcome.summary}</p>
   {!!plan.deadline_outcome.achievable_by_target.length && <ul>{plan.deadline_outcome.achievable_by_target.map((item, i) => <li key={i}>{item}</li>)}</ul>}
   <p className="small">This is a projection, not a guarantee of readiness.</p>
   {plan.beyond_deadline.length > 0 && <div className="review-beyond"><h4>Beyond your deadline</h4><p className="small">These don’t fit before your target date.</p><ul>{plan.beyond_deadline.map((item, i) => <li key={i}><strong>{item.title}</strong>, about {hours(item.estimated_minutes)}<br />{item.reason}</li>)}</ul></div>}
  </section>

  <section className="review-section" aria-labelledby="gaps-title">
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

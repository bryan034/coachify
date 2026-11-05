"use client";
import { useState } from 'react';
import { MilestoneTimeline, RouteMap } from './milestone-timeline';
import { hours, longDate } from './settings-panel';
import type { Beyond, CandidateView, Confirmation, Issue, LegacyAssignment, LegacyRoadmap, PlanAssignment, PlanGap, PlanMilestone, PlanReview, PlannedRoadmap, Planner } from './types';

type AnyRoadmap = PlannedRoadmap | LegacyRoadmap;
type Session = PlanAssignment | LegacyAssignment;

const clock = (session: { start_time: string | null; duration_minutes: number }) => {
 if (!session.start_time) return '';
 const [hour, minute] = session.start_time.split(':').map(Number); const end = hour * 60 + minute + session.duration_minutes;
 return `${session.start_time}–${String(Math.floor(end / 60)).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}`;
};
const answers: [Confirmation['answer'], string][] = [['have_experience', 'Yes'], ['some_experience', 'Somewhat'], ['no_experience', 'No'], ['not_sure', 'Not sure']];

export function GapItem({ gap, plan, answer, frozen, confirm }: { gap: PlanGap; plan: AnyRoadmap; answer?: Confirmation; frozen: boolean; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void }) {
 const diagnostic = (plan.assignments as Session[]).find(session => session.kind === 'diagnostic' && session.gap_id === gap.id);
 return <li className="gap-item">
  <div><strong>{gap.name}</strong><span className="pill n">{gap.source === 'inferred' ? 'Inferred requirement' : 'Stated in your goal'}</span></div>
  <p>{gap.rationale}</p>
  {gap.source === 'inferred' && gap.inference_reason && <p className="small">Why it’s inferred: {gap.inference_reason}</p>}
  {diagnostic?.date && <p className="small">A short diagnostic on {longDate(diagnostic.date)} will test this.</p>}
  {gap.resolution === 'confirm_experience' && gap.confirmation_question && <fieldset className="gap-question" disabled={frozen}>
   <legend>{gap.confirmation_question}</legend>
   {answers.map(([value, label]) => <label key={value}><input type="radio" name={`confirm-${gap.id}`} checked={answer?.answer === value} onChange={() => confirm(gap, value)} />{label}</label>)}
   <p className="small">Your answer only affects this plan. To change your saved evidence, update your Skills Profile.</p>
  </fieldset>}
 </li>;
}

function SessionItem({ session, plan, next, missed }: { session: Session; plan: AnyRoadmap; next: boolean; missed: boolean }) {
 const milestone = plan.milestones.find(m => m.key === session.milestone_key);
 return <li className={`session-item ${session.status}`}>
  <div className="session-when">{session.date && <strong>{longDate(session.date)}</strong>}<span>{clock(session)}</span><span>{session.duration_minutes} min</span>{next && <span className="pill n">Next</span>}{missed && <span className="pill n">Passed</span>}{session.kind === 'diagnostic' && <span className="pill n">Diagnostic</span>}</div>
  <p className="session-task">{session.task}</p>
  {session.completion_criterion && <p className="small">Done when: {session.completion_criterion}</p>}
  {'refresher_reason' in session && session.refresher_reason && <p className="small">Why it returns: {session.refresher_reason}</p>}
  {milestone && <p className="small">Milestone: {milestone.title}</p>}
  {session.evidence_note && <p className="small">Your note: {session.evidence_note}</p>}
 </li>;
}

/** The candidate preview of a new roadmap, and the read-only view of an older roadmap-v2 plan. */
export function RoadmapReview({ plan, review, preview, view, planner, blockers, frozen, accept, discard, backToSettings, regenerate, showCurrent, startNew, confirm }: {
 plan: AnyRoadmap; review: PlanReview; preview: boolean; view?: CandidateView | null; planner: Planner; blockers: Issue[]; frozen: boolean;
 accept: () => void; discard: () => void; backToSettings: () => void; regenerate: () => void; showCurrent: (() => void) | null; startNew: () => void; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void;
}) {
 const sessions = plan.assignments as Session[];
 const next = sessions.find(session => session.id === review.next_assignment_id);
 const remaining = review.remaining;
 const scheduled = sessions.filter(session => session.status === 'scheduled' && session.date).sort((a, b) => `${a.date}${a.start_time}`.localeCompare(`${b.date}${b.start_time}`));
 const completed = sessions.filter(session => session.status === 'completed');
 const confirmed = plan.gaps.filter(gap => gap.status === 'confirmed_gap').sort((a, b) => a.priority - b.priority);
 const unknown = plan.gaps.filter(gap => gap.status === 'unknown').sort((a, b) => a.priority - b.priority);
 const target = plan.config.target_date!;
 const changes = plan.changes;
 const beyond: Beyond[] = plan.schema_version === 'roadmap-v3' ? plan.deferred_scope : plan.beyond_deadline;
 const changeRows = changes ? [['Sessions added', changes.assignments_added], ['Sessions moved', changes.assignments_moved], ['Sessions removed', changes.assignments_removed], ['Milestones added', changes.milestones_added], ['Milestones moved', changes.milestones_moved], ['Milestones removed', changes.milestones_removed]] as const : [];
 const replaced = preview && !!planner.active;
 return <div className="roadmap-review">
  <header className="review-hero">
   <span className={`plan-state${preview ? ' preview' : ''}`}>{preview ? 'Preview: not active until you accept it' : 'Earlier roadmap: read-only'}</span>
   <h2>{plan.summary}</h2>
   <p className="small">Times are in {plan.config.time_zone}. Tasks cover your next two weeks; later weeks stay as outlines.</p>
   {!preview && <p className="roadmap-notice">This roadmap was made in an older format, so it stays read-only. Start a new roadmap to use weekly tasks, moves and check-ins. It uses what you’ve finished here.</p>}
   {replaced && <p className="roadmap-notice">Your current roadmap stays active until you accept this one. Accepting archives it as read-only, with its progress and history.</p>}
   {preview && blockers.map(blocker => <p className="roadmap-notice" key={blocker.code}>{blocker.message}</p>)}
   {preview && planner.signals.map(signal => <p className="roadmap-notice" key={signal.kind + signal.message}>{signal.message} Regenerate to include them.</p>)}
   <div className="plan-actions">
    {preview ? <>
     <button type="button" className="btn primary" disabled={frozen || blockers.length > 0} onClick={accept}>Accept plan</button>
     <button type="button" className="btn ghost" onClick={backToSettings}>Back to configuration</button>
     {planner.signals.length > 0 && <button type="button" className="btn ghost" disabled={frozen} onClick={regenerate}>Regenerate</button>}
     {showCurrent && <button type="button" className="btn ghost" onClick={showCurrent}>View current roadmap</button>}
     {planner.active && <button type="button" className="btn ghost" disabled={frozen} onClick={discard}>Discard preview</button>}
    </> : <button type="button" className="btn primary" disabled={frozen} onClick={startNew}>Start new roadmap</button>}
   </div>
   <RouteMap plan={plan} review={review} />
  </header>

  {replaced && changes && <section className="review-section review-changes" aria-label="What this preview changes">
   <h3>What this preview changes</h3>
   {changeRows.filter(([, items]) => items.length).map(([label, items]) => <div key={label}><h4>{label}</h4><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}
   {!changeRows.some(([, items]) => items.length) && <p className="small">No sessions or milestones moved.</p>}
  </section>}

  <section className="review-now" aria-label="Where you are now">
   <div className="review-next"><h3>Next assignment</h3>{next?.date ? <><p className="review-value">{longDate(next.date)}, {clock(next)}</p><p>{next.task}</p>{next.completion_criterion && <p className="small">Done when: {next.completion_criterion}</p>}</> : <p className="small">No upcoming session.</p>}</div>
   <div className="review-remaining"><h3>Remaining</h3>{remaining.calendar ? <p className="review-value">{remaining.calendar.label}</p> : <p className="review-value">The target date has passed</p>}<p>{hours(remaining.study.usable_minutes)} of usable study time</p>{plan.config.use_backup ? <p className="small">Includes {hours(remaining.study.backup_extra_minutes)} from backup blocks.</p> : remaining.study.backup_extra_minutes > 0 && <p className="small">Backup blocks could add {hours(remaining.study.backup_extra_minutes)}.</p>}<p className="small">Target date: {longDate(target)}</p>
    {view && <><p className="small">Finishes this scope by: {view.projection.scheduled_finish ? longDate(view.projection.scheduled_finish) : 'no estimate'} (scheduled projection)</p>{view.projection.deferred_minutes > 0 && <p className="small">All work including deferred scope: {view.projection.projected_finish ? longDate(view.projection.projected_finish) : 'no estimate'}. {view.projection.assumption}</p>}</>}
   </div>
  </section>

  <div className="review-body"><div className="review-column">
  <MilestoneTimeline plan={plan} review={review} frozen={frozen} recordOutcome={null} />

  <section className="review-section" aria-labelledby="sessions-title">
   <h3 id="sessions-title">Upcoming sessions</h3>
   {!scheduled.length && <p className="small">No sessions are planned right now.</p>}
   <ul className="session-list">{scheduled.map(session => <SessionItem key={session.id} session={session} plan={plan} next={session.id === review.next_assignment_id} missed={review.missed_assignment_ids.includes(session.id)} />)}</ul>
  </section>

  {view && <section className="review-section" aria-labelledby="outline-title">
   <h3 id="outline-title">Week by week</h3>
   <ol className="outline-list">{view.weeks.map(week => <li key={week.week_start}><div><strong>Week of {longDate(week.week_start)}</strong><span>{hours(week.target_minutes)} target</span></div>{week.theme && <p>{week.theme}</p>}{week.expected_output && <p className="small">Expected output: {week.expected_output}</p>}{week.contains_target && <p className="target-boundary">Target date: {longDate(target)}</p>}</li>)}</ol>
  </section>}

  {completed.length > 0 && <section className="review-section review-completed" aria-labelledby="completed-title">
   <h3 id="completed-title">Completed sessions</h3>
   <p className="small">These record what you did. They don’t change your assessed skills.</p>
   <ul className="session-list">{completed.map(session => <SessionItem key={session.id} session={session} plan={plan} next={false} missed={false} />)}</ul>
  </section>}
  </div><div className="review-column">
  <section className="review-section" aria-labelledby="outcome-title">
   <h3 id="outcome-title">What you can reach by {longDate(target)}</h3>
   <p>{plan.deadline_outcome.summary}</p>
   {!!plan.deadline_outcome.achievable_by_target.length && <ul>{plan.deadline_outcome.achievable_by_target.map((item, i) => <li key={i}>{item}</li>)}</ul>}
   <p className="small">This is a projection, not a guarantee of readiness.</p>
   {beyond.length > 0 && <div className="review-beyond"><h4>Beyond your deadline</h4><p className="small">These don’t fit before your target date. They stay outside your schedule unless you accept a scope or date change.</p><ul>{beyond.map((item, i) => <li key={i}><strong>{item.title}</strong>, about {hours(item.estimated_minutes)}<br />{item.reason}</li>)}</ul></div>}
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

"use client";
import { useMemo, useState } from 'react';
import { CoachPanel, ProposalPanel } from './coach-panel';
import { MilestoneTimeline } from './milestone-timeline';
import { GapItem } from './roadmap-review';
import { hours, longDate } from './settings-panel';
import { AddTaskForm, TaskItem, taskWhen, type Act } from './task-item';
import { roadmapApi } from '@/lib/api/roadmap';
import type { ActiveView, ArchivedRoadmap, Confirmation, LegacyRoadmap, PlanAssignment, PlanGap, PlanMilestone, PlanReview, PlannedRoadmap, Planner, WeekView } from './types';

const statusLabels = { on_track: 'On track', behind: 'Behind', insufficient_data: 'Insufficient data' };
const percent = (done: number, total: number) => total ? Math.min(100, Math.round(done / total * 100)) : 0;

function Header({ plan, view, frozen, edit, startNew }: { plan: PlannedRoadmap; view: ActiveView; frozen: boolean; edit: () => void; startNew: () => void }) {
 const { progress, pace, projection } = view;
 const share = percent(progress.roadmap_minutes.completed, progress.roadmap_minutes.planned);
 return <header className="active-header">
  <div className="active-title"><div><span className="plan-state">Your active roadmap</span><h2>{plan.assessment.role}</h2></div>
   <div className="plan-actions"><button type="button" className="btn ghost" disabled={frozen} onClick={edit}>Edit plan</button><button type="button" className="btn ghost" disabled={frozen} onClick={startNew}>Start new roadmap</button></div></div>
  <dl className="active-facts">
   <div><dt>Target date</dt><dd>{longDate(projection.target_date)}</dd></div>
   <div><dt>Projected finish</dt><dd>{projection.projected_finish ? longDate(projection.projected_finish) : 'No estimate'}</dd></div>
   <div><dt>Current week</dt><dd>{longDate(view.current_week)}</dd></div>
   <div><dt>Status</dt><dd className={`pace-status ${pace.status}`}>{statusLabels[pace.status]}{pace.status === 'behind' ? ` by ${hours(pace.behind_minutes)}` : ''}</dd></div>
  </dl>
  <p className="small">Projected finish is a scheduled projection covering all remaining work{projection.deferred_minutes > 0 ? `, including ${hours(projection.deferred_minutes)} of deferred scope outside your dated schedule` : ''}. {projection.assumption}</p>
  <div className="active-progress">
   <div className="active-progress-label"><strong>{progress.label}</strong><span>{hours(progress.roadmap_minutes.completed)} of {hours(progress.roadmap_minutes.planned)}</span></div>
   <div className="progress-track" role="progressbar" aria-label={progress.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={share}><i style={{ width: `${share}%` }} /></div>
   <ul className="active-counts"><li>{progress.generated_tasks.completed} of {progress.generated_tasks.planned} planned tasks</li><li>{progress.milestones.completed} of {progress.milestones.planned} milestones</li><li>{hours(pace.completed_minutes)} done, {hours(pace.expected_minutes)} due by now</li><li>{hours(progress.custom_scheduled_minutes)} of custom tasks scheduled{progress.custom_excluded_minutes ? ` (+${hours(progress.custom_excluded_minutes)} not counted)` : ''}</li></ul>
  </div>
 </header>;
}

function Today({ plan, view, tasks, act, frozen }: { plan: PlannedRoadmap; view: ActiveView; tasks: Map<string, PlanAssignment>; act: Act; frozen: boolean }) {
 // A task completed here stays in view, so its optional feedback can be given in place.
 const [finished, setFinished] = useState<string[]>([]);
 const watched: Act = async (path, data) => {
  const result = await act(path, data);
  if (result.ok && path === '/planner/assignments/status' && data.status === 'completed') setFinished(items => [...items, String(data.assignment_id)]);
  return result;
 };
 const next = view.next_task_id ? tasks.get(view.next_task_id) : undefined;
 const today = [...new Set([...view.today_task_ids, ...finished])].map(id => tasks.get(id)!).filter(task => task && task.id !== next?.id);
 const share = percent(view.this_week.completed, view.this_week.planned);
 return <section className="today" aria-labelledby="today-title">
  <div className="today-head"><h2 id="today-title">Today</h2><p className="small">{longDate(view.today)} · This week: {hours(view.this_week.completed)} of {hours(view.this_week.planned)}</p></div>
  <div className="progress-track" role="progressbar" aria-label="This week’s progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={share}><i style={{ width: `${share}%` }} /></div>
  {next ? <ul className="task-list today-next"><TaskItem task={next} next milestone={plan.milestones.find(m => m.key === next.milestone_key)} act={watched} frozen={frozen} /></ul> : <p className="small">Nothing is scheduled next. Check your Backlog, or add a task to a week below.</p>}
  {today.length > 0 && <ul className="task-list">{today.map(task => <TaskItem key={task.id} task={task} milestone={plan.milestones.find(m => m.key === task.milestone_key)} act={watched} frozen={frozen} />)}</ul>}
 </section>;
}

function WeekRow({ week, plan, tasks, act, frozen, target }: { week: WeekView; plan: PlannedRoadmap; tasks: Map<string, PlanAssignment>; act: Act; frozen: boolean; target: string }) {
 const [adding, setAdding] = useState(false); const [problem, setProblem] = useState('');
 const detailed = week.state === 'current' || week.state === 'next';
 const members = week.task_ids.map(id => tasks.get(id)).filter((task): task is PlanAssignment => !!task);
 const label = { past: 'Past', current: 'This week', next: 'Next week', later: 'Outline' }[week.state];
 async function pause(path: string) { const result = await act(path, { week_start: week.week_start }); setProblem(result.ok ? '' : result.message); }
 return <li className={`week-row ${week.state}${week.paused ? ' paused' : ''}`}>
  <details open={week.state === 'current'}>
   <summary><span className="week-name"><strong>Week of {longDate(week.week_start)}</strong><span className="pill n">{label}</span>{week.paused && <span className="pill n">Paused</span>}</span><span className="week-theme">{week.theme || (week.state === 'past' ? 'Past week' : 'No outline')}</span><span className="week-hours">{week.state === 'past' ? `${hours(week.completed_minutes)} done` : `${hours(week.scheduled_minutes + week.completed_minutes)} of ${hours(week.target_minutes)}`}</span></summary>
   <div className="week-body">
    {week.expected_output && <p className="small">Expected output: {week.expected_output}</p>}
    {week.workload_source === 'checkin' && <p className="small">Workload set by your check-in for this week only.</p>}
    {!!week.buffer_minutes && week.state !== 'past' && <p className="small">{hours(week.eligible_minutes)} eligible, with {hours(week.buffer_minutes)} kept free as buffer.</p>}
    {week.paused && <p className="small">This week is paused.{week.exception_task_ids.length ? ' Tasks you kept are shown as exceptions.' : ''}</p>}
    {week.state === 'past' && <p className="small">Outcome: {hours(week.completed_minutes)} completed, {members.filter(task => task.status === 'skipped').length} skipped.</p>}
    {(detailed || week.state === 'past' || week.paused) && members.length > 0 && <ul className="task-list">{members.map(task => <TaskItem key={task.id} task={task} milestone={plan.milestones.find(m => m.key === task.milestone_key)} act={act} frozen={frozen} />)}</ul>}
    {!detailed && week.state === 'later' && members.length > 0 && <ul className="week-later">{members.map(task => <li key={task.id}>{task.task} · {taskWhen(task)}</li>)}</ul>}
    {detailed && !members.length && !week.paused && <p className="small">No tasks yet.</p>}
    {week.state !== 'past' && <div className="plan-actions">
     <button type="button" className="btn ghost" disabled={frozen} aria-expanded={adding} aria-label={`Add task to the week of ${longDate(week.week_start)}`} onClick={() => setAdding(!adding)}>Add task</button>
     {week.paused
      ? <button type="button" className="btn ghost" disabled={frozen} aria-label={`Unpause the week of ${longDate(week.week_start)}`} onClick={() => void pause('/planner/proposals/unpause')}>Unpause week</button>
      : <button type="button" className="btn ghost" disabled={frozen} aria-label={`Pause the week of ${longDate(week.week_start)}`} onClick={() => void pause('/planner/proposals/pause')}>Pause week</button>}
    </div>}
    {adding && <AddTaskForm week={week.week_start} milestones={plan.milestones} act={act} frozen={frozen} close={() => setAdding(false)} />}
    {problem && <p className="task-problem" role="alert">{problem}</p>}
   </div>
  </details>
  {week.contains_target && <p className="target-boundary">Target date: {longDate(target)}. Work beyond this line is deferred.</p>}
 </li>;
}

function Backlog({ plan, view, tasks, act, frozen }: { plan: PlannedRoadmap; view: ActiveView; tasks: Map<string, PlanAssignment>; act: Act; frozen: boolean }) {
 const [problem, setProblem] = useState('');
 const skipped = view.skipped_task_ids.map(id => tasks.get(id)!).filter(Boolean);
 return <section className="backlog-section" aria-labelledby="backlog-title">
  <div className="backlog-column"><h2 id="backlog-title">Backlog</h2><p className="small">Unscheduled active work. Place these tasks into any valid time.</p>
   {!view.backlog.length && <p className="small">Nothing is waiting here.</p>}
   <ul className="task-list">{view.backlog.map(row => tasks.get(row.task_id) && <li key={row.task_id} className="backlog-entry"><p className="small">{row.reason}{row.suggested_slot ? ` Suggested: ${longDate(row.suggested_slot.date)} ${row.suggested_slot.start_time}.` : ''}</p><ul className="task-list"><TaskItem task={tasks.get(row.task_id)!} milestone={plan.milestones.find(m => m.key === tasks.get(row.task_id)!.milestone_key)} act={act} frozen={frozen} suggested={row.suggested_slot} /></ul></li>)}</ul>
   {skipped.length > 0 && <details className="backlog-skipped"><summary>Skipped tasks ({skipped.length})</summary><ul className="task-list">{skipped.map(task => <TaskItem key={task.id} task={task} act={act} frozen={frozen} />)}</ul></details>}
  </div>
  <div className="backlog-column" role="group" aria-labelledby="deferred-title"><h2 id="deferred-title">Deferred scope</h2><p className="small">Work that doesn’t fit before your target date. It stays outside your schedule until you accept a scope or date change.</p>
   {!plan.deferred_scope.length && <p className="small">Everything fits before your target date.</p>}
   <ul className="deferred-list">{plan.deferred_scope.map(item => <li key={item.id}><strong>{item.title}</strong><span className="small">About {hours(item.estimated_minutes)}{item.dependencies.length ? ` · depends on ${item.dependencies.join(', ')}` : ''}</span><p className="small">{item.reason}</p><button type="button" className="btn ghost" disabled={frozen} aria-label={`Preview bringing ${item.title} into the roadmap`} onClick={async () => { const result = await act('/planner/proposals/scope', { deferred_id: item.id }); setProblem(result.ok ? '' : result.message); }}>Preview bringing it in</button></li>)}</ul>
   {problem && <p className="task-problem" role="alert">{problem}</p>}
  </div>
 </section>;
}

function MilestoneActions({ milestone, plan, act, frozen }: { milestone: PlanMilestone; plan: PlannedRoadmap; act: Act; frozen: boolean }) {
 const [asking, setAsking] = useState(false); const [problem, setProblem] = useState('');
 const open = plan.assignments.filter(task => task.milestone_key === milestone.key && task.origin === 'generated' && (task.status === 'scheduled' || task.status === 'backlog')).length;
 async function send(data: Record<string, unknown>) { const result = await act('/planner/milestones/complete', { milestone_id: milestone.id, ...data }); setProblem(result.ok ? '' : result.message); if (result.ok) setAsking(false); }
 if (milestone.completion) return <p className="timeline-outcome">You marked this complete{milestone.completion.unfinished_choice === 'remove' ? ' and removed its unfinished tasks from scope' : milestone.completion.unfinished_choice === 'keep' ? ' and kept its unfinished tasks scheduled' : ''}. <button type="button" className="settings-link" disabled={frozen} onClick={() => void send({ completed: false })}>Reopen</button></p>;
 return <div className="milestone-actions">
  {!asking && <button type="button" className="btn ghost" disabled={frozen} aria-label={`Mark ${milestone.title} complete`} onClick={() => open ? setAsking(true) : void send({ completed: true })}>Mark complete</button>}
  {asking && <div role="group" aria-label={`${open} unfinished tasks under ${milestone.title}`}><p className="small">{open} unfinished {open === 1 ? 'task remains' : 'tasks remain'} under this milestone.</p><div className="plan-actions"><button type="button" className="btn" disabled={frozen} onClick={() => void send({ completed: true, unfinished: 'keep' })}>Keep them scheduled</button><button type="button" className="btn ghost" disabled={frozen} onClick={() => void send({ completed: true, unfinished: 'remove' })}>Remove them from scope</button><button type="button" className="btn ghost" onClick={() => setAsking(false)}>Cancel</button></div></div>}
  {problem && <p className="task-problem" role="alert">{problem}</p>}
 </div>;
}

function PastRoadmaps({ rows, token }: { rows: ArchivedRoadmap[]; token: string }) {
 const [open, setOpen] = useState<(PlannedRoadmap | LegacyRoadmap) | null>(null); const [problem, setProblem] = useState('');
 async function view(id: string) { try { setOpen(await roadmapApi<PlannedRoadmap | LegacyRoadmap>(`/history/${encodeURIComponent(id)}`, token)); setProblem(''); } catch (failure) { setProblem(failure instanceof Error ? failure.message : 'This roadmap could not be loaded.'); } }
 return <section className="review-section" aria-labelledby="past-title"><h3 id="past-title">Past roadmaps</h3>
  {!rows.length && <p className="small">Roadmaps you replace are kept here, read-only.</p>}
  <ul className="past-list">{rows.map(row => <li key={row.id}><div><strong>{row.role || 'Roadmap'}</strong><span className="small">{row.start_date ? longDate(row.start_date) : ''} to {row.target_date ? longDate(row.target_date) : ''}</span><span className="small">{hours(row.completed_minutes)} of {hours(row.planned_minutes)} · {row.tasks_completed} of {row.tasks_total} tasks · {row.milestones_completed} of {row.milestones_total} milestones</span></div><button type="button" className="btn ghost" aria-label={`View past roadmap: ${row.role || row.summary}`} onClick={() => void view(row.id)}>View</button></li>)}</ul>
  {problem && <p className="task-problem" role="alert">{problem}</p>}
  {open && <div className="past-detail" role="region" aria-label="Past roadmap details"><h4>{open.summary}</h4><p className="small">Read-only. Nothing here can change.</p><ul>{(open.assignments as { id: string; task: string; status: string }[]).map(task => <li key={task.id}>{task.task} · {task.status}</li>)}</ul><button type="button" className="btn ghost" onClick={() => setOpen(null)}>Close</button></div>}
 </section>;
}

export function ActiveRoadmap({ plan, view, review, planner, token, act, frozen, running, edit, startNew, propose, retryCheckin, retryRolling, confirm, recordOutcome }: {
 plan: PlannedRoadmap; view: ActiveView; review: PlanReview; planner: Planner; token: string; act: Act; frozen: boolean; running: boolean; edit: () => void; startNew: () => void;
 propose: (week: string) => Promise<void>; retryCheckin: () => void; retryRolling: () => void; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void; recordOutcome: (milestone: PlanMilestone, demonstrated: boolean, note: string) => void;
}) {
 const tasks = useMemo(() => new Map(plan.assignments.map(task => [task.id, task])), [plan]);
 const [adjusting, setAdjusting] = useState(false);
 const proposal = planner.proposal;
 const confirmed = plan.gaps.filter(gap => gap.status === 'confirmed_gap').sort((a, b) => a.priority - b.priority);
 const unknown = plan.gaps.filter(gap => gap.status === 'unknown').sort((a, b) => a.priority - b.priority);
 return <div className="active-roadmap">
  <Header plan={plan} view={view} frozen={frozen} edit={edit} startNew={startNew} />
  {planner.signals.map(signal => <p className="roadmap-notice" key={signal.kind + signal.message}>{signal.message}</p>)}
  {proposal && !adjusting && <ProposalPanel key={proposal.id} proposal={proposal} blockers={planner.proposal_blockers || []} act={act} frozen={frozen} adjust={proposal.kind === 'checkin' ? () => setAdjusting(true) : null} />}
  <Today plan={plan} view={view} tasks={tasks} act={act} frozen={frozen} />
  <CoachPanel plan={plan} view={view} tasks={tasks} act={act} frozen={frozen} propose={async week => { setAdjusting(false); await propose(week); }} retryCheckin={retryCheckin} canRetryCheckin={!!planner.retry_checkin} retryRolling={retryRolling} adjusting={adjusting} running={running} />
  <section className="weekly-roadmap" aria-labelledby="weekly-title"><h2 id="weekly-title">Weekly roadmap</h2>
   <ol className="week-list">{view.weeks.map(week => <WeekRow key={week.week_start} week={week} plan={plan} tasks={tasks} act={act} frozen={frozen} target={view.projection.target_date} />)}</ol>
  </section>
  <Backlog plan={plan} view={view} tasks={tasks} act={act} frozen={frozen} />
  <details className="secondary-details"><summary>Milestones, projected outcome, gaps and past roadmaps</summary>
   <div className="review-body"><div className="review-column">
    <MilestoneTimeline plan={plan} review={review} frozen={frozen} recordOutcome={recordOutcome} milestoneActions={milestone => <MilestoneActions milestone={milestone} plan={plan} act={act} frozen={frozen} />} />
    <PastRoadmaps rows={planner.archived || []} token={token} />
   </div><div className="review-column">
    <section className="review-section" aria-labelledby="outcome-title"><h3 id="outcome-title">What you can reach by {longDate(view.projection.target_date)}</h3><p>{plan.deadline_outcome.summary}</p>{!!plan.deadline_outcome.achievable_by_target.length && <ul>{plan.deadline_outcome.achievable_by_target.map((item, i) => <li key={i}>{item}</li>)}</ul>}<p className="small">This is a projection, not a guarantee of readiness. Finishing tasks records progress and doesn’t change your Skills Profile.</p></section>
    <section className="review-section" aria-labelledby="gaps-title"><h3 id="gaps-title">Gaps this plan works on</h3>
     {!plan.gaps.length && <p className="small">No gaps were identified from your evidence.</p>}
     {confirmed.length > 0 && <><h4>Confirmed gaps</h4><ul className="gap-list">{confirmed.map(gap => <GapItem key={gap.id} gap={gap} plan={plan} answer={planner.confirmations[gap.id]} frozen={frozen} confirm={confirm} />)}</ul></>}
     {unknown.length > 0 && <><h4>Unknown skills</h4><p className="small">Your evidence doesn’t show these either way.</p><ul className="gap-list">{unknown.map(gap => <GapItem key={gap.id} gap={gap} plan={plan} answer={planner.confirmations[gap.id]} frozen={frozen} confirm={confirm} />)}</ul></>}
    </section>
   </div></div>
  </details>
 </div>;
}

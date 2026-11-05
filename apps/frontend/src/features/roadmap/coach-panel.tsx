"use client";
import { useState } from 'react';
import { hours, longDate } from './settings-panel';
import { TaskItem, type Act } from './task-item';
import type { ActiveView, CheckinAnswers, CheckinView, PlanAssignment, PlannedRoadmap, Proposal, Issue } from './types';

const feelings: [CheckinAnswers['week_feel'], string][] = [['busier', 'Busier than usual'], ['as_expected', 'As expected'], ['freer', 'Freer']];
const capacities: [CheckinAnswers['next_week'], string][] = [['more', 'More'], ['same', 'The same'], ['less', 'Less']];

function Checkin({ view, act, frozen, propose, canRetry, retry, adjustTo }: { view: CheckinView; act: Act; frozen: boolean; propose: (week: string) => Promise<void>; canRetry: boolean; retry: () => void; adjustTo?: CheckinAnswers | null }) {
 const prior = adjustTo || view.answers;
 const [feel, setFeel] = useState<CheckinAnswers['week_feel'] | ''>(prior?.week_feel || ''); const [next, setNext] = useState<CheckinAnswers['next_week'] | ''>(prior?.next_week || ''); const [note, setNote] = useState(prior?.note || ''); const [problem, setProblem] = useState('');
 const { recap } = view;
 async function submit() {
  const result = await act('/planner/checkins/answer', { week_start: view.week_start, week_feel: feel, next_week: next, note: note.trim() || null });
  if (result.ok) { setProblem(''); await propose(view.week_start); } else setProblem(result.message);
 }
 return <section className="coach-card checkin" aria-labelledby="checkin-title">
  <h3 id="checkin-title">Weekly check-in</h3>
  <p className="small">Week of {longDate(view.week_start)} so far. Open until {view.expires_at.replace('T', ' ')}.</p>
  <dl className="coach-stats">
   <div><dt>Planned</dt><dd>{hours(recap.planned_minutes)}</dd></div>
   <div><dt>Completed</dt><dd>{hours(recap.completed_minutes)}</dd></div>
   <div><dt>Still scheduled</dt><dd>{hours(recap.remaining_minutes)}</dd></div>
  </dl>
  {recap.moved.length > 0 && <><h4>Moved</h4><ul>{recap.moved.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
  {recap.skipped.length > 0 && <><h4>Skipped</h4><ul>{recap.skipped.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
  <fieldset disabled={frozen}><legend>How was this week?</legend>{feelings.map(([value, label]) => <label key={value} className="coach-radio"><input type="radio" name="checkin-feel" checked={feel === value} onChange={() => setFeel(value)} />{label}</label>)}</fieldset>
  <fieldset disabled={frozen}><legend>What can next week take? It’s set to {hours(view.next_week_target_minutes)}.</legend>{capacities.map(([value, label]) => <label key={value} className="coach-radio"><input type="radio" name="checkin-next" checked={next === value} onChange={() => setNext(value)} />{label}</label>)}</fieldset>
  {next === 'same' && recap.suggest_less && <p className="coach-hint" role="status">Less than half of the work due so far is done. You might choose Less for next week. It’s your call.</p>}
  <label className="coach-note">Anything to add? (optional)<textarea maxLength={1000} disabled={frozen} value={note} onChange={event => setNote(event.target.value)} /></label>
  {view.status === 'answered' && canRetry && <p className="coach-hint" role="status">Your answers are saved, but the proposal couldn’t be prepared. Your schedule hasn’t changed.</p>}
  <div className="plan-actions">
   <button type="button" className="btn primary" disabled={frozen || !feel || !next} onClick={() => void submit()}>Save and prepare a proposal</button>
   {view.status === 'answered' && canRetry && <button type="button" className="btn ghost" disabled={frozen} onClick={retry}>Retry proposal</button>}
  </div>
  {problem && <p className="task-problem" role="alert">{problem}</p>}
 </section>;
}

function PaceWarning({ view, act, frozen }: { view: ActiveView; act: Act; frozen: boolean }) {
 const { recent } = view.pace; const late = recent.weeks_late;
 const [panel, setPanel] = useState<'add_hours' | 'move_date' | null>(null); const [extra, setExtra] = useState(1); const [date, setDate] = useState(recent.finish_date || ''); const [problem, setProblem] = useState('');
 async function request(data: Record<string, unknown>) { const result = await act('/planner/proposals/pace', data); setProblem(result.ok ? '' : result.message); if (result.ok) setPanel(null); }
 return <section className="coach-card pace" aria-labelledby="pace-title">
  <h3 id="pace-title">Recent pace</h3>
  {recent.status === 'insufficient_data' && <p className="small"><strong>Insufficient data.</strong> A recent-pace forecast needs two finished weeks. Until then, see the scheduled projection above.</p>}
  {recent.status === 'no_estimate' && <p>No finish estimate is available at your current pace, because nothing was completed in the last {recent.weeks_used} finished {recent.weeks_used === 1 ? 'week' : 'weeks'}.</p>}
  {recent.status === 'available' && recent.finish_date && <p className="small">Recent-pace forecast: about {hours(recent.weekly_minutes || 0)} a week over the last {recent.weeks_used} finished weeks finishes your accepted work by {longDate(recent.finish_date)}.</p>}
  {!!late && late > 0 && <p className="pace-late" role="status">At this pace you’ll finish {late} {late === 1 ? 'week' : 'weeks'} late.</p>}
  {(!!late && late > 0 || recent.status === 'no_estimate' || view.pace.status === 'behind') && <div className="plan-actions">
   <button type="button" className="btn ghost" disabled={frozen} onClick={() => void request({ action: 'cut_scope' })}>Cut scope</button>
   <button type="button" className="btn ghost" disabled={frozen} aria-expanded={panel === 'add_hours'} onClick={() => setPanel(panel === 'add_hours' ? null : 'add_hours')}>Add hours</button>
   <button type="button" className="btn ghost" disabled={frozen} aria-expanded={panel === 'move_date'} onClick={() => setPanel(panel === 'move_date' ? null : 'move_date')}>Move the date</button>
  </div>}
  {panel === 'add_hours' && <form className="task-form" onSubmit={event => { event.preventDefault(); void request({ action: 'add_hours', extra_minutes: Math.round(extra * 60) }); }}><label>Extra hours each week<input type="number" min={0.25} max={40} step={0.25} value={extra} onChange={event => setExtra(Number(event.target.value))} /></label><div className="task-form-actions"><button className="btn" disabled={frozen}>Preview</button></div></form>}
  {panel === 'move_date' && <form className="task-form" onSubmit={event => { event.preventDefault(); void request({ action: 'move_date', target_date: date || null }); }}><label>New target date<input type="date" value={date} onChange={event => setDate(event.target.value)} /></label><div className="task-form-actions"><button className="btn" disabled={frozen}>Preview</button></div></form>}
  {problem && <p className="task-problem" role="alert">{problem}</p>}
 </section>;
}

/** A preview of a change to this roadmap. Nothing applies until it is accepted. */
export function ProposalPanel({ proposal, blockers, act, frozen, adjust }: { proposal: Proposal; blockers: Issue[]; act: Act; frozen: boolean; adjust: (() => void) | null }) {
 const { effect } = proposal; const [kept, setKept] = useState<Record<string, boolean>>(() => Object.fromEntries(effect.decisions.map(item => [item.task_id, true])));
 const [problem, setProblem] = useState('');
 const rows: [string, string[]][] = [['Tasks moved', effect.tasks_moved], ['Sent to Backlog', effect.tasks_backlogged], ['Tasks added', effect.tasks_added], ['Tasks removed', effect.tasks_removed]];
 const finishChanged = effect.finish_before !== effect.finish_after;
 async function decide(path: string, data: Record<string, unknown>) { const result = await act(path, data); setProblem(result.ok ? '' : result.message); }
 return <section className="proposal-panel" aria-labelledby="proposal-title">
  <span className="plan-state preview">Preview: nothing changes until you accept</span>
  <h3 id="proposal-title">{effect.summary}</h3>
  {proposal.message && <p>{proposal.message}</p>}
  {blockers.map(blocker => <p className="roadmap-notice" key={blocker.code}>{blocker.message}</p>)}
  <dl className="coach-stats">
   <div><dt>Target date</dt><dd>{longDate(effect.target_after)}{effect.target_after !== effect.target_before ? ` (was ${longDate(effect.target_before)})` : ''}</dd></div>
   <div><dt>Projected finish</dt><dd>{effect.finish_after ? longDate(effect.finish_after) : 'No estimate'}{finishChanged && effect.finish_before ? ` (was ${longDate(effect.finish_before)})` : ''}</dd></div>
   <div><dt>Planned capacity left</dt><dd>{hours(effect.capacity_after_minutes)}{effect.capacity_after_minutes !== effect.capacity_before_minutes ? ` (was ${hours(effect.capacity_before_minutes)})` : ''}</dd></div>
   {effect.workload_after_minutes != null && <div><dt>Next week’s workload</dt><dd>{hours(effect.workload_after_minutes)}{effect.workload_before_minutes !== effect.workload_after_minutes ? ` (was ${hours(effect.workload_before_minutes || 0)})` : ''}</dd></div>}
  </dl>
  {effect.uses_buffer && <p className="coach-hint">This uses part of next week’s reserved buffer.</p>}
  {effect.add_block_suggested && <p className="coach-hint">That’s more than your study blocks hold. Add a study block with Edit plan to fit more.</p>}
  {effect.warnings.map((warning, i) => <p className="coach-hint" key={i}>{warning}</p>)}
  {rows.filter(([, items]) => items.length).map(([label, items]) => <div key={label}><h4>{label}</h4><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}
  {effect.decisions.length > 0 && <fieldset className="proposal-decisions" disabled={frozen}><legend>Your pinned and custom tasks that week</legend>
   {effect.decisions.map(item => <div key={item.task_id} className="proposal-decision"><p>{item.title} · {longDate(item.date)}, {item.start_time}</p><label className="coach-radio"><input type="radio" name={`keep-${item.task_id}`} checked={kept[item.task_id]} onChange={() => setKept({ ...kept, [item.task_id]: true })} />Keep it as an exception</label><label className="coach-radio"><input type="radio" name={`keep-${item.task_id}`} checked={!kept[item.task_id]} onChange={() => setKept({ ...kept, [item.task_id]: false })} />Move it to Backlog to place myself</label></div>)}
  </fieldset>}
  <div className="plan-actions">
   <button type="button" className="btn primary" disabled={frozen || blockers.length > 0} onClick={() => void decide('/planner/proposals/accept', { proposal_id: proposal.id, keep_task_ids: Object.keys(kept).filter(key => kept[key]) })}>Accept changes</button>
   {adjust && <button type="button" className="btn ghost" disabled={frozen} onClick={adjust}>Adjust answers</button>}
   <button type="button" className="btn ghost" disabled={frozen} onClick={() => void decide('/planner/proposals/discard', { proposal_id: proposal.id })}>Discard</button>
  </div>
  {problem && <p className="task-problem" role="alert">{problem}</p>}
 </section>;
}

export function CoachPanel({ plan, view, tasks, act, frozen, propose, retryCheckin, canRetryCheckin, retryRolling, adjusting, running }: { plan: PlannedRoadmap; view: ActiveView; tasks: Map<string, PlanAssignment>; act: Act; frozen: boolean; propose: (week: string) => Promise<void>; retryCheckin: () => void; canRetryCheckin: boolean; retryRolling: () => void; adjusting: boolean; running: boolean }) {
 const { coach, rolling, checkin } = view;
 const [problem, setProblem] = useState('');
 const showCheckin = checkin && (checkin.status !== 'proposed' || adjusting);
 return <section className="coach-panel" aria-labelledby="coach-title">
  <h2 id="coach-title">Coach</h2>
  {coach.messages.length > 0 && <ul className="coach-messages">{coach.messages.map((message, i) => <li key={i}>{message}</li>)}</ul>}
  {coach.notices.map((notice, i) => <p className="roadmap-notice" key={i}>{notice}</p>)}
  {rolling.status === 'running' && <p className="roadmap-notice" role="status">Planning your next tasks. Your saved tasks stay as they are.</p>}
  {rolling.status === 'needed' && !running && <p className="roadmap-notice" role="status">Your next tasks will be planned when you next open this page.</p>}
  {rolling.status === 'unavailable' && <p className="roadmap-notice">Your next tasks can’t be planned right now because the adviser is unavailable. You can still add your own.</p>}
  {rolling.status === 'failed' && <div className="roadmap-notice" role="status"><p>Your next tasks couldn’t be planned: {rolling.error || 'please try again.'} Your saved tasks are unchanged.</p>{!!rolling.retry_after && <p>Provider capacity: retry in {rolling.retry_after} seconds.</p>}<button type="button" className="btn" disabled={frozen || !!rolling.retry_after} onClick={retryRolling}>Retry planning</button></div>}
  {showCheckin && <Checkin key={`${checkin.week_start}:${checkin.status}`} view={checkin} act={act} frozen={frozen} propose={propose} canRetry={canRetryCheckin} retry={retryCheckin} />}
  <PaceWarning view={view} act={act} frozen={frozen} />
  {coach.action_needed_task_ids.length > 0 && <section className="coach-card" aria-labelledby="action-title"><h3 id="action-title">Needs your decision</h3><ul className="task-list">{coach.action_needed_task_ids.map(id => tasks.get(id) && <TaskItem key={id} task={tasks.get(id)!} milestone={plan.milestones.find(m => m.key === tasks.get(id)!.milestone_key)} act={act} frozen={frozen} />)}</ul></section>}
  {coach.recent_moves.length > 0 && <section className="coach-card" aria-labelledby="moves-title"><h3 id="moves-title">Recent automatic moves</h3><ul className="coach-moves">{coach.recent_moves.map(event => <li key={event.id}><span><strong>{tasks.get(event.task_id || '')?.task || 'Task'}</strong> {event.message}</span><button type="button" className="btn ghost" disabled={frozen} aria-label={`Undo: ${event.message}`} onClick={async () => { const result = await act('/planner/events/undo', { event_id: event.id }); setProblem(result.ok ? '' : result.message); }}>Undo</button></li>)}</ul>{problem && <p className="task-problem" role="alert">{problem} You can place it with Move.</p>}</section>}
 </section>;
}

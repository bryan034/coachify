"use client";
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import { useEffect, useRef, useState, type FormEvent, type ReactNode, type KeyboardEvent } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { useChatScroll, ChatScrollControl } from '@/features/career/use-chat-scroll';
import { roadmapApi, RoadmapError } from '@/lib/api/roadmap';
import type { Workspace, MessageRequest, Plan, Preferences, Task, TaskDefinition, Assessment } from './types';
import '@/styles/roadmap.css';

const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const hours = (minutes: number) => `${Number((minutes / 60).toFixed(2))} h`;
const explanation = (error: unknown) => error instanceof Error ? error.message : 'Your saved work could not be confirmed. Retry to recover it.';
const definition = (task: Task): TaskDefinition => ({ id: task.id, title: task.title, instructions: task.instructions, completion_outcome: task.completion_outcome, estimated_minutes: task.estimated_minutes, rationale: task.rationale, requirement_refs: task.requirement_refs, prerequisites: task.prerequisites, milestone: task.milestone, splittable: task.splittable });

export function RoadmapPlanner() {
 const { account, token } = useProfile();
 if (!account || !token) return null;
 return <Planner key={`${account.id}:${token}`} token={token} />;
}
function Planner({ token }: { token: string }) {
 const [workspace, setWorkspace] = useState<Workspace | null>(null);
 const [text, setText] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
 const [partial, setPartial] = useState(false); const [tab, setTab] = useState<'plan' | 'assessment'>('plan');
 const [preferences, setPreferences] = useState(false); const [editing, setEditing] = useState<Task | null>(null); const [adding, setAdding] = useState(false);
 const [pending, setPending] = useState<MessageRequest | null>(null); const [confirmRemove, setConfirmRemove] = useState<Task | null>(null);
 const mounted = useRef(true); const latest = useRef<Workspace | null>(null); const sequence = useRef(0); const { transcript, showJump, jumpToLatest, scrollProps } = useChatScroll();
 const pendingRef = useRef<MessageRequest | null>(null);
 const unknownMutation = useRef<{ path: string; body: unknown } | null>(null); const [unknown, setUnknown] = useState(false);
 useEffect(() => { mounted.current = true; return () => { mounted.current = false; sequence.current++; }; }, []);
 function receive(value: Workspace) { if (mounted.current) { latest.current = value; setWorkspace(value); } }
 async function load(signal?: AbortSignal) {
  const order = ++sequence.current;
  try { const value = await roadmapApi<Workspace>('/workspace', token, undefined, signal); if (mounted.current && order === sequence.current) { receive(value); setError(''); if (pendingRef.current && value.operation?.id === pendingRef.current.mutation_id) { pendingRef.current = null; setPending(null); } } }
  catch (failure) { if (mounted.current && !signal?.aborted && order === sequence.current) setError(explanation(failure)); }
 }
 useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); /* account/token remounts this component */ }, []); // eslint-disable-line react-hooks/exhaustive-deps
 const running = workspace?.operation?.status === 'pending' || workspace?.operation?.status === 'running';
 useEffect(() => {
  if (!running && !(workspace?.operation?.retry_after && workspace.operation.retry_after > 0)) return;
  const timer = setTimeout(async () => {
   const order = ++sequence.current;
   try {
    const progress = await roadmapApi<Pick<Workspace, 'version' | 'operation'>>('/progress', token);
    if (!mounted.current || order !== sequence.current || !latest.current) return;
    const current = latest.current;
    if (!['pending', 'running'].includes(progress.operation?.status || '') && (progress.version !== current.version || progress.operation?.status !== current.operation?.status)) await load();
    else receive({ ...current, version: progress.version, operation: progress.operation });
   } catch (failure) { if (mounted.current && order === sequence.current) setError(explanation(failure)); }
  }, 1500);
  return () => clearTimeout(timer);
 }, [workspace, running]); // eslint-disable-line react-hooks/exhaustive-deps
 async function send(request?: MessageRequest) {
  const value = request || { expected_version: latest.current!.version, mutation_id: crypto.randomUUID(), message: text.trim(), allow_partial_assessment: partial };
  if (!value.message || busy || running) return;
  setBusy(true); setError(''); setPending(value); pendingRef.current = value; if (!request) setText(''); sequence.current++;
  try { await roadmapApi('/messages', token, value); if (mounted.current) { setPending(null); pendingRef.current = null; await load(); } }
  catch (failure) { if (mounted.current) setError(explanation(failure)); }
  finally { if (mounted.current) setBusy(false); }
 }
 async function change(path: string, data: Record<string, unknown>, retry = false) {
  if (busy || running || !latest.current) return;
  const call = retry && unknownMutation.current ? unknownMutation.current : { path, body: { ...data, expected_version: latest.current.version, mutation_id: crypto.randomUUID() } };
  unknownMutation.current = call; setBusy(true); setError(''); sequence.current++;
  try { const value = await roadmapApi<Workspace>(call.path, token, call.body); if (mounted.current) { receive(value); unknownMutation.current = null; setUnknown(false); setEditing(null); setAdding(false); setPreferences(false); setConfirmRemove(null); } }
  catch (failure) { if (mounted.current) { setError(explanation(failure)); const uncertain = !(failure instanceof RoadmapError) || failure.status >= 500; setUnknown(uncertain); if (!uncertain) unknownMutation.current = null; } }
  finally { if (mounted.current) setBusy(false); }
 }
 if (!workspace) return <section className="roadmap-adviser"><h1>Roadmap</h1><p role={error ? 'alert' : 'status'}>{error || 'Loading your planning conversation…'}</p>{error && <button className="btn" onClick={() => void load()}>Retry loading</button>}</section>;
 const { context, active, draft, assessment } = workspace; const plan = draft || active; const frozen = busy || running || !!error || unknown || !!pending || !!workspace.operation?.retry_after;
 const validResearch = ['available', 'no_findings'].includes(context.research_coverage || '');
 return <section className="roadmap-adviser">
  <header className="roadmap-heading"><div><h1>Roadmap</h1><p>Make room for the career you want.</p></div><div className="roadmap-goal">{context.goal?.role || assessment?.role || 'Choose your direction'}{context.cv?.name && <span>Using {context.cv.name}</span>}</div></header>
  {error && <div className="roadmap-notice" role="alert"><p>{error}</p><button className="btn ghost" disabled={busy} onClick={() => void load()}>Reload saved work</button>{pending && <button className="btn" disabled={busy || running} onClick={() => void send(pending)}>Recover sent message</button>}{unknown && <button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button>}</div>}
  {pending && !busy && !error && <div className="roadmap-notice"><p>The sent message is awaiting confirmation.</p><button className="btn" disabled={running} onClick={() => void send(pending)}>Recover sent message</button></div>}
  {unknown && !error && <div className="roadmap-notice"><p>The previous change is awaiting confirmation.</p><button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button></div>}
  {context.availability === 'unavailable' && <div className="roadmap-notice"><p>We can’t check your latest CV and Career goal right now. Your saved plan and conversation are still here; new advice and plan activation need this check.</p><button className="btn ghost" onClick={() => void load()}>Retry source check</button></div>}
  {!context.ready && context.availability !== 'unavailable' && <div className="roadmap-prerequisites"><h2>Bring your starting point and direction</h2><p>Your adviser needs your extracted CV and Career goal to personalise the conversation.</p>{context.issues.map(issue => <div key={issue.source}><p>{issue.message}</p><Link className="btn ghost" href={issue.href}>Open {issue.source === 'cv' ? 'CV' : 'Career Goal'}</Link></div>)}</div>}
  {workspace.stale && <div className="roadmap-notice"><p>Your CV or goal has changed. Your saved plan is still here; discuss a revision before treating it as current advice.</p></div>}
  <div className="roadmap-workspace">
   <section className="adviser-conversation" aria-label="Career adviser conversation">
    <div className="adviser-intro"><div className="adviser-avatar" aria-hidden="true">C</div><div><h2>Your career adviser</h2><p>A plan we can keep shaping together.</p></div></div>
    <div ref={transcript} {...scrollProps} className="adviser-messages" role="log" aria-label="Saved planning messages" aria-live="polite">
     {!workspace.messages.length && <div className="adviser-opening"><h3>What would a manageable week look like?</h3><p>Tell me when you would like to be ready, how much time you can spend, and which days suit you. We’ll work out useful next steps from your experience.</p>{context.planning_defaults.weekly_hours != null && <p>You previously saved {context.planning_defaults.weekly_hours} hours a week. We can use that as a starting point or choose a different pace.</p>}{context.goal?.job_dates?.map((date, i) => <p key={i}>{date.kind.replaceAll('_', ' ')}: <strong>{date.text}</strong>. We can discuss a preparation target around this.</p>)}<div className="adviser-starters">{['Help me choose what to focus on first.', 'I want a practical, project-based plan.', 'Help me find a realistic weekly pace.'].map(prompt => <button key={prompt} disabled={!context.ready || busy} onClick={() => setText(prompt)}>{prompt}</button>)}</div></div>}
     {workspace.messages.map(message => <article key={message.id} className={`adviser-message ${message.role}`}><span>{message.role === 'assistant' ? 'elo' : 'You'}</span><ReactMarkdown components={{ img: () => null, a: ({ children }) => <span>{children}</span> }}>{message.content}</ReactMarkdown></article>)}
     {running && <p role="status" className="adviser-working">Reviewing your evidence and preparing advice… You can keep drafting your next message.</p>}
     {workspace.operation?.status === 'failed' && <div className="roadmap-notice"><p>{workspace.operation.error?.detail || 'This response could not finish. Your message is saved.'}</p>{!!workspace.operation.retry_after && <p role="status">Provider capacity: retry in {workspace.operation.retry_after} seconds.</p>}{workspace.retry_request && <button className="btn" disabled={busy || !!error || !context.ready || !context.model_available || !!workspace.operation?.retry_after} onClick={() => void send(workspace.operation?.error?.code === 'inputs_changed' ? { ...workspace.retry_request!, expected_version: workspace.version, mutation_id: crypto.randomUUID() } : workspace.retry_request!)}>{workspace.operation?.error?.code === 'inputs_changed' ? 'Retry with current inputs' : 'Retry saved message'}</button>}</div>}

    </div>
    <ChatScrollControl visible={showJump} onClick={jumpToLatest} />
    <form className="adviser-composer" onSubmit={(event: FormEvent) => { event.preventDefault(); void send(); }}>
     {!validResearch && context.ready && <label className="roadmap-partial"><input type="checkbox" checked={partial} onChange={event => setPartial(event.target.checked)} />Continue with available evidence. Interview research is {context.research_coverage || 'unavailable'}; advice will be labelled partial.</label>}
     {!context.model_available && <p className="small">Your adviser is unavailable. Your saved plan remains available.</p>}
     <label htmlFor="adviser-message">Talk through your plan</label><textarea id="adviser-message" rows={3} maxLength={4000} value={text} disabled={!context.ready} onChange={event => setText(event.target.value)} placeholder="I can do six hours a week, mostly on Saturdays…" />
     <div><span className="small">Suggestions are yours to change.</span><button className="btn primary" disabled={!text.trim() || !context.ready || !context.model_available || frozen || (!validResearch && !partial)}>Send message</button></div>
    </form>
   </section>
   <aside className="adviser-plan" aria-label="Your plan">
    <div className="roadmap-tabs" role="tablist" aria-label="Planning detail"><button id="plan-tab" role="tab" aria-selected={tab === 'plan'} aria-controls="plan-panel" onClick={() => setTab('plan')}>Your plan</button><button id="assessment-tab" role="tab" aria-selected={tab === 'assessment'} aria-controls="assessment-panel" onClick={() => setTab('assessment')}>Starting point</button></div>
    <div id="plan-panel" role="tabpanel" aria-labelledby="plan-tab" hidden={tab !== 'plan'}>
     {plan ? <>
      <div className="plan-summary"><span className="plan-state">{draft ? 'Proposed changes' : 'Your active plan'}</span><h2>{draft ? 'Does this work for you?' : 'A pace you can build on'}</h2><p>{plan.preferences.weekly_minutes == null ? 'Choose your weekly time budget' : `${hours(plan.preferences.weekly_minutes)} per week`}{plan.preferences.target_date ? ` · Ready-by target ${plan.preferences.target_date}` : plan.preferences.horizon_weeks ? ` · ${plan.preferences.horizon_weeks}-week horizon` : ''}</p><p className="small">Effort is estimated. Daily work has no fixed clock times.</p>
       <button className="btn ghost" disabled={frozen} onClick={() => setPreferences(true)}>Adjust time and days</button>
       {draft && <div className="plan-actions"><button className="btn primary" disabled={frozen || !context.ready || plan.schedule.status === 'needs_preferences'} onClick={() => void change('/activate', {})}>{active ? 'Apply these changes' : 'Start this plan'}</button><button className="btn ghost" disabled={frozen} onClick={() => void change('/draft/discard', {})}>Discard proposal</button></div>}
      </div>
      <p className="plan-feasibility">{({ feasible: 'The estimated work fits the selected availability.', partial: 'Some work remains unscheduled. We can discuss the trade-offs.', needs_preferences: 'Let’s agree on your timeline and available days.', no_work: 'No unfinished activities in this plan.', review_needed: 'Your edits or progress need a schedule review.' } as Record<string, string>)[plan.schedule.status] || plan.schedule.status}</p>
      {plan.schedule.issues.length > 0 && <details className="plan-explanation"><summary>Planning details ({plan.schedule.issues.length})</summary><ul>{plan.schedule.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul></details>}
      {plan.unaddressed_requirements && plan.unaddressed_requirements.length > 0 && <details className="plan-explanation"><summary>Other development opportunities ({plan.unaddressed_requirements.length})</summary><p>These priorities are outside the proposed activities. We can discuss whether to include them.</p><ul>{plan.unaddressed_requirements.map(ref => <li key={ref}>{[...plan.assessment.job_skill_gaps, ...plan.assessment.interview_prep_gaps].find(r => r.ref === ref)?.name || ref}</li>)}</ul></details>}
      {plan.exclusions?.length > 0 && <details className="plan-explanation"><summary>Your scope choices</summary>{plan.exclusions.map(e => <p key={e.requirement_ref}>{e.reason}</p>)}</details>}
      <Schedule plan={plan} />
      <div className="plan-task-heading"><h3>Your activities</h3>{active && !draft && <button className="btn ghost" disabled={frozen} onClick={() => setAdding(true)}>Add activity</button>}</div>
      {plan.tasks.filter(task => !task.removed).map(task => <details key={task.id} className={`plan-task ${task.status}`}><summary><span>{task.title}<small>{hours(task.estimated_minutes)} estimated · {task.status.replaceAll('_', ' ')}</small></span></summary><p>{task.instructions}</p><h4>Done when</h4><p>{task.completion_outcome}</p><h4>Why this activity</h4><p>{task.rationale}</p>{task.definition_review_required && <p className="roadmap-notice">The definition changed. Earlier completion does not cover the new outcome.</p>}{task.requirement_refs.length > 0 && <p className="small">Linked to: {task.requirement_refs.map(ref => [...plan.assessment.job_skill_gaps, ...plan.assessment.interview_prep_gaps, ...plan.assessment.constraints].find(r => r.ref === ref)?.name || 'Historical requirement').join(', ')}</p>}{task.prerequisites.length > 0 && <p className="small">Builds on: {task.prerequisites.map(id => plan.tasks.find(t => t.id === id)?.title || 'Removed prerequisite').join(', ')}</p>}
       {!draft && <div className="plan-task-actions">{task.status === 'not_started' && <button className="btn" disabled={frozen} onClick={() => void change('/tasks/status', { task_id: task.id, status: 'in_progress' })}>Start</button>}{task.status !== 'completed' ? <button className="btn" disabled={frozen} onClick={() => void change('/tasks/status', { task_id: task.id, status: 'completed' })}>Mark complete</button> : <><button className="btn" disabled={frozen} onClick={() => void change('/tasks/status', { task_id: task.id, status: 'not_started' })}>Reopen as not started</button><button className="btn" disabled={frozen} onClick={() => void change('/tasks/status', { task_id: task.id, status: 'in_progress' })}>Resume work</button></>}<button className="btn ghost" disabled={frozen} onClick={() => setEditing(task)}>Edit</button><button className="btn ghost" disabled={frozen} onClick={() => setConfirmRemove(task)}>Remove</button></div>}
      </details>)}
      {!plan.tasks.some(t => !t.removed) && <p className="plan-empty">No activities chosen yet. Tell your adviser what you would like to work on.</p>}
      {plan.schedule.milestones?.length > 0 && <div className="plan-milestones"><h3>Milestones</h3>{plan.schedule.milestones.map(m => <div key={m.name}><strong>{m.name}</strong><span>{m.status.replaceAll('_', ' ')}{m.target_date ? ` · ${m.target_date}` : ''}</span></div>)}</div>}
     </> : <div className="plan-empty"><h2>Room for your next steps</h2><p>As we discuss your goal, proposed activities and a weekly rhythm will appear here. You can shape the details before starting.</p></div>}
    </div>
    <div id="assessment-panel" role="tabpanel" aria-labelledby="assessment-tab" hidden={tab !== 'assessment'}><AssessmentView assessment={assessment} /></div>
   </aside>
  </div>
  {preferences && plan && <PreferencesEditor key={plan.id} plan={plan} busy={busy} save={value => void change('/preferences', { preferences: value })} cancel={() => setPreferences(false)} />}
  {(editing || adding) && active && <TaskEditor key={editing?.id || 'new'} task={editing} plan={active} busy={busy} save={value => void change('/tasks', { task: value, base_definition: editing ? definition(editing) : null })} cancel={() => { setEditing(null); setAdding(false); }} />}
  {confirmRemove && <Dialog onClose={() => setConfirmRemove(null)}><section className="roadmap-dialog" role="dialog" aria-modal="true" aria-labelledby="remove-title"><h2 id="remove-title">Remove {confirmRemove.title}?</h2><p>Its history will remain. Dependent activities and milestones may need review.</p><button className="btn" disabled={busy} onClick={() => void change('/tasks/remove', { task_id: confirmRemove.id })}>Remove activity</button><button className="btn ghost" onClick={() => setConfirmRemove(null)}>Cancel</button></section></Dialog>}
 </section>;
}

function Schedule({ plan }: { plan: Plan }) {
 const [view, setView] = useState<'day' | 'week' | 'month'>('week');
 const [focus, setFocus] = useState(() => { const today = new Intl.DateTimeFormat('en-CA', { timeZone: plan.preferences.time_zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); const first = plan.schedule.allocations.map(a => a.date).sort()[0]; return first && today < first ? first : today; });
 const dates = [...new Set(plan.schedule.allocations.filter(a => plan.tasks.some(t => t.id === a.task_id && !t.removed && t.status !== 'completed')).map(a => a.date))].sort();
 const date = new Date(`${focus}T12:00:00Z`); const day = (date.getUTCDay() + 6) % 7; const monday = new Date(date); monday.setUTCDate(monday.getUTCDate() - day);
 const weekEnd = new Date(monday); weekEnd.setUTCDate(weekEnd.getUTCDate() + 7);
 const filtered = dates.filter(d => view === 'day' ? d === focus : view === 'month' ? d.slice(0, 7) === focus.slice(0, 7) : d >= monday.toISOString().slice(0, 10) && d < weekEnd.toISOString().slice(0, 10));
 return <section className="daily-schedule" aria-label="Daily workload"><div className="schedule-controls"><h3>Your rhythm</h3><label>View<select value={view} onChange={e => setView(e.target.value as typeof view)}><option value="day">Day</option><option value="week">Week</option><option value="month">Month</option></select></label><label>Focus date<input type="date" required value={focus} onChange={e => { if (e.target.value) setFocus(e.target.value); }} /></label></div>{filtered.length === 0 && <div><p className="small">No activities allocated in this period.</p>{dates.length > 0 && <button className="btn ghost" onClick={() => setFocus(dates[0])}>First planned day</button>}</div>}{filtered.map(date => { const segments = plan.schedule.allocations.filter(a => a.date === date && plan.tasks.some(t => t.id === a.task_id && !t.removed && t.status !== 'completed')); return <div className="schedule-day" key={date}><div><strong>{new Date(`${date}T12:00:00Z`).toLocaleDateString('en-SG', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })}</strong><span>{hours(segments.reduce((sum, a) => sum + a.minutes, 0))}</span></div>{segments.map(a => <p key={`${a.task_id}:${a.order}`}><span>{plan.tasks.find(t => t.id === a.task_id)?.title}</span><span>{a.minutes} min</span></p>)}</div>; })}{Object.values(plan.schedule.remainders).some(n => n > 0) && <p className="small">Unscheduled: {hours(Object.values(plan.schedule.remainders).reduce((sum, n) => sum + n, 0))}. Ask the adviser to help find a workable adjustment.</p>}</section>;
}
function AssessmentView({ assessment }: { assessment: Assessment | null }) {
 if (!assessment) return <div className="plan-empty"><h2>Advice grounded in your experience</h2><p>Your first planning message starts the comparison of your selected CV and Career goal. Findings and their limitations will appear here.</p></div>;
 return <div className="assessment-view"><h2>Your starting point</h2><p>Based on declared evidence for {assessment.role}.</p><p className="small">Interview coverage: {assessment.research_coverage.replaceAll('_', ' ')}</p>{assessment.groups?.map(group => <details key={group.id}><summary>{group.operator === 'any' ? 'Alternative routes' : 'Combined conditions'}<small>{group.match_status.replaceAll('_', ' ')}</small></summary><p>{group.operator === 'any' ? 'One supported permitted route satisfies this group. Unused alternatives are not mandatory work.' : 'All required conditions contribute to this group. Known support, shortfalls and uncertainty remain separate below.'}</p><ul>{group.requirement_refs.map(ref => <li key={ref}>{[...assessment.job_skill_gaps, ...assessment.constraints].find(r => r.ref === ref)?.name || 'Historical requirement'}</li>)}</ul></details>)}{([['Role requirements', assessment.job_skill_gaps], ['Interview preparation', assessment.interview_prep_gaps], ['Other conditions', assessment.constraints]] as const).map(([label, items]) => <section key={label}><h3>{label}</h3>{!items.length && <p className="small">No findings in this group. Coverage limitations still apply.</p>}{items.map(item => <details key={item.ref}><summary>{item.name}<small>{item.match_status.replaceAll('_', ' ')}</small></summary>{(item.evidence || item.description) && <blockquote>{item.evidence || item.description}</blockquote>}{item.priority && <p className="small">Importance: {item.priority}{item.origin ? ` · ${item.origin.replaceAll('_', ' ')}` : ''}</p>}{item.components.map((c, i) => <p key={i}><strong>{c.dimension.replaceAll('_', ' ')}: {c.status.replaceAll('_', ' ')}</strong><br />{c.explanation}{c.evidence_refs.map(ref => assessment.evidence?.[ref] && <span className="assessment-evidence" key={ref}><strong>{assessment.evidence[ref].name || 'Saved declaration'}</strong>: {assessment.evidence[ref].text}</span>)}</p>)}{item.recommendation && <p>{item.recommendation}</p>}</details>)}</section>)}</div>;
}

function PreferencesEditor({ plan, busy, save, cancel }: { plan: Plan; busy: boolean; save: (p: Preferences) => void; cancel: () => void }) {
 const [value, setValue] = useState<Preferences>(plan.preferences); const [issue, setIssue] = useState('');
 const total = value.days.reduce((sum, day) => sum + day.minutes, 0);
 function submit(e: FormEvent) { e.preventDefault(); if (!value.start_date || (!value.target_date && !value.horizon_weeks) || !value.days.length || value.weekly_minutes == null || total > value.weekly_minutes) { setIssue('Choose a start, target or horizon, and days within your weekly budget.'); return; } save(value); }
 return <Dialog onClose={cancel}><form className="roadmap-dialog" role="dialog" aria-modal="true" aria-labelledby="preferences-title" onSubmit={submit}><h2 id="preferences-title">A week that works for you</h2><p>Changes create a proposal you can review beside the conversation.</p><label>Start preparing<input type="date" required value={value.start_date || ''} onChange={e => setValue({ ...value, start_date: e.target.value })} /></label><label>Ready-by target (optional)<input type="date" value={value.target_date || ''} min={value.start_date || undefined} onChange={e => setValue({ ...value, target_date: e.target.value || null })} /></label>{!value.target_date && <label>Ongoing planning horizon in weeks<input type="number" required min={1} max={52} value={value.horizon_weeks || ''} onChange={e => setValue({ ...value, horizon_weeks: Number(e.target.value) })} /></label>}<label>Weekly budget in hours<input type="number" required min={0} max={168} step="any" value={value.weekly_minutes == null ? '' : value.weekly_minutes / 60} onChange={e => setValue({ ...value, weekly_minutes: Number(e.target.value) * 60 })} /></label><fieldset><legend>Preferred days and hours</legend>{days.map((day, index) => { const selected = value.days.find(d => d.day === index); return <div className="day-budget" key={day}><label><input type="checkbox" checked={!!selected} onChange={e => setValue({ ...value, days: e.target.checked ? [...value.days, { day: index, minutes: 60 }] : value.days.filter(d => d.day !== index) })} />{day}</label>{selected && <label><span className="sr-only">{day} hours</span><input aria-label={`${day} hours`} type="number" min={0} max={24} step="any" value={selected.minutes / 60} onChange={e => setValue({ ...value, days: value.days.map(d => d.day === index ? { ...d, minutes: Number(e.target.value) * 60 } : d) })} /></label>}</div>; })}<p>{hours(total)} chosen each week</p></fieldset><label>Comfortable session length in minutes<input type="number" min={1} max={1440} step={1} value={value.max_session_minutes} onChange={e => setValue({ ...value, max_session_minutes: Number(e.target.value) })} /></label><label>How do you like to learn?<textarea maxLength={2000} value={value.learning_preferences} onChange={e => setValue({ ...value, learning_preferences: e.target.value })} /></label>{issue && <p role="alert">{issue}</p>}<div className="plan-actions"><button className="btn primary" disabled={busy}>Preview schedule</button><button type="button" className="btn ghost" onClick={cancel}>Cancel</button></div></form></Dialog>;
}
function TaskEditor({ task, plan, busy, save, cancel }: { task: Task | null; plan: Plan; busy: boolean; save: (t: TaskDefinition) => void; cancel: () => void }) {
 const [value, setValue] = useState<TaskDefinition>(() => task ? definition(task) : { id: crypto.randomUUID(), title: '', instructions: '', completion_outcome: '', estimated_minutes: 60, rationale: '', requirement_refs: [], prerequisites: [], milestone: '', splittable: true });
 const refs = [...plan.assessment.job_skill_gaps, ...plan.assessment.interview_prep_gaps, ...plan.assessment.constraints];
 return <Dialog onClose={cancel}><form className="roadmap-dialog" role="dialog" aria-modal="true" aria-labelledby="task-editor-title" onSubmit={e => { e.preventDefault(); save(value); }}><h2 id="task-editor-title">{task ? 'Shape this activity' : 'Add your own activity'}</h2>{(['title', 'instructions', 'completion_outcome', 'rationale', 'milestone'] as const).map(key => <label key={key}>{({ title: 'Activity', instructions: 'What will you do?', completion_outcome: 'How will you know it is done?', rationale: 'Why does this matter to you?', milestone: 'Milestone (optional)' })[key]}<textarea required={key !== 'milestone'} maxLength={key === 'title' || key === 'milestone' ? 160 : 4000} value={value[key]} onChange={e => setValue({ ...value, [key]: e.target.value })} /></label>)}<label>Estimated effort in minutes<input type="number" required min={1} max={60000} step={1} value={value.estimated_minutes} onChange={e => setValue({ ...value, estimated_minutes: Number(e.target.value) })} /></label><label><input type="checkbox" checked={value.splittable} onChange={e => setValue({ ...value, splittable: e.target.checked })} />Can be split over several sessions</label><label>Related requirements (optional; otherwise personal development)<select multiple value={value.requirement_refs} onChange={e => setValue({ ...value, requirement_refs: Array.from(e.target.selectedOptions, o => o.value) })}>{refs.map(r => <option key={r.ref} value={r.ref}>{r.name}</option>)}</select></label><label>Builds on these activities<select multiple value={value.prerequisites} onChange={e => setValue({ ...value, prerequisites: Array.from(e.target.selectedOptions, o => o.value) })}>{plan.tasks.filter(t => t.id !== value.id && !t.removed).map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label><p className="small">Saving an estimate or definition keeps the existing schedule and shows any conflicts for review.</p><div className="plan-actions"><button className="btn primary" disabled={busy}>Save activity</button><button className="btn ghost" type="button" onClick={cancel}>Cancel</button></div></form></Dialog>;
}

function Dialog({ children, onClose }: { children: ReactNode; onClose: () => void }) {
 const root = useRef<HTMLDivElement>(null); const close = useRef(onClose); close.current = onClose;
 useEffect(() => { const previous = document.activeElement as HTMLElement | null; root.current?.querySelector<HTMLElement>('input,textarea,select,button')?.focus(); return () => previous?.focus(); }, []);
 function keyboard(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key === 'Escape') { event.preventDefault(); close.current(); }
  if (event.key !== 'Tab') return;
  const elements = Array.from(root.current?.querySelectorAll<HTMLElement>('input:not([disabled]),textarea:not([disabled]),select:not([disabled]),button:not([disabled]),[tabindex="0"]') || []);
  const first = elements[0], last = elements.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
 }
 return <div className="roadmap-dialog-backdrop" ref={root} onKeyDown={keyboard}>{children}</div>;
}

"use client";
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import { roadmapApi, RoadmapError } from '@/lib/api/roadmap';
import { useComparison, COMPARISON_REFRESH } from '@/features/assessment/comparison';
import { EvaluationStatusPanel } from '@/features/assessment/evaluation-status';
import { EvidenceProposals } from './evidence-proposals';
import { AdviserChat } from './adviser-chat';
import { RoadmapViews, skillCatalog } from './roadmap-views';
import { PlanPreview } from './plan-preview';
import { planSessions } from './roadmap-day';
import type { RoadmapActions } from './day-list';
import { SettingsPanel, useSettingsDraft, type AutosaveState } from './settings-panel';
import type { BacklogPlan, Context, FreeTimes, Workspace, MessageRequest, PlannerConfig } from './types';
import '@/styles/roadmap.css';
import '@/styles/evaluate.css';
import { errorText, friendlyOperationError } from '@/lib/errors';
import { loadSkills, useSection } from '@/lib/api/workspace-summary';
import { PageSkeleton } from '@/components/ui/workspace-ui';
import { ProcessingCard, SkeletonRoad, type ProcessingStep } from '@/components/ui/processing-card';

const explanation = (error: unknown) => errorText(error, 'Your saved work could not be confirmed. Retry to recover it.');

export function RoadmapPlanner() {
 const { account, token } = useProfile();
 if (!account || !token) return null;
 return <Planner key={`${account.id}:${token}`} token={token} />;
}
function workspacePath() {
 try { return `/workspace?time_zone=${encodeURIComponent(deviceTimeZone())}`; } catch { return '/workspace'; }
}
function Planner({ token }: { token: string }) {
 const [workspace, setWorkspace] = useState<Workspace | null>(null);
 const profileSkills = useSection(loadSkills, token);
 const evaluation = useComparison(token);
 const [text, setText] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
 const [partial, setPartial] = useState(true);
 const [helperOpen, setHelperOpen] = useState(()=>typeof window!=='undefined'&&new URLSearchParams(window.location.search).get('chat')==='1'); const launcher = useRef<HTMLButtonElement>(null);
 const helperDismissed = useRef(false); const helperTakesFocus = useRef(true);
 const [configuring, setConfiguring] = useState(false);
 const [pending, setPending] = useState<MessageRequest | null>(null);
 const mounted = useRef(true); const latest = useRef<Workspace | null>(null); const sequence = useRef(0);
 const pendingRef = useRef<MessageRequest | null>(null);
 const unknownMutation = useRef<{ path: string; body: unknown } | null>(null); const [unknown, setUnknown] = useState(false);
 const idle = useRef(false);
 const settings = useSettingsDraft(workspace, token);
 const [autosave, setAutosave] = useState<AutosaveState>('idle');
 const saving = useRef<Promise<void> | null>(null); const draftRef = useRef<PlannerConfig | null>(null); const unsafeDraft = useRef(false);
 draftRef.current = settings.draft; unsafeDraft.current = !!settings.previewError;
 useEffect(() => { mounted.current = true; return () => { mounted.current = false; sequence.current++; }; }, []);
 function receive(value: Workspace) {
  if (!mounted.current) return;
  // Choose the view in the same update as the new preview. A later effect can
  // otherwise override a Back click made just after the preview appears.
  const candidateId = value.planner.candidate?.id;
  if (candidateId && candidateId !== latest.current?.planner.candidate?.id) {
   setConfiguring(false); setHelperOpen(false);
  }
  latest.current = value; setWorkspace(value);
 }
 async function load(signal?: AbortSignal) {
  const order = ++sequence.current;
  try { const value = await roadmapApi<Workspace>(workspacePath(), token, undefined, signal); if (mounted.current && order === sequence.current) { receive(value); setError(''); if (pendingRef.current && value.operation?.id === pendingRef.current.mutation_id) { pendingRef.current = null; setPending(null); } } }
  catch (failure) { if (mounted.current && !signal?.aborted && order === sequence.current) setError(explanation(failure)); }
 }
 useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); /* account/token remounts this component */ }, []); // eslint-disable-line react-hooks/exhaustive-deps
 useEffect(() => {
  const refresh = () => { if (document.visibilityState !== 'hidden' && idle.current && !saving.current && !draftRef.current && !latest.current?.operation?.retry_after && !['pending','running'].includes(latest.current?.operation?.status ?? '')) void load(); };
  window.addEventListener('focus', refresh);
  const timer = setInterval(refresh, 10000);
  return () => { window.removeEventListener('focus', refresh); clearInterval(timer); };
 }, []);
 useEffect(() => {
  const refresh = () => { if (!saving.current) void load(); };
  window.addEventListener(COMPARISON_REFRESH, refresh);
  return () => window.removeEventListener(COMPARISON_REFRESH, refresh);
 }, []);
 const seenEvaluation = useRef<string | null>(null);
 useEffect(() => {
  const status = evaluation.current?.evaluation;
  if (!status) return;
  const key = `${status.freshness}:${status.processing}`;
  const previous = seenEvaluation.current; seenEvaluation.current = key;
  if (previous !== null && previous !== key && !saving.current) void load();
 }, [evaluation.current?.evaluation?.freshness, evaluation.current?.evaluation?.processing]);
 const running = workspace?.operation?.status === 'pending' || workspace?.operation?.status === 'running';
 const settled = !busy && !running && !error && !unknown && !pending && !workspace?.operation?.retry_after;
 idle.current = settled;
 // Saves quietly, without freezing the form, so a refresh always shows the latest settings.
 function persist(draft: PlannerConfig) {
  const previous = saving.current;
  const task = (async () => {
   await previous;
   if (!mounted.current || !latest.current) return;
   setAutosave('saving'); sequence.current++;
   try {
    const value = await roadmapApi<Workspace>('/planner/config', token, { config: draft, expected_version: latest.current.version, mutation_id: crypto.randomUUID() });
    if (mounted.current) { receive(value); settings.clearIf(draft); setAutosave('saved'); }
   } catch { if (mounted.current) setAutosave('failed'); }
  })();
  saving.current = task;
  return task.finally(() => { if (saving.current === task) saving.current = null; });
 }
 useEffect(() => {
  const draft = settings.draft;
  if (!draft || settings.calculating || settings.previewError || !settled) return;
  const timer = setTimeout(() => void persist(draft), 400);
  return () => clearTimeout(timer);
 }, [settings.draft, settings.calculating, settings.previewError, settled]); // eslint-disable-line react-hooks/exhaustive-deps
 // Edits still waiting on that delay are sent as the page closes or the user moves to another page.
 useEffect(() => {
  const flush = () => {
   const draft = draftRef.current;
   if (!draft || !latest.current || unsafeDraft.current) return;
   void Promise.resolve(roadmapApi('/planner/config', token, { config: draft, expected_version: latest.current.version, mutation_id: crypto.randomUUID() }, undefined, { keepalive: true })).catch(() => {});
  };
  window.addEventListener('pagehide', flush);
  return () => { window.removeEventListener('pagehide', flush); flush(); };
 }, [token]);
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
 // A saved message that failed can only be retried from the helper, so bring it into view.
 const failedMessageId = workspace?.operation?.status === 'failed' && workspace.retry_request ? workspace.operation.id : null;
 useEffect(() => { if (failedMessageId) setHelperOpen(true); }, [failedMessageId]);
 function closeHelper() { helperDismissed.current = true; setHelperOpen(false); requestAnimationFrame(() => launcher.current?.focus()); }
 function openHelper() { helperTakesFocus.current = true; helperDismissed.current = false; setHelperOpen(true); }
 // Before a roadmap is shown the helper stays docked beside the planner, unless the user closed it.
 const current = workspace?.planner; const currentReview = current?.candidate ? current.candidate_review : current?.active_review;
 const planning = !!workspace && !((current?.candidate || current?.active) && currentReview && !configuring);
 useEffect(() => {
  const wide = window.matchMedia?.('(min-width: 1101px)');
  if (!planning || !wide) return;
  // On narrow screens the helper covers the page, so it only stays open there if the user opened it.
  const fit = () => {
   if (helperDismissed.current) return;
   if (wide.matches) { helperTakesFocus.current = false; setHelperOpen(true); }
   else if (!helperTakesFocus.current) setHelperOpen(false);
  };
  fit(); wide.addEventListener?.('change', fit);
  return () => wide.removeEventListener?.('change', fit);
 }, [planning]);
 async function change(path: string, data: Record<string, unknown>, retry = false) {
  if (busy || running || !latest.current) return false;
  const call = retry && unknownMutation.current ? unknownMutation.current : { path, body: { ...data, expected_version: latest.current.version, mutation_id: crypto.randomUUID() } };
  unknownMutation.current = call; setBusy(true); setError(''); sequence.current++;
  try {
   const value = await roadmapApi<Workspace | Pick<Workspace, 'version' | 'operation'>>(call.path, token, call.body);
   if (mounted.current) { unknownMutation.current = null; setUnknown(false); if ('messages' in value) receive(value); else await load(); }
   return true;
  } catch (failure) {
   if (mounted.current) { setError(explanation(failure)); const uncertain = !(failure instanceof RoadmapError) || failure.status >= 500; setUnknown(uncertain); if (!uncertain) unknownMutation.current = null; }
   return false;
  } finally { if (mounted.current) setBusy(false); }
 }
 // Settings are saved first so the model and the panel always share one confirmed record.
 async function saveSettings() {
  await saving.current;
  const planner = latest.current?.planner; const config = draftRef.current || settings.config; if (!config || !planner) return false;
  if (!draftRef.current && planner.config_saved) return true;
  const saved = await change('/planner/config', { config });
  if (saved) settings.clear();
  return saved;
 }
 async function send(request?: MessageRequest) {
  if (busy || running) return;
  if (!request && !text.trim()) return;
  if (!request && !await saveSettings()) return;
  const value = request || { expected_version: latest.current!.version, mutation_id: crypto.randomUUID(), message: text.trim(), allow_partial_assessment: partial };
  setBusy(true); setError(''); setPending(value); pendingRef.current = value; if (!request) setText(''); sequence.current++;
  try { await roadmapApi('/messages', token, value); if (mounted.current) { setPending(null); pendingRef.current = null; await load(); } }
  catch (failure) { if (mounted.current) { setError(explanation(failure)); if (!request && failure instanceof RoadmapError && failure.status < 500) { setText(current => current || value.message); setPending(null); pendingRef.current = null; } } }
  finally { if (mounted.current) setBusy(false); }
 }
 // The bar shows from the click (saving your settings, then the request), and the service's stage takes over once the work starts.
 const [starting, setStarting] = useState(false);
 async function generate() {
  setStarting(true);
  try { if (await saveSettings()) await change('/planner/generate', { allow_partial_assessment: partial }); } finally { if (mounted.current) setStarting(false); }
 }
 function retryGenerate(body: Record<string, unknown>, renew: boolean) {
  if (renew) { void change('/planner/generate', { allow_partial_assessment: partial }); return; }
  unknownMutation.current = { path: '/planner/generate', body }; void change('', {}, true);
 }
 const rolling = useRef<string | null>(null);
 useEffect(()=>{
  if(workspace?.context.evaluation && workspace.context.evaluation.freshness!=='current')return;
  if(!workspace?.planner.active||workspace.planner.candidate||!settled||!workspace.planner.signals.some(signal=>signal.kind==='next_week'))return;
  const key=`${workspace.planner.active.id}:${workspace.planner.runway.first_planning_week}`;
  if(rolling.current===key)return;rolling.current=key;
  void change('/planner/roll-forward',{allow_partial_assessment:true});
 },[workspace,settled]);
 if (!workspace) return <section className="roadmap-adviser"><h1>Roadmap</h1>{error ? <><p role="alert">{error}</p><button className="btn" onClick={() => void load()}>Retry loading</button></> : <PageSkeleton label="Loading your planner…" cards={3}/>}</section>;
 const { context, active: earlier, draft: earlierDraft, planner } = workspace;
 const frozen = busy || running || !!error || unknown || !!pending || !!workspace.operation?.retry_after;
 const plan = planner.candidate || planner.active; const preview = !!planner.candidate;
 const sourceChanged = !!plan && !!context.input_hash && plan.assessment_hash !== context.input_hash;
 const review = preview ? planner.candidate_review : planner.active_review;
 const showRoadmap = !!plan && !!review && !configuring;
 // Without both an extracted CV and a Career goal there is nothing to plan from, so only the checklist is shown.
 const blocked = !context.ready && context.availability !== 'unavailable' && !showRoadmap;
 // The accepted roadmap has its own header and keeps plan notices on the planning page; a count on Plan settings points to them.
 const activeView = showRoadmap && !preview;
 const signals = planner.signals.filter(signal => !sourceChanged || signal.kind !== 'evidence');
 const updates = (sourceChanged ? 1 : 0) + signals.length + (context.availability === 'unavailable' ? 1 : 0);
 const goalName = context.goal ? [context.goal.role, context.goal.company].filter(Boolean).join(' · ') : plan?.assessment.role || 'Your goal';
 const actions: RoadmapActions = {
  setDone: (session, done) => change('/planner/tasks/status', { task_id: session.task_id, status: done ? 'completed' : 'not_started' }),
  saveSession: (id, changes, allowOverlap) => change('/planner/sessions/save', { session_id: id, changes, allow_overlap: allowOverlap }),
  addSession: (session, allowOverlap) => change('/planner/sessions/add', { session, allow_overlap: allowOverlap }),
  move: moves => change('/planner/sessions/move', { moves }),
  skip: id => change('/planner/sessions/skip', { session_id: id }),
  // Reads: free times and elo's proposal are recalculated by the service from the saved schedule.
  freeTimes: (minutes, sessionId) => roadmapApi<FreeTimes>('/planner/sessions/free-times', token, { duration_minutes: minutes, ...(sessionId ? { session_id: sessionId } : {}) }).catch(() => null),
  backlogPlan: sessionIds => roadmapApi<BacklogPlan>('/planner/sessions/backlog-plan', token, sessionIds ? { session_ids: sessionIds } : {}).catch(() => null),
  recordOutcome: (milestone, demonstrated, note) => void change('/planner/milestones/outcome', { milestone_id: milestone.id, demonstrated, note: note || null }),
  reachCheckpoint: (milestone, key, reached) => void change('/planner/milestones/checkpoint', { milestone_id: milestone.id, checkpoint_key: key, reached }),
  confirm: (gap, answer) => void change('/planner/confirmations', { gap_id: gap.id, answer }),
 };
 const failedGeneration = workspace.operation?.status === 'failed' ? planner.retry_generate : null;
 const helper = helperOpen && !blocked && <AdviserChat workspace={workspace} runway={settings.runway} text={text} setText={setText} partial={partial} setPartial={setPartial} showPartial={showRoadmap} busy={busy} running={running} frozen={frozen} editing={!!plan} takeFocus={helperTakesFocus.current} close={closeHelper} send={() => void send()}
  retry={() => void send(workspace.operation?.error?.code === 'inputs_changed' ? { ...workspace.retry_request!, expected_version: workspace.version, mutation_id: crypto.randomUUID() } : workspace.retry_request!)} />;
 const legacy = earlier || earlierDraft;
 return <section className="roadmap-adviser">
  <div className={`roadmap-workspace${helperOpen ? ' helper-open' : ''}`}><div className="roadmap-main">
  {!showRoadmap && <header className="roadmap-heading"><div><h1>Roadmap</h1><p>{plan ? 'Plan settings: change your schedule, then preview an updated roadmap.' : 'Make room for the career you want.'}</p></div>
   <div className="roadmap-heading-side">
    <button ref={launcher} type="button" className="btn ghost helper-launcher" hidden={helperOpen || blocked} aria-expanded={helperOpen} onClick={() => helperOpen ? closeHelper() : openHelper()}>{helperOpen ? 'Chat helper is open' : workspace.messages.length ? 'Continue with chat helper' : 'Start chat helper'}</button>
    {running && !helperOpen && <p className="small">Your request is still being worked on. Changes are paused until it finishes.</p>}
   </div>
  </header>}
  {!activeView && sourceChanged && <section className="evaluate-banner change-banner" aria-labelledby="roadmap-outdated-title">
   <span className="evaluate-banner-mark" aria-hidden="true">↻</span>
   <div><h2 id="roadmap-outdated-title">Your roadmap is out of date</h2><p>Your CV, skills or career goal changed. Regenerate your roadmap to build a plan from your latest information. You can review the new plan before accepting it.</p></div>
   <div className="evaluate-banner-actions"><button type="button" className="btn pri" disabled={starting || frozen || !context.ready || !context.model_available || (!!context.evaluation && context.evaluation.freshness !== 'current')} onClick={() => void generate()}>Regenerate roadmap</button></div>
  </section>}
  {error && <div className="roadmap-notice" role="alert"><p>{error}</p><button className="btn ghost" disabled={busy} onClick={() => void load()}>Reload saved work</button>{pending && <button className="btn" disabled={busy || running} onClick={() => void send(pending)}>Recover sent message</button>}{unknown && <button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button>}</div>}
  {pending && !busy && !error && <div className="roadmap-notice"><p>The sent message is awaiting confirmation.</p><button className="btn" disabled={running} onClick={() => void send(pending)}>Recover sent message</button></div>}
  {unknown && !error && <div className="roadmap-notice"><p>The previous change is awaiting confirmation.</p><button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button></div>}
  {!activeView&&planner.active&&<EvidenceProposals token={token} version={workspace.version} onSaved={()=>void load()}/>}
  {!activeView && context.availability === 'unavailable' && <div className="roadmap-notice"><p>We can’t check your latest CV and Career goal right now. Your saved roadmap and conversation are still here; new plans and accepting a preview need this check.</p><button className="btn ghost" onClick={() => void load()}>Retry source check</button></div>}
  {!activeView && <EvaluationStatusPanel comparison={evaluation} actions disabled={frozen} />}
  {blocked && <Prerequisites issues={context.issues} />}
  <GenerationProgress active={starting || running} stage={running ? workspace.operation?.stage : undefined} context={context} />
  {failedGeneration && <div className="roadmap-notice" role="status"><p>{friendlyOperationError(workspace.operation?.error, 'Your plan could not be prepared. Try again.')}</p>{!!workspace.operation?.retry_after && <p>Provider capacity: retry in {workspace.operation.retry_after} seconds.</p>}<button className="btn" disabled={busy || !context.ready || !context.model_available || !!workspace.operation?.retry_after || (!!context.evaluation && context.evaluation.freshness !== 'current')} onClick={() => retryGenerate(failedGeneration, workspace.operation?.error?.code === 'inputs_changed')}>Try again</button></div>}
  <div id="plan-panel">
   {activeView ? <RoadmapViews plan={plan!} review={review!} planner={planner} goal={goalName} version={workspace.version} frozen={frozen} updates={updates} openSettings={() => setConfiguring(true)} actions={actions} />
   : showRoadmap ? <PlanPreview planner={planner} blockers={planner.candidate_blockers} goal={goalName} sourceChanged={sourceChanged}
     context={{ plan: plan!, review: review!, sessions: planSessions(planner, plan!, true, review!.remaining.resolved.today), today: review!.remaining.resolved.today, nowMinute: null, version: workspace.version, catalog: skillCatalog(plan!, planner), frozen, actions, go: () => {} }}
     accept={() => void change('/planner/accept', {})} discard={() => void change('/planner/discard', {})} backToSettings={() => setConfiguring(true)}
     keepTasks={decisions => void change('/planner/tasks/reconcile', { candidate_id: plan!.id, decisions })} />
   : blocked ? null : <>{!!plan && !preview && signals.length > 0 && <ul className="plan-updates" aria-label="Changes since this roadmap was prepared">{signals.map(signal => <li key={signal.kind + signal.message}>{signal.message}</li>)}</ul>}<SettingsPanel profileSkills={profileSkills.state} workspace={workspace} settings={settings} partial={partial} setPartial={setPartial} frozen={frozen} generate={() => void generate()} save={() => void saveSettings()} autosave={autosave} returnToReview={plan ? () => setConfiguring(false) : null} /></>}
  </div>
  {!showRoadmap && !!legacy && <details className="plan-explanation earlier-plan"><summary>Earlier plan without session times</summary><p className="small">This plan was made before timed roadmaps. It stays here for reference and isn’t part of your current roadmap.</p><ul>{legacy.tasks.filter(task => !task.removed).map(task => <li key={task.id}>{task.title} · {task.status.replaceAll('_', ' ')}</li>)}</ul></details>}
  </div>{helper}</div>
 </section>;
}

const stages = [['assessing', 'Comparing your skills with your goal', 30], ['writing', 'Writing your roadmap', 65], ['correcting', 'Fixing what the schedule check found', 88]] as const;
/** Stage-based progress: it only moves when the service reports a new stage, so it never claims more than is known. */
export function generationProgress(stage?: string) {
 const index = stages.findIndex(([key]) => key === stage);
 if (index < 0) return { percent: 8, label: 'Starting', step: 0 };
 return { percent: stages[index][2], label: stages[index][1], step: index + 1 };
}
function GenerationProgress({ active, stage, context }: { active: boolean; stage?: string; context?: Context }) {
 const box = useRef<HTMLDivElement>(null);
 useEffect(() => { if (active) box.current?.scrollIntoView?.({ block: 'nearest', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); }, [active]);
 if (!active) return null;
 const { percent, step } = generationProgress(stage);
 const shown = stages.filter((_, index) => index < 2 || stage === 'correcting');
 const steps: ProcessingStep[] = shown.map(([, name], index) => ({ label: name, state: index + 1 < step ? 'done' : index + 1 === step ? 'now' : 'next', note: index + 1 === step && stage === 'correcting' ? 'Now' : undefined }));
 return <div ref={box}>{(context?.goal || context?.cv) && <section className="processing-using" aria-labelledby="using-h"><h2 id="using-h">What elo is using</h2>
  {context.goal && <div className="processing-using-row"><h3>Career goal</h3><span className="processing-chip goal">{context.goal.role}</span>{context.goal.company && <span className="processing-chip">{context.goal.company}</span>}</div>}
  {context.cv?.name && <div className="processing-using-row"><h3>CV</h3><span className="processing-chip">{context.cv.name}</span></div>}
  <p className="small">Your plan is locked while elo generates. Nothing is lost if you leave this page.</p></section>}<ProcessingCard dark title="Generating your roadmap" progressLabel={step ? 'Building your plan' : 'Starting: saving your settings'} percent={percent} steps={steps}
  footer={<p>You can leave this page. Your roadmap will be here when it’s done.</p>}/><SkeletonRoad /></div>;
}

const requirements = [
 { source: 'cv', title: 'Extracted CV', done: 'Your CV is extracted and selected.', href: '/cv', action: 'Open CV' },
 { source: 'career', title: 'Career goal', done: 'Your Career goal is set.', href: '/career-goal', action: 'Open Career Goal' },
] as const;
function Prerequisites({ issues }: { issues: { source: string; message: string; href: string }[] }) {
 return <div className="roadmap-prerequisites"><h2>Finish these first</h2><p>Your roadmap is built from your extracted CV and your Career goal. Complete both to start planning.</p>
  <ul className="prerequisite-list">{requirements.map(item => { const issue = issues.find(entry => entry.source === item.source);
   return <li key={item.source} className={issue ? 'todo' : 'done'}><span className="prerequisite-mark" aria-hidden="true">{issue ? '○' : '✓'}</span><div><strong>{item.title}</strong><p>{issue ? issue.message : item.done}</p></div>{issue && <Link className="btn ghost" href={issue.href || item.href}>{item.action}</Link>}</li>; })}</ul></div>;
}

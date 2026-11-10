"use client";
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import { roadmapApi, RoadmapError } from '@/lib/api/roadmap';
import { EvidenceProposals } from './evidence-proposals';
import { AdviserChat } from './adviser-chat';
import { RoadmapReview } from './roadmap-review';
import { SettingsPanel, useSettingsDraft, type AutosaveState } from './settings-panel';
import type { Workspace, MessageRequest, PlannerConfig } from './types';
import '@/styles/roadmap.css';
import { errorText, friendlyOperationError } from '@/lib/errors';
import { loadSkills, useSection } from '@/lib/api/workspace-summary';
import { PageSkeleton } from '@/components/ui/workspace-ui';
import { formatDate } from '@/lib/format';

const dayNumber = (value: string) => Math.round(Date.parse(`${value}T12:00:00Z`) / 86400000);
/** "172 days until Tue, 4 May 2027 · Week 1 of 24", from saved plan dates only. */
export function planCountdown(today: string, start: string | null, target: string | null) {
 if (!target) return null;
 const left = dayNumber(target) - dayNumber(today);
 if (left < 0) return null;
 const days = left === 0 ? 'Today' : `${left} ${left === 1 ? 'day' : 'days'}`;
 if (!start || dayNumber(start) > dayNumber(today)) return { days, target, week: null, weeks: null };
 // Whole weeks, as the planner's runway counts them; leftover days belong to the last week.
 const weeks = Math.max(1, Math.floor((dayNumber(target) - dayNumber(start) + 1) / 7));
 return { days, target, week: Math.min(weeks, Math.floor((dayNumber(today) - dayNumber(start)) / 7) + 1), weeks };
}

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
  catch (failure) { if (mounted.current) setError(explanation(failure)); }
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
  if(!workspace?.planner.active||workspace.planner.candidate||!settled||!workspace.planner.signals.some(signal=>signal.kind==='next_week'))return;
  const key=`${workspace.planner.active.id}:${workspace.planner.runway.first_planning_week}`;
  if(rolling.current===key)return;rolling.current=key;
  void change('/planner/roll-forward',{allow_partial_assessment:true});
 },[workspace,settled]);
 if (!workspace) return <section className="roadmap-adviser"><h1>Roadmap</h1>{error ? <><p role="alert">{error}</p><button className="btn" onClick={() => void load()}>Retry loading</button></> : <PageSkeleton label="Loading your planner…" cards={3}/>}</section>;
 const { context, active: earlier, draft: earlierDraft, planner } = workspace;
 const frozen = busy || running || !!error || unknown || !!pending || !!workspace.operation?.retry_after;
 const plan = planner.candidate || planner.active; const preview = !!planner.candidate;
 const review = preview ? planner.candidate_review : planner.active_review;
 const showRoadmap = !!plan && !!review && !configuring;
 const countdown = showRoadmap ? planCountdown(review!.remaining.resolved.today, plan!.config.start_date || plan!.first_planning_week, plan!.config.target_date) : null;
 const failedGeneration = workspace.operation?.status === 'failed' ? planner.retry_generate : null;
 const helper = helperOpen && <AdviserChat workspace={workspace} runway={settings.runway} text={text} setText={setText} partial={partial} setPartial={setPartial} showPartial={showRoadmap} busy={busy} running={running} frozen={frozen} editing={!!plan} takeFocus={helperTakesFocus.current} close={closeHelper} send={() => void send()}
  retry={() => void send(workspace.operation?.error?.code === 'inputs_changed' ? { ...workspace.retry_request!, expected_version: workspace.version, mutation_id: crypto.randomUUID() } : workspace.retry_request!)} />;
 const legacy = earlier || earlierDraft;
 return <section className="roadmap-adviser">
  <div className={`roadmap-workspace${helperOpen ? ' helper-open' : ''}`}><div className="roadmap-main">
  <header className="roadmap-heading"><div><h1>Roadmap</h1>{countdown ? <p><strong>{countdown.days}</strong> until {formatDate(countdown.target)}{countdown.week ? ` · Week ${countdown.week} of ${countdown.weeks}` : ''}</p> : <p>Make room for the career you want.</p>}</div>
   <div className="roadmap-heading-side">
    <button ref={launcher} type="button" className="btn ghost helper-launcher" hidden={helperOpen} aria-expanded={helperOpen} onClick={() => helperOpen ? closeHelper() : openHelper()}>{helperOpen ? 'Chat helper is open' : workspace.messages.length ? 'Continue with chat helper' : 'Start chat helper'}</button>
    {running && !helperOpen && <p className="small">Your request is still being worked on. Changes are paused until it finishes.</p>}
   </div>
  </header>
  {error && <div className="roadmap-notice" role="alert"><p>{error}</p><button className="btn ghost" disabled={busy} onClick={() => void load()}>Reload saved work</button>{pending && <button className="btn" disabled={busy || running} onClick={() => void send(pending)}>Recover sent message</button>}{unknown && <button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button>}</div>}
  {pending && !busy && !error && <div className="roadmap-notice"><p>The sent message is awaiting confirmation.</p><button className="btn" disabled={running} onClick={() => void send(pending)}>Recover sent message</button></div>}
  {unknown && !error && <div className="roadmap-notice"><p>The previous change is awaiting confirmation.</p><button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button></div>}
  {planner.active&&<EvidenceProposals token={token} version={workspace.version} onSaved={()=>void load()}/>}
  {context.availability === 'unavailable' && <div className="roadmap-notice"><p>We can’t check your latest CV and Career goal right now. Your saved roadmap and conversation are still here; new plans and accepting a preview need this check.</p><button className="btn ghost" onClick={() => void load()}>Retry source check</button></div>}
  {!context.ready && context.availability !== 'unavailable' && <div className="roadmap-prerequisites"><h2>Bring your starting point and direction</h2><p>Your roadmap needs your extracted CV and Career goal to personalise the plan.</p>{context.issues.map(issue => <div key={issue.source}><p>{issue.message}</p><Link className="btn ghost" href={issue.href}>Open {issue.source === 'cv' ? 'CV' : 'Career Goal'}</Link></div>)}</div>}
  <GenerationProgress active={starting || running} stage={running ? workspace.operation?.stage : undefined} />
  {failedGeneration && <div className="roadmap-notice" role="status"><p>{friendlyOperationError(workspace.operation?.error, 'Your plan could not be prepared. Try again.')}</p>{!!workspace.operation?.retry_after && <p>Provider capacity: retry in {workspace.operation.retry_after} seconds.</p>}<button className="btn" disabled={busy || !context.ready || !context.model_available || !!workspace.operation?.retry_after} onClick={() => retryGenerate(failedGeneration, workspace.operation?.error?.code === 'inputs_changed')}>Try again</button></div>}
  <div id="plan-panel">
   {showRoadmap ? <RoadmapReview plan={plan!} review={review!} preview={preview} planner={planner} blockers={planner.candidate_blockers} frozen={frozen}
    accept={() => void change('/planner/accept', {})} discard={() => void change('/planner/discard', {})} backToSettings={() => setConfiguring(true)} revise={() => void generate()}
    complete={(session, note) => change('/planner/assignments/status', { assignment_id: session.id, status: 'completed', evidence_note: note.trim() || null })}
    reopen={session => change('/planner/assignments/status', { assignment_id: session.id, status: 'scheduled' })}
    saveNotes={(taskId, notes) => change('/planner/tasks/notes', { task_id: taskId, notes })}
    addTask={task => change('/planner/tasks/add', { task })}
    recordOutcome={(milestone, demonstrated, note) => void change('/planner/milestones/outcome', { milestone_id: milestone.id, demonstrated, note: note || null })}
    confirm={(gap, answer) => void change('/planner/confirmations', { gap_id: gap.id, answer })} />
   : <SettingsPanel profileSkills={profileSkills.state} workspace={workspace} settings={settings} partial={partial} setPartial={setPartial} frozen={frozen} generate={() => void generate()} save={() => void saveSettings()} autosave={autosave} returnToReview={plan ? () => setConfiguring(false) : null} />}
  </div>
  {!!legacy && <details className="plan-explanation earlier-plan"><summary>Earlier plan without session times</summary><p className="small">This plan was made before timed roadmaps. It stays here for reference and isn’t part of your current roadmap.</p><ul>{legacy.tasks.filter(task => !task.removed).map(task => <li key={task.id}>{task.title} · {task.status.replaceAll('_', ' ')}</li>)}</ul></details>}
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
function GenerationProgress({ active, stage }: { active: boolean; stage?: string }) {
 const box = useRef<HTMLDivElement>(null);
 useEffect(() => { if (active) box.current?.scrollIntoView?.({ block: 'nearest', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); }, [active]);
 if (!active) return null;
 const { percent, label, step } = generationProgress(stage);
 const total = stage === 'correcting' ? 3 : 2;
 return <div ref={box} className="generation-progress" role="status"><p><strong>Preparing your roadmap.</strong> You can leave this page; it keeps going and reconnects when you return.</p>
  <div className="generation-bar" role="progressbar" aria-label="Roadmap generation progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={step ? `Step ${step} of ${total}: ${label}` : label}><i style={{ width: `${percent}%` }} /></div>
  <p className="generation-step">{step ? `Step ${step} of ${total}: ${label}` : 'Starting: saving your settings'}</p>
  <ol>{stages.map(([key, name], index) => (index < 2 || stage === 'correcting') && <li key={key} className={index + 1 === step ? 'current' : index + 1 < step ? 'done' : ''}>{name}</li>)}</ol></div>;
}

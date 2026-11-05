"use client";
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import { roadmapApi, RoadmapError } from '@/lib/api/roadmap';
import { AdviserChat } from './adviser-chat';
import { RoadmapReview } from './roadmap-review';
import { SettingsPanel, useSettingsDraft } from './settings-panel';
import type { Workspace, MessageRequest, Assessment } from './types';
import '@/styles/roadmap.css';

const explanation = (error: unknown) => error instanceof Error ? error.message : 'Your saved work could not be confirmed. Retry to recover it.';

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
 const [text, setText] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
 const [partial, setPartial] = useState(false); const [tab, setTab] = useState<'plan' | 'assessment'>('plan');
 const [helperOpen, setHelperOpen] = useState(false); const launcher = useRef<HTMLButtonElement>(null);
 const helperDismissed = useRef(false); const helperTakesFocus = useRef(true);
 const [configuring, setConfiguring] = useState(false);
 const [pending, setPending] = useState<MessageRequest | null>(null);
 const mounted = useRef(true); const latest = useRef<Workspace | null>(null); const sequence = useRef(0);
 const pendingRef = useRef<MessageRequest | null>(null);
 const unknownMutation = useRef<{ path: string; body: unknown } | null>(null); const [unknown, setUnknown] = useState(false);
 const settings = useSettingsDraft(workspace, token);
 useEffect(() => { mounted.current = true; return () => { mounted.current = false; sequence.current++; }; }, []);
 function receive(value: Workspace) {
  if (!mounted.current) return;
  // Choose the view in the same update as the new preview. A later effect can
  // otherwise override a Back click made just after the preview appears.
  const candidateId = value.planner.candidate?.id;
  if (candidateId && candidateId !== latest.current?.planner.candidate?.id) {
   setConfiguring(false); setTab('plan'); setHelperOpen(false);
  }
  latest.current = value; setWorkspace(value);
 }
 async function load(signal?: AbortSignal) {
  const order = ++sequence.current;
  try { const value = await roadmapApi<Workspace>(workspacePath(), token, undefined, signal); if (mounted.current && order === sequence.current) { receive(value); setError(''); if (pendingRef.current && value.operation?.id === pendingRef.current.mutation_id) { pendingRef.current = null; setPending(null); } } }
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
  const planner = latest.current?.planner; if (!settings.config || !planner) return false;
  if (!settings.dirty && planner.config_saved) return true;
  const saved = await change('/planner/config', { config: settings.config });
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
 async function generate() {
  if (await saveSettings()) await change('/planner/generate', { allow_partial_assessment: partial });
 }
 function retryGenerate(body: Record<string, unknown>, renew: boolean) {
  if (renew) { void change('/planner/generate', { allow_partial_assessment: partial }); return; }
  unknownMutation.current = { path: '/planner/generate', body }; void change('', {}, true);
 }
 if (!workspace) return <section className="roadmap-adviser"><h1>Roadmap</h1><p role={error ? 'alert' : 'status'}>{error || 'Loading your planner…'}</p>{error && <button className="btn" onClick={() => void load()}>Retry loading</button>}</section>;
 const { context, active: earlier, draft: earlierDraft, assessment, planner } = workspace;
 const frozen = busy || running || !!error || unknown || !!pending || !!workspace.operation?.retry_after;
 const plan = planner.candidate || planner.active; const preview = !!planner.candidate;
 const review = preview ? planner.candidate_review : planner.active_review;
 const showRoadmap = !!plan && !!review && !configuring;
 const failedGeneration = workspace.operation?.status === 'failed' ? planner.retry_generate : null;
 const helper = helperOpen && <AdviserChat workspace={workspace} runway={settings.runway} text={text} setText={setText} partial={partial} setPartial={setPartial} showPartial={showRoadmap} busy={busy} running={running} frozen={frozen} editing={!!plan} takeFocus={helperTakesFocus.current} close={closeHelper} send={() => void send()}
  retry={() => void send(workspace.operation?.error?.code === 'inputs_changed' ? { ...workspace.retry_request!, expected_version: workspace.version, mutation_id: crypto.randomUUID() } : workspace.retry_request!)} />;
 const starting = <AssessmentView assessment={plan?.assessment || assessment} />;
 const legacy = earlier || earlierDraft;
 return <section className="roadmap-adviser">
  <header className="roadmap-heading"><div><h1>Roadmap</h1><p>Make room for the career you want.</p></div>
   <div className="roadmap-heading-side">
    <div className="roadmap-tabs" role="tablist" aria-label={showRoadmap ? 'Roadmap views' : 'Planning detail'}>
     <button id="plan-tab" role="tab" aria-selected={tab !== 'assessment'} aria-controls="plan-panel" onClick={() => setTab('plan')}>{showRoadmap ? 'Roadmap' : 'Planner'}</button>
     <button id="assessment-tab" role="tab" aria-selected={tab === 'assessment'} aria-controls="assessment-panel" onClick={() => setTab('assessment')}>Starting point</button>
    </div>
    <button ref={launcher} type="button" className="btn ghost helper-launcher" aria-expanded={helperOpen} onClick={() => helperOpen ? closeHelper() : openHelper()}>{helperOpen ? 'Hide chat helper' : workspace.messages.length ? 'Continue with chat helper' : 'Start chat helper'}</button>
    {running && !helperOpen && <p className="small">Your request is still being worked on. Changes are paused until it finishes.</p>}
   </div>
  </header>
  {error && <div className="roadmap-notice" role="alert"><p>{error}</p><button className="btn ghost" disabled={busy} onClick={() => void load()}>Reload saved work</button>{pending && <button className="btn" disabled={busy || running} onClick={() => void send(pending)}>Recover sent message</button>}{unknown && <button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button>}</div>}
  {pending && !busy && !error && <div className="roadmap-notice"><p>The sent message is awaiting confirmation.</p><button className="btn" disabled={running} onClick={() => void send(pending)}>Recover sent message</button></div>}
  {unknown && !error && <div className="roadmap-notice"><p>The previous change is awaiting confirmation.</p><button className="btn" disabled={busy || running} onClick={() => void change('', {}, true)}>Recover saved change</button></div>}
  {context.availability === 'unavailable' && <div className="roadmap-notice"><p>We can’t check your latest CV and Career goal right now. Your saved roadmap and conversation are still here; new plans and accepting a preview need this check.</p><button className="btn ghost" onClick={() => void load()}>Retry source check</button></div>}
  {!context.ready && context.availability !== 'unavailable' && <div className="roadmap-prerequisites"><h2>Bring your starting point and direction</h2><p>Your roadmap needs your extracted CV and Career goal to personalise the plan.</p>{context.issues.map(issue => <div key={issue.source}><p>{issue.message}</p><Link className="btn ghost" href={issue.href}>Open {issue.source === 'cv' ? 'CV' : 'Career Goal'}</Link></div>)}</div>}
  <GenerationProgress stage={running ? workspace.operation?.stage : undefined} />
  {failedGeneration && <div className="roadmap-notice" role="status"><p>{workspace.operation?.error?.detail || 'Your plan could not be prepared.'}</p>{!!workspace.operation?.retry_after && <p>Provider capacity: retry in {workspace.operation.retry_after} seconds.</p>}<button className="btn" disabled={busy || !context.ready || !context.model_available || !!workspace.operation?.retry_after} onClick={() => retryGenerate(failedGeneration, workspace.operation?.error?.code === 'inputs_changed')}>Try again</button></div>}
  <div className={`roadmap-workspace${helperOpen ? ' helper-open' : ''}`}><div className="roadmap-main">
  <div id="plan-panel" role="tabpanel" aria-labelledby="plan-tab" hidden={tab === 'assessment'}>
   {showRoadmap ? <RoadmapReview plan={plan!} review={review!} preview={preview} planner={planner} blockers={planner.candidate_blockers} frozen={frozen}
    accept={() => void change('/planner/accept', {})} discard={() => void change('/planner/discard', {})} backToSettings={() => setConfiguring(true)} revise={() => void generate()}
    complete={(session, note) => change('/planner/assignments/status', { assignment_id: session.id, status: 'completed', evidence_note: note.trim() || null })}
    reopen={session => change('/planner/assignments/status', { assignment_id: session.id, status: 'scheduled' })}
    recordOutcome={(milestone, demonstrated, note) => void change('/planner/milestones/outcome', { milestone_id: milestone.id, demonstrated, note: note || null })}
    confirm={(gap, answer) => void change('/planner/confirmations', { gap_id: gap.id, answer })} />
   : <SettingsPanel workspace={workspace} settings={settings} partial={partial} setPartial={setPartial} frozen={frozen} generate={() => void generate()} save={() => void saveSettings()} returnToReview={plan ? () => setConfiguring(false) : null} />}
  </div>
  <div id="assessment-panel" role="tabpanel" aria-labelledby="assessment-tab" hidden={tab !== 'assessment'}>{starting}</div>
  </div>{helper}</div>
  {!!legacy && <details className="plan-explanation earlier-plan"><summary>Earlier plan without session times</summary><p className="small">This plan was made before timed roadmaps. It stays here for reference and isn’t part of your current roadmap.</p><ul>{legacy.tasks.filter(task => !task.removed).map(task => <li key={task.id}>{task.title} · {task.status.replaceAll('_', ' ')}</li>)}</ul></details>}
 </section>;
}

const stages = [['assessing', 'Comparing your skills with your goal'], ['writing', 'Writing your roadmap'], ['correcting', 'Fixing what the schedule check found']] as const;
function GenerationProgress({ stage }: { stage?: string }) {
 if (!stage || !stages.some(([key]) => key === stage)) return null;
 const position = stages.findIndex(([key]) => key === stage);
 return <div className="generation-progress" role="status"><p><strong>Preparing your roadmap.</strong> You can leave this page; it keeps going and reconnects when you return.</p><ol>{stages.map(([key, label], index) => (index < 2 || stage === 'correcting') && <li key={key} className={index === position ? 'current' : index < position ? 'done' : ''}>{label}</li>)}</ol></div>;
}

function AssessmentView({ assessment }: { assessment: Assessment | null }) {
 if (!assessment) return <div className="plan-empty"><h2>Advice grounded in your experience</h2><p>Generating your roadmap starts the comparison of your selected CV and Career goal. Findings and their limitations will appear here.</p></div>;
 return <div className="assessment-view"><h2>Your starting point</h2><p>Based on declared evidence for {assessment.role}.</p><p className="small">Interview coverage: {assessment.research_coverage.replaceAll('_', ' ')}</p>{assessment.groups?.map(group => <details key={group.id}><summary>{group.operator === 'any' ? 'Alternative routes' : 'Combined conditions'}<small>{group.match_status.replaceAll('_', ' ')}</small></summary><p>{group.operator === 'any' ? 'One supported permitted route satisfies this group. Unused alternatives are not mandatory work.' : 'All required conditions contribute to this group. Known support, shortfalls and uncertainty remain separate below.'}</p><ul>{group.requirement_refs.map(ref => <li key={ref}>{[...assessment.job_skill_gaps, ...assessment.constraints].find(r => r.ref === ref)?.name || 'Historical requirement'}</li>)}</ul></details>)}{([['Role requirements', assessment.job_skill_gaps], ['Interview preparation', assessment.interview_prep_gaps], ['Other conditions', assessment.constraints]] as const).map(([label, items]) => <section key={label}><h3>{label}</h3>{!items.length && <p className="small">No findings in this group. Coverage limitations still apply.</p>}{items.map(item => <details key={item.ref}><summary>{item.name}<small>{item.match_status.replaceAll('_', ' ')}</small></summary>{(item.evidence || item.description) && <blockquote>{item.evidence || item.description}</blockquote>}{item.priority && <p className="small">Importance: {item.priority}{item.origin ? ` · ${item.origin.replaceAll('_', ' ')}` : ''}</p>}{item.components.map((c, i) => <p key={i}><strong>{c.dimension.replaceAll('_', ' ')}: {c.status.replaceAll('_', ' ')}</strong><br />{c.explanation}{c.evidence_refs.map(ref => assessment.evidence?.[ref] && <span className="assessment-evidence" key={ref}><strong>{assessment.evidence[ref].name || 'Saved declaration'}</strong>: {assessment.evidence[ref].text}</span>)}</p>)}{item.recommendation && <p>{item.recommendation}</p>}</details>)}</section>)}</div>;
}

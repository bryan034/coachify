"use client";
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { Assessment, Operation } from '@/features/roadmap/types';
import { errorText, friendlyOperationError } from '@/lib/errors';
import { assessmentApi, skillMatches, skillOutcomes, type EvaluationStatus } from '@/lib/api/assessment';

type Command = { expected_version: number; mutation_id: string; allow_partial: boolean };
type Current = { evaluation?: EvaluationStatus; version: number; operation: Operation | null; result: Assessment | null; stale: boolean; ready: boolean; issues: { message: string; href: string; source?: string }[] };
/** The source revisions an evaluation was made from; comparing two of them says what changed. */
export type InputRevisions = { cv_id: string | null; goal_id: string; goal_version: number; goal_selection_version?: number };
type Context = { evaluation?: EvaluationStatus; ready: boolean; model_available: boolean; research_coverage?: string; goal?: { role: string; target_type?: string }; cv?: { name: string }; inputs?: InputRevisions; input_hash?: string; issues?: Current['issues']; cv_reviewed?: boolean | null; research_pending?: boolean | null };

/** Fired when a source an evaluation depends on (active CV, career goal) changes, or an evaluation starts. Every comparison re-reads. */
export const COMPARISON_REFRESH = 'elo:comparison-refresh';
export function announceInputsChanged() { if (typeof window !== 'undefined') window.dispatchEvent(new Event(COMPARISON_REFRESH)); }
/** Every consumer reads the same version-checked Assessment result. Reads never start one: only `compare` submits the explicit command. */
export function useComparison(token: string | undefined, revision?: string) {
 const [current, setCurrent] = useState<Current | null>(null), [context, setContext] = useState<Context | null>(null);
 const [error, setError] = useState(''), [busy, setBusy] = useState(false), [attempt, setAttempt] = useState(0);
 const owner = useRef(token);
 const sourceRevision = useRef(revision);
 const command = useRef<Command | null>(null), sending = useRef(false);
 const lifetime = useRef(new AbortController());
 useEffect(() => {
  const abort = new AbortController(); lifetime.current = abort; sending.current = false;
  if (owner.current !== token) { owner.current = token; command.current = null; }
  if (sourceRevision.current !== revision) { sourceRevision.current = revision; command.current = null; }
  setCurrent(null); setContext(null); setError(''); setBusy(false);
  if (!token) return () => abort.abort();
  let timer: ReturnType<typeof setTimeout>; let sequence = 0;
  async function load() {
   const order = ++sequence;
   try {
    const value = await assessmentApi<Current>('/current', token!, undefined, abort.signal);
    if (!Number.isInteger(value.version) || typeof value.stale !== 'boolean') throw new Error('Your comparison could not be read. Try again.');
    const source = await assessmentApi<Context>('/context', token!, undefined, abort.signal);
    if (abort.signal.aborted || order !== sequence) return;
    if (value.operation?.status === 'failed') {
     const operation = await assessmentApi<{retry_request: Command | null}>('/operation', token!, undefined, abort.signal);
     if (abort.signal.aborted || order !== sequence) return;
     command.current = value.operation.error?.code === 'inputs_changed' ? null : operation.retry_request;
    }
    setCurrent({...value, evaluation: source.evaluation ?? value.evaluation, stale: value.stale || Boolean(value.result && source.input_hash && value.result.input_hash !== source.input_hash)}); setContext(source); setError('');
    if (value.operation && ['pending', 'running'].includes(value.operation.status)) timer = setTimeout(load, 2000);
    else if (value.operation?.retry_after) timer = setTimeout(load, Math.min(value.operation.retry_after, 60) * 1000);
   } catch (cause) { if (!abort.signal.aborted && order === sequence) setError(errorText(cause, 'Your comparison could not be loaded. Try again.')); }
  }
  void load();
  const refresh = () => { clearTimeout(timer); void load(); };
  window.addEventListener('focus', refresh); window.addEventListener(COMPARISON_REFRESH, refresh);
  return () => { abort.abort(); clearTimeout(timer); window.removeEventListener('focus', refresh); window.removeEventListener(COMPARISON_REFRESH, refresh); };
 }, [token, attempt, revision]);
 async function compare() {
  if (!token || !current || sending.current) return;
  const signal = lifetime.current.signal;
  sending.current = true; setBusy(true); setError('');
  command.current ??= { expected_version: current.version, mutation_id: crypto.randomUUID(), allow_partial: true };
  try {
   await assessmentApi('', token, command.current, signal);
   if (!signal.aborted) { command.current = null; setAttempt(value => value + 1); announceInputsChanged(); }
  } catch (cause) { if (!signal.aborted) {
   if (cause && typeof cause === 'object' && 'status' in cause && cause.status === 409) { command.current = null; setAttempt(value => value + 1); }
   else setError(errorText(cause, 'Could not start the comparison. Retry to recover the same request.'));
  } }
  finally { if (!signal.aborted) { sending.current = false; setBusy(false); } }
 }
 const result = owner.current === token && !error && current && !current.stale ? current.result : null;
 return { current: owner.current === token ? current : null, context: owner.current === token ? context : null, result, matches: result ? skillMatches(result) : null, outcomes: result ? skillOutcomes(result) : null, error, busy, compare, retry: () => setAttempt(value => value + 1) };
}
export type Comparison = ReturnType<typeof useComparison>;
export function ComparisonPanel({ comparison: c, className = '' }: { comparison: Comparison; className?: string }) {
 const running = !!c.current?.operation && ['pending', 'running'].includes(c.current.operation.status);
 const outcomes = c.result?.job_skill_gaps ?? [];
 const have = outcomes.filter(item => item.match_status === 'supported').length;
 const gaps = outcomes.filter(item => c.matches?.[item.ref.slice(4)] !== 'covered' && item.components?.some(component => component.status === 'confirmed_shortfall')).sort((a,b) => (c.result?.priorities.indexOf(a.ref) ?? -1) - (c.result?.priorities.indexOf(b.ref) ?? -1));
 return <section id="goal-match" className={`card pad goal-comparison ${className}`} aria-label="Goal match" aria-busy={running || c.busy}>
  <h2>Goal match</h2>
  {!c.current && !c.error && <p role="status">Checking your saved comparison…</p>}
  {c.error && <div role="alert"><p>{c.error}</p><button className="btn ghost" onClick={c.retry}>Reload comparison</button></div>}
  {c.current?.stale && c.current.result && <p>Your goal or skills changed. Compare again to update these results.</p>}
  {c.current && !c.result && !running && <p>Not yet compared with your latest Skills Profile.</p>}
  {c.context?.goal && <p>{c.context.goal.role}{c.context.cv?.name ? ` · ${c.context.cv.name}` : ''}</p>}
  {c.result && <><p><strong>You have evidence for {have} of {outcomes.length} skills.</strong> Missing evidence stays unknown.</p>
   <p>Top confirmed gaps</p>{gaps.length ? <ul>{gaps.slice(0, 3).map(item => <li key={item.ref}>{item.name}</li>)}</ul> : <p>No confirmed skill gaps in this comparison.</p>}
   <Link href="/roadmap">Plan your next steps</Link></>}
  {!c.result && c.context?.ready && !['available', 'no_findings'].includes(c.context.research_coverage ?? '') && <p className="small">Compare with available evidence. Interview research is {c.context.research_coverage || 'unavailable'}; results will be labelled partial.</p>}
  {c.result && !['available', 'no_findings'].includes(c.result.research_coverage) && <p className="notice">Partial comparison: interview research is {c.result.research_coverage}.</p>}
  {c.context && !c.context.ready && c.context.issues?.map((issue, i) => <p key={i}>{issue.message} <Link href={issue.href}>Set up</Link></p>)}
  {c.context && !c.context.model_available && <p>The comparison assistant is unavailable. Your saved result is retained.</p>}
  {running ? <p role="status">Comparing your saved evidence… You can leave and return.</p> : c.context?.ready && <button className="btn pri" disabled={c.busy || !c.context.model_available || !!c.current?.operation?.retry_after} onClick={() => void c.compare()}>{c.busy ? 'Starting comparison…' : c.result ? 'Compare again' : 'Compare with my skills'}</button>}
  {c.current?.operation?.status === 'failed' && <p role="alert">{friendlyOperationError(c.current.operation.error, 'The comparison failed. Try again.')}</p>}
 </section>;
}

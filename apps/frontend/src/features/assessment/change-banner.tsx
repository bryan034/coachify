"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { roadmapApi } from '@/lib/api/roadmap';
import { friendlyOperationError } from '@/lib/errors';
import { announceInputsChanged, COMPARISON_REFRESH, useComparison, type InputRevisions } from './comparison';
import '@/styles/evaluate.css';

export type Change = 'cv' | 'goal' | 'cv_and_goal' | 'details';

/** What differs between the inputs an evaluation used and the current ones. */
export function describeChange(before: InputRevisions | undefined, now: InputRevisions | undefined): Change {
 if (!before || !now) return 'details';
 const cv = before.cv_id !== now.cv_id;
 const goal = before.goal_id !== now.goal_id || before.goal_version !== now.goal_version;
 return cv && goal ? 'cv_and_goal' : cv ? 'cv' : goal ? 'goal' : 'details';
}

type Roadmap = { active: { assessment_hash: string } | null } | null;
const DISMISSED = 'elo:change-banner-dismissed';
const remembered = () => { try { return window.sessionStorage.getItem(DISMISSED); } catch { return null; } };
/** Input hashes an automatic update was already started for in this page load, so a failure never loops. */
const attempted = new Set<string>();
/** Test hook: forget automatic attempts between cases. */
export function resetAutomaticEvaluations() { attempted.clear(); }

/** Career Goal and Skills Profile keep the skill evaluation in step with the goal and CV automatically. */
const evaluates = (path: string) => path === '/cv' || path.startsWith('/cv/') || path === '/career-goal' || path.startsWith('/career-goal/');
/** Full-screen chats keep the viewport for the conversation. */
const showsProgress = (path: string) => evaluates(path) && !path.startsWith('/career-goal/chat') && !path.startsWith('/career-goal/discovery');
const isHome = (path: string) => path === '/dashboard';

/**
 * Keeps the skill evaluation in step with the active CV and career goal.
 * - On Career Goal and Skills Profile, a changed CV or goal starts a new evaluation on its own once the
 *   new skills are rated (the CV review is finished) and goal research is done. While it runs, a banner says so;
 *   otherwise nothing is shown here.
 * - On Home, once the active roadmap was built from older inputs, it points to the roadmap to regenerate it.
 *   Roadmap shows its own out-of-date banner. Other pages show nothing.
 */
export function ChangeBanner() {
 const { token } = useProfile();
 const pathname = usePathname();
 const c = useComparison(token);
 const [roadmap, setRoadmap] = useState<Roadmap>(null);
 const [dismissed, setDismissed] = useState<string | null>(null);
 useEffect(() => { setDismissed(remembered()); }, []);
 useEffect(() => {
  if (!token) return;
  const abort = new AbortController();
  const load = () => { void roadmapApi<NonNullable<Roadmap>>('/dashboard-source', token, undefined, abort.signal).then(value => { if (!abort.signal.aborted) setRoadmap(value); }).catch(() => { if (!abort.signal.aborted) setRoadmap(null); }); };
  load();
  window.addEventListener('focus', load); window.addEventListener(COMPARISON_REFRESH, load);
  return () => { abort.abort(); window.removeEventListener('focus', load); window.removeEventListener(COMPARISON_REFRESH, load); };
 }, [token]);
 // A route change is a fresh look at the workspace: re-read the evaluation and roadmap.
 const lastPath = useRef(pathname);
 useEffect(() => { if (pathname !== lastPath.current) { lastPath.current = pathname; announceInputsChanged(); } }, [pathname]);

 const current = c.current, context = c.context, previous = current?.result;
 const operation = current?.operation;
 const running = !!operation && ['pending', 'running'].includes(operation.status);
 const outdated = !!previous && !!context?.ready && !!context.input_hash && previous.input_hash !== context.input_hash;
 const auto = evaluates(pathname) && outdated && !running && !c.busy && !c.error;
 // New skills must be rated before they are compared with the goal: wait for the CV review and goal research.
 const ready = auto && context!.cv_reviewed !== false && !context!.research_pending && context!.model_available && !operation?.retry_after;
 const hash = context?.input_hash;
 useEffect(() => {
  if (!ready || !hash || attempted.has(hash)) return;
  attempted.add(hash);
  void c.compare();
 }, [ready, hash, c]);
 // Goal research finishing is not announced: re-check while an automatic update waits for it.
 const waitingForResearch = auto && !!context?.research_pending;
 useEffect(() => {
  if (!waitingForResearch) return;
  const timer = setInterval(announceInputsChanged, 10000);
  return () => clearInterval(timer);
 }, [waitingForResearch]);

 if (!current || !context) return null;

 if (showsProgress(pathname)) {
  if (running || (c.busy && outdated)) return <section className="evaluate-banner change-banner" aria-busy="true" aria-labelledby="change-banner-title">
   <span className="evaluate-banner-mark is-busy" aria-hidden="true"/>
   <div><h2 id="change-banner-title">Evaluating the skill gap between you and your career goal…</h2><p role="status">This usually takes a minute or two. You can leave this page and come back.</p></div>
  </section>;
  // An automatic update that failed is not retried on its own; say so once, with a way to retry.
  const failed = outdated && operation?.status === 'failed' && !!hash && attempted.has(hash);
  if (failed || (outdated && c.error)) return <section className="evaluate-banner change-banner" role="alert" aria-labelledby="change-banner-title">
   <span className="evaluate-banner-mark" aria-hidden="true">!</span>
   <div><h2 id="change-banner-title">Your skill gap couldn’t be updated</h2><p>{c.error || friendlyOperationError(operation?.error, 'The evaluation didn’t finish. Try again.')}</p></div>
   <div className="evaluate-banner-actions"><button type="button" className="btn pri" disabled={c.busy || !context.model_available || !!operation?.retry_after} onClick={() => void c.compare()}>Try again</button></div>
  </section>;
  return null;
 }

 if (!isHome(pathname) || !roadmap?.active || !hash || roadmap.active.assessment_hash === hash) return null;
 const key = `roadmap:${hash}`;
 if (dismissed === key) return null;
 const dismiss = () => { setDismissed(key); try { window.sessionStorage.setItem(DISMISSED, key); } catch { /* remembered for this page only */ } };
 return <section className="evaluate-banner change-banner" aria-labelledby="change-banner-title">
  <span className="evaluate-banner-mark" aria-hidden="true">↻</span>
  <div><h2 id="change-banner-title">Your roadmap is out of date</h2><p>Your CV, skills or career goal changed. Regenerate your roadmap to build a plan from your latest information. You can review the new plan before accepting it.</p></div>
  <div className="evaluate-banner-actions"><Link className="btn pri" href="/roadmap">Update roadmap</Link><button type="button" className="btn ghost" onClick={dismiss}>Not now</button></div>
 </section>;
}

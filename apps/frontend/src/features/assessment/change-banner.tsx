"use client";
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { roadmapApi } from '@/lib/api/roadmap';
import { friendlyOperationError } from '@/lib/errors';
import { announceInputsChanged, COMPARISON_REFRESH, useComparison, type Comparison, type InputRevisions } from './comparison';
import '@/styles/evaluate.css';

export type Change = 'cv' | 'goal' | 'cv_and_goal' | 'details';

/** What differs between the inputs an evaluation used and the current ones. */
export function describeChange(before: InputRevisions | undefined, now: InputRevisions | undefined): Change {
 if (!before || !now) return 'details';
 const cv = before.cv_id !== now.cv_id;
 const goal = before.goal_id !== now.goal_id || before.goal_version !== now.goal_version;
 return cv && goal ? 'cv_and_goal' : cv ? 'cv' : goal ? 'goal' : 'details';
}

type Copy = { title: string; source: string; target?: string };
function copy(change: Change, c: Comparison): Copy {
 const job = c.context?.goal?.target_type === 'specific_job';
 const goal = job ? 'job description' : 'career goal';
 const cv = c.context?.cv?.name, role = c.context?.goal?.role;
 if (change === 'cv') return { title: 'Your active CV changed', source: 'CV', target: cv };
 if (change === 'goal') return { title: `Your ${goal} changed`, source: goal, target: role };
 if (change === 'cv_and_goal') return { title: `Your active CV and ${goal} changed`, source: `CV and ${goal}` };
 return { title: 'Your skills or profile changed', source: 'skills and profile details' };
}

type Roadmap = { active: { assessment_hash: string } | null } | null;
type Phase = 'updating' | 'evaluation' | 'roadmap';
const DISMISSED = 'elo:change-banner-dismissed';
const remembered = () => { try { return window.sessionStorage.getItem(DISMISSED); } catch { return null; } };

/**
 * Shown above every workspace page after the active CV, career goal or other evaluated source changes. It says what
 * changed, offers to update the skill evaluation, then points to the roadmap until it is regenerated from the new one.
 * Nothing starts on its own: evaluation and roadmap generation stay explicit, user-started actions.
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
 // Roadmap owns its regeneration banner; full-screen chats keep the viewport for the conversation.
 if (pathname.startsWith('/roadmap') || pathname.startsWith('/career-goal/chat') || pathname.startsWith('/career-goal/discovery')) return null;
 if (!current || !context?.ready || !context.input_hash || !previous) return null;
 const operation = current.operation;
 const running = !!operation && ['pending', 'running'].includes(operation.status);
 const evaluationOld = previous.input_hash !== context.input_hash;
 const hasRoadmap = !!roadmap?.active;
 const roadmapOld = hasRoadmap && roadmap!.active!.assessment_hash !== context.input_hash;
 const phase: Phase | null = evaluationOld ? (running ? 'updating' : 'evaluation') : roadmapOld && !pathname.startsWith('/roadmap') ? 'roadmap' : null;
 if (!phase) return null;
 const key = `${phase}:${context.input_hash}`;
 if (dismissed === key) return null;
 const dismiss = () => { setDismissed(key); try { window.sessionStorage.setItem(DISMISSED, key); } catch { /* remembered for this page only */ } };
 const change = describeChange(previous.inputs as InputRevisions | undefined, context.inputs);
 const text = copy(change, c);
 const roadmapLink = hasRoadmap && !pathname.startsWith('/roadmap') && <Link className="btn" href="/roadmap">Update roadmap</Link>;

 if (phase === 'updating') return <section className="evaluate-banner change-banner" aria-busy="true" aria-labelledby="change-banner-title">
  <span className="evaluate-banner-mark is-busy" aria-hidden="true"/>
  <div><h2 id="change-banner-title">Updating your skill evaluation</h2><p role="status">{text.title}, so elo is evaluating your skills again{context.goal?.role ? ` against ${context.goal.role}` : ''}. This usually takes a minute or two.{hasRoadmap ? ' Your roadmap can be regenerated once it finishes.' : ''}</p></div>
 </section>;

 if (phase === 'roadmap') return <section className="evaluate-banner change-banner" aria-labelledby="change-banner-title">
  <Mark/>
  <div><h2 id="change-banner-title">Your roadmap is out of date</h2><p>Your skill evaluation now uses your latest {text.source}. Regenerate your roadmap so your plan uses it too.</p></div>
  <div className="evaluate-banner-actions"><Link className="btn pri" href="/roadmap">Update roadmap</Link><button type="button" className="btn ghost" onClick={dismiss}>Not now</button></div>
 </section>;

 const failed = operation?.status === 'failed', waiting = !!operation?.retry_after;
 const both = hasRoadmap ? 'skill evaluation and roadmap still use' : 'skill evaluation still uses';
 return <section className="evaluate-banner change-banner" aria-labelledby="change-banner-title" aria-busy={c.busy}>
  <Mark/>
  <div>
   <h2 id="change-banner-title">{text.title}</h2>
   <p>Your {both} your previous {text.source}. Update {hasRoadmap ? 'them' : 'it'} so your scores{hasRoadmap ? ' and plan' : ''} reflect {text.target ?? `your latest ${text.source}`}.</p>
   {context.cv_reviewed === false && <p>Review your CV first so elo understands what you did. Topics you skip are rated by elo from your CV as written.</p>}
   {failed && <p role="alert">{friendlyOperationError(operation.error, 'The evaluation didn’t finish. Try again.')}</p>}
   {c.error && <p role="alert">{c.error}</p>}
   {!context.model_available && <p>Evaluation is unavailable right now. Try again later.</p>}
   {waiting && <p role="status">elo is waiting for its service allowance. Try again in about {operation.retry_after} seconds.</p>}
  </div>
  <div className="evaluate-banner-actions">
   {context.cv_reviewed === false
    ? pathname !== '/cv' && <Link className="btn pri" href="/cv">Review your CV</Link>
    : <button type="button" className="btn pri" disabled={c.busy || !context.model_available || waiting} onClick={() => void c.compare()}>{c.busy ? 'Starting evaluation…' : failed ? 'Try again' : 'Update evaluation'}</button>}
   {context.cv_reviewed !== false && roadmapLink}
   <button type="button" className="btn ghost" onClick={dismiss}>Not now</button>
  </div>
 </section>;
}

function Mark() {
 return <span className="evaluate-banner-mark" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5"/></svg></span>;
}

"use client";
import Link from 'next/link';
import { friendlyOperationError } from '@/lib/errors';
import type { Comparison } from './comparison';
import '@/styles/evaluate.css';

type Page = '/career-goal' | '/cv';
type Step = { title: string; text: string; href: Page; action: string };

/** The one setup step still open, if any. A goal comes first: without it there is nothing to evaluate against. */
function setupStep(c: Comparison): Step | null {
 const context = c.context!;
 const issues = context.issues ?? [];
 if (!context.ready && issues.some(issue => issue.source === 'career' || issue.href === '/career-goal'))
  return { title: 'Set your Career Goal first', text: 'elo needs a goal to evaluate your skills against. Add a job description or explore a direction.', href: '/career-goal', action: 'Set career goal' };
 if (!context.ready)
  return { title: 'Add your skills first', text: 'Upload your CV to your Skills Profile and finish its review. Then you can evaluate your skills here.', href: '/cv', action: 'Go to Skills Profile' };
 if (context.cv_reviewed === false)
  return { title: 'Finish your CV review first', text: 'elo has read your CV, but your skills aren’t confirmed until its review is finished. Then you can evaluate your skills here.', href: '/cv', action: 'Finish CV review' };
 return null;
}

/**
 * Shown on Career Goal and Skills Profile until a current evaluation exists. It is either a pointer to the setup
 * step still open, or the button that starts the evaluation; never both. A current result hides it.
 */
export function EvaluateBanner({ comparison: c, here }: { comparison: Comparison; here: Page }) {
 if (c.error && !c.current) return <section className="evaluate-banner is-setup" role="alert"><div><h2>Your evaluation could not be loaded</h2><p>{c.error}</p></div><div className="evaluate-banner-actions"><button type="button" className="btn" onClick={c.retry}>Reload</button></div></section>;
 if (!c.current || !c.context || c.result) return null;
 // An earlier evaluation from changed inputs is updated automatically by ChangeBanner.
 if (c.current.result && c.context.ready && c.current.result.input_hash !== c.context.input_hash) return null;
 const role = c.context.goal?.role;
 const operation = c.current.operation;
 // Progress is shown once, at the top of the page, by ChangeBanner.
 if (operation && ['pending', 'running'].includes(operation.status)) return null;
 const step = setupStep(c);
 if (step) return <section className="evaluate-banner is-setup" aria-labelledby="evaluate-banner-title">
  <span className="evaluate-banner-mark" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M12 8v5M12 16.5v.01M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18"/></svg></span>
  <div><h2 id="evaluate-banner-title">{step.title}</h2><p>{step.text}</p></div>
  {step.href !== here && <div className="evaluate-banner-actions"><Link className="btn pri" href={step.href}>{step.action}</Link></div>}
 </section>;
 if (c.context.research_pending) return <section className="evaluate-banner is-setup" aria-labelledby="evaluate-banner-title">
  <span className="evaluate-banner-mark is-busy" aria-hidden="true"/>
  <div><h2 id="evaluate-banner-title">elo is still researching your goal</h2><p role="status">You can evaluate your skills{role ? ` against ${role}` : ''} as soon as the research is done.</p></div>
  {here !== '/career-goal' && <div className="evaluate-banner-actions"><Link className="btn" href="/career-goal">View career goal</Link></div>}
 </section>;
 const failed = operation?.status === 'failed', changed = c.current.stale && !!c.current.result;
 const waiting = !!operation?.retry_after;
 return <section className="evaluate-banner" aria-labelledby="evaluate-banner-title" aria-busy={c.busy}>
  <span className="evaluate-banner-mark" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19V5M4 19h16M8 15v-4M12 15V8M16 15v-6"/></svg></span>
  <div>
   <h2 id="evaluate-banner-title">{changed ? 'Your goal or skills changed' : 'Evaluate skills with career goal'}</h2>
   <p>{changed ? 'Evaluate again to update your scores. ' : ''}elo checks which skills {role ?? 'your goal'} needs that you already have, then scores your competence in each out of 10 against the level the role expects.</p>
   {failed && <p role="alert">{friendlyOperationError(operation.error, 'The evaluation didn’t finish. Try again.')}</p>}
   {c.error && <p role="alert">{c.error}</p>}
   {!c.context.model_available && <p>Evaluation is unavailable right now. Try again later.</p>}
   {waiting && <p role="status">elo is waiting for its service allowance. Try again in about {operation.retry_after} seconds.</p>}
  </div>
  <div className="evaluate-banner-actions"><button type="button" className="btn pri" disabled={c.busy || !c.context.model_available || waiting} onClick={() => void c.compare()}>{c.busy ? 'Starting evaluation…' : changed || failed ? 'Evaluate again' : 'Evaluate skills'}</button></div>
 </section>;
}

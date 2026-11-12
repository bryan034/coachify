"use client";
import Link from 'next/link';
import type { Comparison } from './comparison';
import { formatDateTime } from '@/lib/format';
import { friendlyOperationError } from '@/lib/errors';

const labels = { missing: 'Not evaluated', current: 'Up to date', outdated: 'Outdated', unavailable: 'Unable to verify' };
const reasons: Record<string, string> = {
 cv_changed: 'Your selected CV or its contents changed.', evidence_changed: 'Your reviewed skills or profile evidence changed.',
 goal_changed: 'Your career goal changed.', research_changed: 'Career research changed or expired.',
 registry_changed: 'Skill matching was updated.', evaluation_update_required: 'The saved evaluation needs an update.',
 inputs_not_ready: 'Your CV or career goal is not ready.',
};

/** Status and explicit commands for the same saved evaluation used by Skills Profile and Roadmap. */
export function EvaluationStatusPanel({ comparison: c, actions = false, disabled = false }: { comparison: Comparison; actions?: boolean; disabled?: boolean }) {
 const status = c.current?.evaluation;
 if (!status) return c.error && actions ? <section className="roadmap-notice" role="alert"><p>Unable to verify your skill evaluation.</p><button className="btn" onClick={c.retry}>Check evaluation</button></section> : null;
 const running = status.processing === 'evaluating';
 const needsUpdate = status.freshness === 'missing' || status.freshness === 'outdated';
 const canEvaluate = c.context?.ready && c.context.cv_reviewed !== false && c.context.model_available;
 return <section className="evaluate-banner" aria-label="Skill evaluation status" aria-busy={running || c.busy}>
  <div>
   <p role="status"><strong>Skill evaluation: {c.error ? 'Unable to verify' : labels[status.freshness]}</strong>{running ? ' · Evaluating' : ''}</p>
   {status.evaluated_at && <p className="small">Last evaluated {formatDateTime(status.evaluated_at)}{status.completeness === 'partial' ? ' · Partial evaluation' : ''}</p>}
   {status.reasons.map(reason => <p key={reason} className="small">{reasons[reason] ?? 'Your evaluation inputs changed.'}</p>)}
   {running && <p>Your evaluation is processing. You can leave this page and return.</p>}
   {status.processing === 'failed' && <p role="alert">{friendlyOperationError(c.current?.operation?.error, 'The evaluation did not finish. Your saved result is retained.')}</p>}
   {c.error && <p role="alert">{c.error}</p>}
  </div>
  {actions && !running && <div className="evaluate-banner-actions">
   {needsUpdate && c.context?.cv_reviewed === false ? <Link className="btn pri" href="/cv">Finish CV review</Link> : needsUpdate && <button className="btn pri" disabled={disabled || c.busy || !canEvaluate || !!c.current?.operation?.retry_after} onClick={() => void c.compare()}>{c.busy ? 'Starting evaluation…' : status.freshness === 'missing' ? 'Evaluate skills' : 'Update evaluation'}</button>}
   {(status.freshness === 'unavailable' || c.error) && <button className="btn" onClick={c.retry}>Check evaluation</button>}
  </div>}
 </section>;
}

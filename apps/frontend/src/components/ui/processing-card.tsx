import type { ReactNode } from 'react';

export type ProcessingStep = { label: string; state: 'done' | 'now' | 'next'; note?: string };

/** Percent complete from known step states; a running step counts as half, so it never claims more than is known. */
export function stepPercent(steps: ProcessingStep[]) {
 if (!steps.length) return 0;
 const score = steps.reduce((sum, step) => sum + (step.state === 'done' ? 1 : step.state === 'now' ? 0.5 : 0), 0);
 return Math.round((score / steps.length) * 100);
}

const defaultNote = { done: 'Done', now: 'Now', next: 'Up next' } as const;

/** Progress card shared by the Career Goal and Roadmap processing screens: percent, bar and a short step list. */
export function ProcessingCard({ title, intro, progressLabel, steps, percent = stepPercent(steps), dark = false, footer, children, className = '' }: {
 title: string; intro?: string; progressLabel: string; steps: ProcessingStep[]; percent?: number; dark?: boolean; footer?: ReactNode; children?: ReactNode; className?: string;
}) {
 const labelId = `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-progress`;
 return <section className={`processing-card${dark ? ' dark' : ''} ${className}`.trim()} aria-label={title} aria-busy="true">
  <h2>{title}</h2>
  {intro && <p className="processing-intro">{intro}</p>}
  <div className="processing-progress">
   <div className="processing-progress-head"><p id={labelId}>{progressLabel}</p><p className="processing-percent">{percent}%<span> complete</span></p></div>
   <div className="processing-bar" role="progressbar" aria-labelledby={labelId} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={`${percent}% complete`}><i style={{ width: `${percent}%` }} /></div>
  </div>
  <ol className="processing-steps">{steps.map(step => <li key={step.label} className={step.state} aria-current={step.state === 'now' ? 'step' : undefined}>
   <span className="processing-mark" aria-hidden="true">{step.state === 'done' && <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2"><path d="M5 12l5 5 9-10" /></svg>}</span>
   <span><strong>{step.label}</strong><small>{step.note ?? defaultNote[step.state]}</small></span></li>)}</ol>
  {footer && <div className="processing-footer" role="status">{footer}</div>}
  {children}
 </section>;
}

/** Decorative placeholder bars shown while the real content is still being prepared. */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
 const widths = [36, 28, 42, 32, 38];
 return <div className="skeleton-rows" aria-hidden="true">{Array.from({ length: rows }, (_, index) => <div key={index} className="skeleton-row"><span className="sk dot" /><span className="sk" style={{ width: `${widths[index % widths.length]}%` }} /><span className="sk small" /><span className="sk pill" /></div>)}</div>;
}

export function SkeletonRoad({ stops = 3 }: { stops?: number }) {
 const widths = [[34, 72], [42, 64], [30, 68]];
 return <ol className="skeleton-road" aria-hidden="true">{Array.from({ length: stops }, (_, index) => <li key={index}><div className="skeleton-rail"><i /></div><div className="skeleton-stop"><span className="sk" style={{ width: `${widths[index % 3][0]}%` }} /><span className="sk thin" style={{ width: `${widths[index % 3][1]}%` }} /></div></li>)}</ol>;
}

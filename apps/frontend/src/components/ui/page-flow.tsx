import Link from 'next/link';
import type { ReactNode } from 'react';

const steps = [
 { href: '/career-goal', label: 'Career Goal' },
 { href: '/cv', label: 'Skills Profile' },
 { href: '/roadmap', label: 'Roadmap' },
];

export function PageFlow({ current, children }: { current: '/career-goal' | '/cv'; children: ReactNode }) {
 return <div className="ws-connect">
  <nav className="ws-flow" aria-label="How the pages connect">{steps.map((step, index) => <span key={step.href} style={{ display: 'contents' }}>
   {index > 0 && <span aria-hidden="true">→</span>}
   <Link href={step.href} className={step.href === current ? 'on' : undefined} aria-current={step.href === current ? 'page' : undefined}>{step.label}</Link>
  </span>)}</nav>
  <p>{children}</p>
 </div>;
}

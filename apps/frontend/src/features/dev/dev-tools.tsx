"use client";
import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { useProfile } from '@/features/profile/profile-provider';
import { forgetApplyVisits } from '@/features/jobs/application-check';
import { forgetExtraction } from '@/features/career/pending-extraction';
import { resetWorkspace, switchAccountType, type AccountType, type ResetPrefix } from '@/lib/api/dev-tools';
const PLAN_LABEL: Record<AccountType, string> = { free: 'Free', premium: 'Premium' };
type PageReset = { name: string; prefixes: ResetPrefix[]; deletes: string; forget?: 'jobs' | 'career' };
const PAGE_RESETS: { match: (path: string) => boolean; reset: PageReset }[] = [
  { match: path => path === '/cv' || path.startsWith('/cv/'), reset: { name: 'Skills Profile', prefixes: ['cv', 'profile', 'assessments'], deletes: 'your CVs and uploaded files, manual skills, skill ratings and assessments' } },
  { match: path => path === '/career-goal' || path.startsWith('/career-goal/'), reset: { name: 'Career goal', prefixes: ['career'], deletes: 'your career goal, its chats and research, and this browser’s pending goal extraction', forget: 'career' } },
  { match: path => path === '/roadmap' || path.startsWith('/roadmap/') || path === '/settings/roadmap', reset: { name: 'Roadmap', prefixes: ['roadmaps'], deletes: 'your roadmaps, study plan, progress and adviser chat' } },
  { match: path => path === '/jobs' || path.startsWith('/jobs/'), reset: { name: 'Jobs', prefixes: ['jobs'], deletes: 'your tracked applications and this browser’s remembered apply visits', forget: 'jobs' } },
];
function pageReset(path: string | null): PageReset | null {
  return PAGE_RESETS.find(item => path && item.match(path))?.reset ?? null;
}
export function DevTools() {
  const { developmentToolsEnabled, token, account } = useProfile();
  const page = pageReset(usePathname());
  const [step, setStep] = useState<'idle' | 'confirm' | 'working' | 'switching'>('idle');
  const [target, setTarget] = useState<'all' | 'page'>('all');
  const [error, setError] = useState('');
  if (!developmentToolsEnabled || !token || !account) return null;
  const plan: AccountType = account.account_type === 'premium' ? 'premium' : 'free';
  const other: AccountType = plan === 'premium' ? 'free' : 'premium';
  const switchPlan = async () => {
    setStep('switching'); setError('');
    try { await switchAccountType(token, other); }
    catch (cause) { setError((cause as Error).message); setStep('idle'); return; }
    window.location.reload();
  };
  const run = async (scope: PageReset | null) => {
    setStep('working'); setTarget(scope ? 'page' : 'all'); setError('');
    const { failed } = await resetWorkspace(token, scope?.prefixes);
    if (failed.length) { setError(`Could not reset: ${failed.map(item => `${item.prefix} (${item.message})`).join(', ')}.`); setStep('idle'); return; }
    if (!scope || scope.forget === 'jobs') forgetApplyVisits(account.id);
    if (!scope || scope.forget === 'career') forgetExtraction();
    if (scope) window.location.reload(); else window.location.assign('/dashboard');
  };
  return <div className="dev-tools" role="region" aria-label="Development tools">
    <span className="chip">Development</span>
    <span className="small" aria-live="polite">Account: <strong>{PLAN_LABEL[plan]}</strong></span>
    {(step === 'idle' || step === 'switching') && <>
      <button type="button" className="btn ghost sm" disabled={step === 'switching'} onClick={switchPlan}>{step === 'switching' ? 'Switching…' : `Switch to ${PLAN_LABEL[other]}`}</button>
      <button type="button" className="btn ghost sm" disabled={step === 'switching'} onClick={() => setStep('confirm')}>Start afresh</button>
    </>}
    {(step === 'confirm' || step === 'working') && <><span className="small">
      <strong>Everything</strong> deletes your career goal, CVs, assessments, roadmaps, applications, manual skills and this browser’s pending drafts.
      {page && <> <strong>{page.name} only</strong> deletes {page.deletes}.</>} Your account, plan and profile stay.</span>
      <button type="button" className="btn sm" disabled={step === 'working'} onClick={() => run(null)}>{step === 'working' && target === 'all' ? 'Resetting…' : 'Yes, delete everything'}</button>
      {page && <button type="button" className="btn sm" disabled={step === 'working'} onClick={() => run(page)}>{step === 'working' && target === 'page' ? 'Resetting…' : `Reset ${page.name} only`}</button>}
      <button type="button" className="btn ghost sm" disabled={step === 'working'} onClick={() => setStep('idle')}>Cancel</button></>}
    {error && <span className="small" role="alert">{error}</span>}
  </div>;
}

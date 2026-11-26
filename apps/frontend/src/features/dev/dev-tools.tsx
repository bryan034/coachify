"use client";
import { useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { forgetApplyVisits } from '@/features/jobs/application-check';
import { forgetExtraction } from '@/features/career/pending-extraction';
import { resetWorkspace, switchAccountType, type AccountType } from '@/lib/api/dev-tools';
const PLAN_LABEL: Record<AccountType, string> = { free: 'Free', premium: 'Premium' };
export function DevTools() {
  const { developmentToolsEnabled, token, account } = useProfile();
  const [step, setStep] = useState<'idle' | 'confirm' | 'working' | 'switching'>('idle');
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
  const run = async () => {
    setStep('working'); setError('');
    const { failed } = await resetWorkspace(token);
    if (failed.length) { setError(`Could not reset: ${failed.map(item => `${item.prefix} (${item.message})`).join(', ')}.`); setStep('idle'); return; }
    forgetApplyVisits(account.id);
    forgetExtraction();
    window.location.assign('/dashboard');
  };
  return <div className="dev-tools" role="region" aria-label="Development tools">
    <span className="chip">Development</span>
    <span className="small" aria-live="polite">Account: <strong>{PLAN_LABEL[plan]}</strong></span>
    {(step === 'idle' || step === 'switching') && <>
      <button type="button" className="btn ghost sm" disabled={step === 'switching'} onClick={switchPlan}>{step === 'switching' ? 'Switching…' : `Switch to ${PLAN_LABEL[other]}`}</button>
      <button type="button" className="btn ghost sm" disabled={step === 'switching'} onClick={() => setStep('confirm')}>Start afresh</button>
    </>}
    {(step === 'confirm' || step === 'working') && <><span className="small">Delete your career goal, CVs, assessments, roadmaps, applications, manual skills and this browser’s pending drafts? Your account, plan and profile stay.</span>
      <button type="button" className="btn sm" disabled={step === 'working'} onClick={run}>{step === 'working' ? 'Resetting…' : 'Yes, delete everything'}</button>
      <button type="button" className="btn ghost sm" disabled={step === 'working'} onClick={() => setStep('idle')}>Cancel</button></>}
    {error && <span className="small" role="alert">{error}</span>}
  </div>;
}

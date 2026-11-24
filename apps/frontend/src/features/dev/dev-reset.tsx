"use client";
import { useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { resetWorkspace } from '@/lib/api/dev-reset';
export function DevReset() {
  const { developmentToolsEnabled, token } = useProfile();
  const [step, setStep] = useState<'idle' | 'confirm' | 'working'>('idle');
  const [error, setError] = useState('');
  if (!developmentToolsEnabled || !token) return null;
  const run = async () => {
    setStep('working'); setError('');
    const { failed } = await resetWorkspace(token);
    if (failed.length) { setError(`Could not reset: ${failed.map(item => `${item.prefix} (${item.message})`).join(', ')}.`); setStep('idle'); return; }
    window.location.assign('/dashboard');
  };
  return <div className="dev-reset" role="region" aria-label="Development tools">
    <span className="chip">Development</span>
    {step === 'idle' && <button type="button" className="btn ghost sm" onClick={() => setStep('confirm')}>Start afresh</button>}
    {step !== 'idle' && <><span className="small">Delete your career goal, CVs, assessments, roadmaps, applications and manual skills? Your account and profile stay.</span>
      <button type="button" className="btn sm" disabled={step === 'working'} onClick={run}>{step === 'working' ? 'Resetting…' : 'Yes, delete everything'}</button>
      <button type="button" className="btn ghost sm" disabled={step === 'working'} onClick={() => setStep('idle')}>Cancel</button></>}
    {error && <span className="small" role="alert">{error}</span>}
  </div>;
}

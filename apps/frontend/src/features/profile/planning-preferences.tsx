"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, profileApi } from '@/lib/api/profile';
import { useProfile } from './profile-provider';
import type { AvailabilityPeriod, PlanningInputs, Profile } from './types';
import { SectionTitle } from '@/components/ui/workspace-ui';

type PeriodDraft = { id?: string; start_date: string; end_date: string; hours: string };
export function deviceTimeZone() {
 const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
 if (!zone) throw new Error('Your device time zone is unavailable. Check your device settings and retry.');
 return zone;
}
function numericHours(text: string, allowZero: boolean) {
 if (!text.trim()) throw new Error('Enter available hours per week.');
 const hours = Number(text);
 if (!Number.isFinite(hours) || hours > 168 || (allowZero ? hours < 0 : hours <= 0))
  throw new Error(allowZero ? 'Enter hours from 0 to below your normal weekly budget.' : 'Normal weekly hours must be greater than 0 and no more than 168.');
 return hours;
}
export function PlanningPreferences() {
 const { profile, token, loading, configError, setProfile } = useProfile();
 const [applicationDate, setApplicationDate] = useState('');
 const [hours, setHours] = useState('');
 const [dateDirty, setDateDirty] = useState(false);
 const [hoursDirty, setHoursDirty] = useState(false);
 const [period, setPeriod] = useState<PeriodDraft | null>(null);
 const [error, setError] = useState('');
 const [message, setMessage] = useState('');
 const [busy, setBusy] = useState(false);
 const [conflict, setConflict] = useState(false);
 const [snapshot, setSnapshot] = useState<PlanningInputs | null>(null);
 const [snapshotError, setSnapshotError] = useState('');
 const [snapshotRetry, setSnapshotRetry] = useState(0);
 const pending = useRef<{ signature: string; key: string } | null>(null);
 const active = useRef<AbortController | null>(null);
 useEffect(() => {
  setDateDirty(false); setHoursDirty(false); setPeriod(null); setError(''); setMessage(''); setConflict(false); setBusy(false); pending.current = null;
  return () => active.current?.abort();
 }, [token]);
 useEffect(() => {
  if (!dateDirty) setApplicationDate(profile?.application_date || '');
  if (!hoursDirty) setHours(profile?.weekly_hours == null ? '' : String(profile.weekly_hours));
 }, [profile, dateDirty, hoursDirty]);
 const refreshSnapshot = useCallback(() => setSnapshotRetry(n => n + 1), []);
 useEffect(() => {
  setSnapshot(null); setSnapshotError('');
  if (!profile) return;
  const controller = new AbortController();
  try {
   profileApi<PlanningInputs>(`/planning-inputs?time_zone=${encodeURIComponent(deviceTimeZone())}`, { signal: controller.signal }, token)
    .then(setSnapshot).catch(e => { if (e.name !== 'AbortError') setSnapshotError(e.message || 'Planning checks could not load.'); });
  } catch(e) { setSnapshotError((e as Error).message); }
  return () => controller.abort();
 }, [profile, token, snapshotRetry]);
 // Recheck elapsed deadlines after a long-open tab crosses midnight or changes zone.
 useEffect(() => {
  const timer = window.setInterval(refreshSnapshot, 60_000);
  window.addEventListener('focus', refreshSnapshot);
  return () => { clearInterval(timer); window.removeEventListener('focus', refreshSnapshot); };
 }, [refreshSnapshot]);
 const locked = busy || loading || !profile?.occupational_status || !!configError;
 function edit() { setMessage(''); setError(''); }
 async function mutate(method: string, path: string, body: object | undefined, success: string, done: () => void) {
  if (!profile || busy) return;
  setBusy(true); setError(''); setMessage('');
  const signature = JSON.stringify({ method, path, body });
  if (pending.current?.signature !== signature) pending.current = { signature, key: crypto.randomUUID() };
  const controller = new AbortController(); active.current = controller;
  try {
   const result = await profileApi<Profile>(path, { method, signal: controller.signal,
    headers: { 'Idempotency-Key': pending.current.key }, ...(body ? { body: JSON.stringify(body) } : {}) }, token);
   if (controller.signal.aborted) return;
   pending.current = null; setConflict(false); done(); setProfile(result); setMessage(success);
  } catch(e) {
   if (controller.signal.aborted) return;
   setConflict(e instanceof ApiError && [404,409].includes(e.status));
   setError((e as Error).message || 'Saving failed. Your changes are retained; retry.');
  } finally { if (!controller.signal.aborted) setBusy(false); }
 }
 function saveDeadline(event: FormEvent) {
  event.preventDefault();
  try {
   if (!applicationDate) throw new Error('Choose an intended application date.');
   const zone = deviceTimeZone();
   void mutate('PATCH','',{ expected_version: profile!.version, application_date: applicationDate, time_zone: zone },'Application date saved.',()=>setDateDirty(false));
  } catch(e) { setError((e as Error).message); }
 }
 function saveHours(event: FormEvent) {
  event.preventDefault();
  try { void mutate('PATCH','',{ expected_version: profile!.version, weekly_hours: numericHours(hours,false) },'Weekly availability saved.',()=>setHoursDirty(false)); }
  catch(e) { setError((e as Error).message); }
 }
 function savePeriod(event: FormEvent) {
  event.preventDefault(); if (!period || !profile) return;
  try {
   const path = `/availability-periods${period.id ? `/${period.id}` : ''}`;
   void mutate(period.id ? 'PATCH' : 'POST', path, { expected_version: profile.version,
    start_date: period.start_date, end_date: period.end_date, weekly_hours: numericHours(period.hours,true) },'Reduced availability saved.',()=>setPeriod(null));
  } catch(e) { setError((e as Error).message); }
 }
 async function loadLatest() {
  setBusy(true);
  const controller = new AbortController(); active.current = controller;
  try { const latest = await profileApi<Profile>('',{signal:controller.signal},token); if(controller.signal.aborted)return; setProfile(latest); setConflict(false); pending.current=null; setError(''); setMessage('Latest saved values loaded. Your planning drafts are retained; review them before saving.'); }
  catch(e) { if(!controller.signal.aborted)setError((e as Error).message); }
  finally { if(!controller.signal.aborted)setBusy(false); }
 }
 function editPeriod(row: AvailabilityPeriod) {
  edit(); setPeriod({ id: row.id, start_date: row.start_date, end_date: row.end_date, hours: String(row.weekly_hours) });
 }
 return <section id="planning-preferences" className="planning-preferences" aria-label="Planning preferences">
  <SectionTitle title="Planning preferences"><span className="small">Optional · available to all occupational statuses</span></SectionTitle>
  <p className="small planning-description">Set a deadline and a realistic pace. These details are saved for future roadmap planning; they do not generate a roadmap.</p>
  {!profile?.occupational_status && <p className="notice">Save your occupational status above before adding planning preferences.</p>}
  <div className="grid c2">
   <form className="card pad planning-card" onSubmit={saveDeadline}><h3>Intended application date</h3><p className="small">The date you want to apply for your target role. Uses your device’s local time zone.</p>
    <label>Application date<input type="date" value={applicationDate} disabled={locked} onChange={e=>{setApplicationDate(e.target.value);setDateDirty(true);edit();}}/></label>
    <div className="row"><button className="btn pri" disabled={locked} type="submit">Save application date</button><button className="btn ghost" type="button" disabled={busy || !dateDirty} onClick={()=>{setDateDirty(false);edit();}}>Cancel date changes</button></div>
   </form>
   <form className="card pad planning-card" onSubmit={saveHours}><h3>Normal weekly availability</h3><p className="small">Your normal budget, in hours per week. Decimals are allowed; no budget is assumed.</p>
    <label>Normal hours per week<input type="number" min="0" max="168" step="any" value={hours} disabled={locked} onChange={e=>{setHours(e.target.value);setHoursDirty(true);edit();}}/></label>
    <div className="row"><button className="btn pri" disabled={locked} type="submit">Save weekly availability</button><button className="btn ghost" type="button" disabled={busy || !hoursDirty} onClick={()=>{setHoursDirty(false);edit();}}>Cancel hours changes</button></div>
   </form>
  </div>
  <div className="card pad planning-card"><div className="row between"><h3>Reduced-availability periods</h3><button className="btn ghost sm" type="button" disabled={locked || profile?.weekly_hours == null} onClick={()=>{setPeriod({start_date:'',end_date:'',hours:''});edit();}}>Add reduced period</button></div>
   <p className="small">Dates include both endpoints and use Asia/Singapore. A period’s weekly hours replace your normal rate; 0 means no capacity. Overlapping periods are not allowed.</p>
   {profile?.weekly_hours == null && <p className="notice">Save normal weekly availability to add periods.</p>}
   {!(profile?.availability_periods?.length) && <p className="small">No reduced periods saved.</p>}
   <ul className="period-list">{profile?.availability_periods?.map(row=><li key={row.id} className="row"><div className="grow"><strong>{row.start_date} → {row.end_date}</strong><p className="small">{row.weekly_hours} hours/week · inclusive · Asia/Singapore</p>{snapshot?.issues.some(i=>i.period_ids?.includes(row.id)) && <p className="error">Review this period: its hours must be below your normal budget.</p>}</div><button className="btn ghost sm" type="button" disabled={locked} onClick={()=>editPeriod(row)}>Edit period {row.start_date}</button><button className="btn ghost sm" type="button" disabled={locked} onClick={()=>void mutate('DELETE',`/availability-periods/${row.id}?expected_version=${profile.version}`,undefined,'Reduced period removed.',()=>{if(period?.id===row.id)setPeriod(null);})}>Delete period {row.start_date}</button></li>)}</ul>
   {period && <form aria-label="Reduced period editor" className="period-editor" onSubmit={savePeriod}><h4>{period.id?'Edit reduced period':'Add reduced period'}</h4><div className="grid c3"><label>Start date (Singapore)<input type="date" required disabled={locked} value={period.start_date} onChange={e=>{setPeriod({...period,start_date:e.target.value});edit();}}/></label><label>End date (Singapore)<input type="date" required disabled={locked} value={period.end_date} onChange={e=>{setPeriod({...period,end_date:e.target.value});edit();}}/></label><label>Reduced hours per week<input type="number" required min="0" max="168" step="any" disabled={locked} value={period.hours} onChange={e=>{setPeriod({...period,hours:e.target.value});edit();}}/></label></div><div className="row"><button className="btn pri" type="submit" disabled={locked}>Save reduced period</button><button className="btn ghost" type="button" disabled={busy} onClick={()=>{setPeriod(null);edit();}}>Cancel period changes</button></div></form>}
  </div>
  {busy && <p role="status">Saving planning preferences…</p>}
  {error && <p role="alert" className="error">{error}</p>}
  {message && <p role="status" className="success">{message}</p>}
  {conflict && <button className="btn ghost" type="button" disabled={busy} onClick={()=>void loadLatest()}>Load latest saved values (keep planning drafts)</button>}
  {snapshotError && <p role="alert" className="error">{snapshotError} <button type="button" className="btn ghost sm" onClick={refreshSnapshot}>Retry planning checks</button></p>}
  {snapshot && <div className="planning-readiness" aria-label="Planning checks"><h4>{snapshot.ready?'Planning inputs are ready':'Before generating a future roadmap'}</h4><ul>{snapshot.issues.map((issue,i)=><li key={i}>{issue.message}</li>)}</ul><p className="small">Saved profile version {snapshot.profile_version} · planning revision {snapshot.planning_revision}. Weekly hours are spread evenly across seven calendar days; reduced rates apply only on covered dates.</p></div>}
 </section>;
}

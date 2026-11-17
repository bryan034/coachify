"use client";
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { roadmapApi } from '@/lib/api/roadmap';
import type { PlannerConfig, Workspace } from '@/features/roadmap/types';
import { days } from '@/features/roadmap/settings-panel';
import { errorText } from '@/lib/errors';
import { applyAppearance, type Appearance } from './theme-preference';
import '@/styles/roadmap.css';

export function SettingsPage() {
 const [mode, setMode] = useState<Appearance>('system');
 useEffect(() => {try {const saved = localStorage.getItem('elo-appearance'); if (saved === 'light' || saved === 'dark') setMode(saved);} catch {}}, []);
 return <section className="roadmap-adviser settings-page"><h1>Settings</h1><section className="review-card"><h2>Appearance</h2><label>Colour mode <select value={mode} onChange={e => {const next = e.target.value as Appearance; setMode(next); try {localStorage.setItem('elo-appearance', next);} catch {} applyAppearance(next); window.dispatchEvent(new Event('elo-appearance'));}}><option value="system">Follow system</option><option value="light">Light</option><option value="dark">Dark</option></select></label><p className="small">Follow system switches automatically when your device changes appearance. This preference is saved on this browser.</p></section><Link className="review-card settings-destination" href="/settings/roadmap"><h2>Roadmap</h2><p>Set your planning week, session limits and unfinished-work preferences.</p></Link></section>;
}
export function RoadmapSettingsPage() {
 const { token } = useProfile(); const [workspace,setWorkspace] = useState<Workspace | null>(null); const [draft,setDraft] = useState<PlannerConfig | null>(null); const [error,setError] = useState(''); const [busy,setBusy] = useState(false); const [saved,setSaved] = useState(false);
 async function load() {if (!token) return; try {const value = await roadmapApi<Workspace>('/workspace', token); setWorkspace(value); setDraft(value.planner.config); setError('');} catch (e) {setError(errorText(e, 'Settings could not be loaded.'));}}
 useEffect(() => {void load();}, [token]); // eslint-disable-line react-hooks/exhaustive-deps
 const update = (patch: Partial<PlannerConfig>) => {setDraft(d => d ? {...d,...patch} : d);setSaved(false);};
 async function save() {if (!workspace || !draft || !token) return; setBusy(true);setError('');try {const value = await roadmapApi<Workspace>('/planner/config', token, {config:draft, expected_version:workspace.version, mutation_id:crypto.randomUUID()});setWorkspace(value);setDraft(value.planner.config);setSaved(true);} catch(e) {setError(errorText(e,'Settings could not be saved. Reload to review the latest values.'));} finally {setBusy(false);}}
 return <section className="roadmap-adviser settings-page"><Link href="/settings" className="text-link">Settings</Link><h1>Roadmap settings</h1><p>Defaults apply until you change them. Schedule changes apply to future planning; accepted tasks stay saved.</p>{error && <div role="alert"><p>{error}</p><button className="btn ghost" onClick={() => void load()}>Reload settings</button></div>}{!draft ? <p role="status">Loading settings…</p> : <form onSubmit={e => {e.preventDefault();void save();}}><fieldset disabled={busy} className="review-card settings-grid"><legend>Weekly planning</legend>
 <label>Week starts on <select value={draft.week_start_day ?? 0} onChange={e => update({week_start_day:Number(e.target.value)})}>{days.map((d,i)=><option key={d} value={i}>{d}</option>)}</select></label>
 <label>Plan next week on <select value={draft.plan_day ?? ''} onChange={e => update({plan_day:e.target.value === '' ? null : Number(e.target.value)})}><option value="">Last day of my week</option>{days.map((d,i)=><option key={d} value={i}>{d}</option>)}</select></label><p className="small">This week's progress and feedback curate the next plan. Planning opens on this day or when all tasks are complete; missed planning remains available.</p>
 <label>Longest session (minutes) <input type="number" required min={15} max={480} value={draft.preferred_session_minutes} onChange={e => update({preferred_session_minutes:Number(e.target.value)})}/></label>
 <label>Break minutes per hour <input type="number" required min={0} max={30} value={draft.break_minutes_per_hour ?? 10} onChange={e => update({break_minutes_per_hour:Number(e.target.value)})}/></label>
 <label>Shortest session (minutes) <input type="number" required min={15} max={120} value={draft.min_session_minutes ?? 25} onChange={e => update({min_session_minutes:Number(e.target.value)})}/></label>
 <label>Daily study limit (minutes, blank for none) <input type="number" min={15} max={1440} value={draft.max_daily_minutes ?? ''} onChange={e => update({max_daily_minutes:e.target.value ? Number(e.target.value) : null})}/></label>
 <label>Notice before a session (minutes) <input type="number" required min={0} max={1440} value={draft.lead_minutes ?? 0} onChange={e => update({lead_minutes:Number(e.target.value)})}/></label>
 <label>Rest days per week <input type="number" required min={0} max={6} value={draft.rest_days_per_week ?? 0} onChange={e => update({rest_days_per_week:Number(e.target.value)})}/></label>
 <label><input type="checkbox" checked={draft.apply_reduced_periods ?? true} onChange={e => update({apply_reduced_periods:e.target.checked})}/> Reduce targets during reduced availability</label>
 <label>Unfinished work default <select value={draft.unfinished_default ?? 'ask'} onChange={e => update({unfinished_default:e.target.value as PlannerConfig['unfinished_default']})}><option value="ask">Review each week</option><option value="carry">Propose carry forward</option><option value="defer">Propose defer</option></select></label>
 <label>Carry-over limit (minutes, blank for half your weekly target) <input type="number" min={0} max={10080} value={draft.max_carry_minutes ?? ''} onChange={e => update({max_carry_minutes:e.target.value ? Number(e.target.value) : null})}/></label>
 <label>Planning timezone <input required value={draft.time_zone} onChange={e => update({time_zone:e.target.value})}/></label>
 <p className="small">Dates, weekly hours, study blocks and blocked-out times are on the <Link href="/roadmap">roadmap planner</Link>.</p><div className="plan-actions"><button className="btn primary" type="submit">{busy ? 'Saving…' : 'Save settings'}</button>{saved && <span role="status">Settings saved</span>}</div></fieldset></form>}</section>;
}

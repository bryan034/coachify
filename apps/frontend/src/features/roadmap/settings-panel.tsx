"use client";
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import { groupSkills } from '@/lib/skill-groups';
import { roadmapApi } from '@/lib/api/roadmap';
import { BlackoutRules, dailyBlackout } from './blackout-rules';
import type { Duration, LearningFocus, PlannerConfig, Runway, StudyBlock, Workspace } from './types';

export const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
export const hours = (minutes: number) => `${Number((minutes / 60).toFixed(2))} h`;
export const longDate = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-SG', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const count = (value: number, noun: string) => `${value} ${noun}${value === 1 ? '' : 's'}`;
const focuses: [LearningFocus, string][] = [['interview_practice', 'Interview practice'], ['portfolio_work', 'Portfolio work'], ['hands_on_projects', 'Hands-on projects'], ['courses_and_reading', 'Courses and reading'], ['certification', 'Certification'], ['networking', 'Networking']];

/** The unsaved settings draft. All numbers shown beside it come from the backend's runway. */
export function useSettingsDraft(workspace: Workspace | null, token: string) {
 const planner = workspace?.planner;
 const [draft, setDraft] = useState<PlannerConfig | null>(null);
 const [preview, setPreview] = useState<{ source: PlannerConfig; runway: Runway } | null>(null);
 const [previewError, setPreviewError] = useState('');
 const config = draft || planner?.config || null;
 useEffect(() => {
  if (!draft) { setPreview(null); setPreviewError(''); return; }
  const controller = new AbortController();
  const timer = setTimeout(() => {
   roadmapApi<Runway>('/planner/runway', token, { config: draft }, controller.signal)
    .then(runway => { setPreview({ source: draft, runway }); setPreviewError(''); })
    .catch(failure => { if (!controller.signal.aborted) setPreviewError(failure instanceof Error ? failure.message : 'Your runway could not be calculated.'); });
  }, 250);
  return () => { clearTimeout(timer); controller.abort(); };
 }, [draft, token]);
 const current = preview && preview.source === draft ? preview.runway : null;
 return {
  config, dirty: !!draft, previewError,
  runway: draft ? current || preview?.runway || planner?.runway || null : planner?.runway || null,
  calculating: !!draft && !current && !previewError,
  update: (patch: Partial<PlannerConfig>) => { if (config) setDraft({ ...config, ...patch }); },
  clear: () => setDraft(null),
 };
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
 return <label className="settings-field"><span>{label}</span>{children}</label>;
}

/** A section of the planner, as a stop on the route: its dot and tag say whether it still needs filling in. */
function Stop({ label, required, filled, frozen, children }: { label: string; required: boolean; filled: boolean; frozen: boolean; children: React.ReactNode }) {
 return <div className={`planner-stop${filled ? ' filled' : required ? ' needed' : ''}`}>
  <i aria-hidden="true" />
  <fieldset className="settings-section" disabled={frozen}>
   <legend>{label} <span className="settings-need">{filled ? 'Done' : required ? 'Required' : 'Optional'}</span></legend>
   {children}
  </fieldset>
 </div>;
}

function BlockRow({ block, index, change, remove }: { block: StudyBlock; index: number; change: (patch: Partial<StudyBlock>) => void; remove: () => void }) {
 const name = `Block ${index + 1}`;
 return <div className="study-block">
  <label><span aria-hidden="true">Day</span><select aria-label={`${name} day`} value={block.day} onChange={e => change({ day: Number(e.target.value) })}>{days.map((day, i) => <option key={day} value={i}>{day}</option>)}</select></label>
  <label><span aria-hidden="true">Starts</span><input aria-label={`${name} start time`} type="time" value={block.start_time} onChange={e => { if (e.target.value) change({ start_time: e.target.value }); }} /></label>
  <label><span aria-hidden="true">Minutes</span><input aria-label={`${name} minutes`} type="number" min={15} max={480} step={5} value={block.duration_minutes} onChange={e => change({ duration_minutes: Math.round(Number(e.target.value)) })} /></label>
  <label><span aria-hidden="true">Type</span><select aria-label={`${name} type`} value={block.kind} onChange={e => change({ kind: e.target.value as StudyBlock['kind'] })}><option value="preferred">Preferred</option><option value="backup">Backup</option></select></label>
  <button type="button" className="btn ghost" aria-label={`Remove block ${index + 1}`} onClick={remove}>Remove</button>
 </div>;
}

export function SettingsPanel({ workspace, settings, partial, setPartial, frozen, generate, save, returnToReview, mode = 'plan', previewEdit }: {
 workspace: Workspace; settings: ReturnType<typeof useSettingsDraft>; partial: boolean; setPartial: (value: boolean) => void; frozen: boolean;
 generate: () => void; save: () => void; returnToReview: (() => void) | null; mode?: 'plan' | 'new' | 'edit'; previewEdit?: () => void;
}) {
 const { context, planner } = workspace;
 const { config, runway, update } = settings;
 const device = useRef<string | null>(null);
 if (device.current === null) { try { device.current = deviceTimeZone(); } catch { device.current = ''; } }
 if (!config || !runway) return null;
 const zone = device.current;
 const target = config.duration ? runway.resolved.target_date : config.target_date;
 const duration: Duration | null = config.duration || runway.resolved.matched_duration;
 const setBlocks = (blocks: StudyBlock[]) => update({ blocks });
 const validResearch = ['available', 'no_findings'].includes(context.research_coverage || '');
 const reasons = [
  ...(context.ready ? [] : [context.availability === 'unavailable' ? 'Your CV and Career goal can’t be checked right now.' : 'Finish the CV and Career goal steps shown above.']),
  ...runway.issues.map(issue => issue.message),
  ...(settings.previewError ? [settings.previewError] : []),
  ...(context.model_available ? [] : ['Your adviser is unavailable right now.']),
  ...(context.ready && !validResearch && !partial ? ['Interview research is incomplete. Tick “Continue with available evidence” below to proceed.'] : []),
 ];
 const blocked = reasons.length > 0 || settings.calculating;
 const editBlocked = runway.issues.filter(issue => issue.code !== 'start_in_past').length > 0 || !!settings.previewError || settings.calculating;
 const groups = groupSkills(planner.inputs.skills, skill => skill.name, planner.inputs.skill_groups);
 const defaults = context.planning_defaults;
 const blackoutPeriods = defaults.availability_periods.filter(period => period.weekly_hours === 0);
 const reduced = defaults.availability_periods.filter(period => period.weekly_hours > 0);
 const jobDates = (context.goal?.job_dates || []).filter(date => date.date && date.date > runway.resolved.today);
 return <div className="roadmap-settings">
  <section className="settings-section settings-destination" aria-labelledby="sent-title">
   
   <h2 id="sent-title">What elo will use</h2>
   <p className="small">Your career goal and skills profile are sent to the planning model, along with your confirmed settings.</p>
   <div className="settings-goal"><strong>{planner.inputs.goal?.role || 'No career goal yet'}</strong>{planner.inputs.goal?.company && <span>{planner.inputs.goal.company}</span>}{!!planner.inputs.goal?.skills?.length && <span>{count(planner.inputs.goal.skills.length, 'skill')} in this goal</span>}{planner.inputs.cv?.name && <span>From {planner.inputs.cv.name}</span>}</div>
   <details className="settings-skills"><summary>Skills profile ({count(planner.inputs.skills.length, 'skill')}, {count(planner.inputs.experience.length, 'experience')})</summary>
    {!planner.inputs.skills.length && !planner.inputs.experience.length && <p className="small">No skills evidence is available yet.</p>}
    {groups.map(group => <div key={group.name}><h3>{group.name}</h3><ul>{group.items.map(skill => <li key={skill.ref}><strong>{skill.name}</strong>{skill.text && <span>{skill.text.slice(0, 160)}</span>}</li>)}</ul></div>)}
    {!!planner.inputs.experience.length && <div><h3>Experience</h3><ul>{planner.inputs.experience.map(item => <li key={item.ref}><strong>{item.name}</strong></li>)}</ul></div>}
    <Link href="/cv">Update your Skills Profile</Link>
   </details>
  </section>

  <div className="settings-columns"><div className="settings-column planner-route">
  <Stop label="Timeline" required filled={!!runway.calendar} frozen={frozen}>
   <div className="settings-trio">
   <FieldRow label="Start date"><input type="date" required value={config.start_date || runway.resolved.start_date} onChange={e => { if (e.target.value) update({ start_date: e.target.value }); }} /></FieldRow>
    <FieldRow label="Target date"><input type="date" value={target || ''} onChange={e => update({ target_date: e.target.value || null, duration: null })} /></FieldRow>
    <div className="settings-field"><span id="duration-label">Or duration</span><div className="settings-duration" role="group" aria-labelledby="duration-label">
     <input aria-label="Duration length" type="number" min={1} max={52} value={duration?.value ?? ''} onChange={e => { const value = Math.round(Number(e.target.value)); update(value >= 1 ? { duration: { value, unit: duration?.unit || 'weeks' }, target_date: null } : { duration: null }); }} />
     <select aria-label="Duration unit" value={duration?.unit || 'weeks'} onChange={e => update({ duration: { value: duration?.value || 1, unit: e.target.value as Duration['unit'] }, target_date: null })}><option value="weeks">weeks</option><option value="months">months</option></select>
    </div></div>
   </div>
   {runway.resolved.target_date && <p className="settings-resolved">Target date: <strong>{longDate(runway.resolved.target_date)}</strong>. This is your last study day.</p>}
   {(defaults.application_date || jobDates.length > 0) && <div className="settings-suggestions">{defaults.application_date && <button type="button" className="chip sm" onClick={() => update({ target_date: defaults.application_date, duration: null })}>Use saved application date ({defaults.application_date})</button>}{jobDates.map(date => <button type="button" className="chip sm" key={`${date.kind}${date.date}`} onClick={() => update({ target_date: date.date, duration: null })}>Use {date.kind.replaceAll('_', ' ')} ({date.date})</button>)}</div>}
   <FieldRow label="Plan timezone"><input value={config.time_zone} maxLength={64} onChange={e => update({ time_zone: e.target.value })} /></FieldRow>
   <p className="small">Times are in {config.time_zone}. Weeks run Monday to Sunday there.{zone && zone !== config.time_zone && <> Your device uses {zone}. <button type="button" className="settings-link" onClick={() => update({ time_zone: zone })}>Use {zone}</button></>}</p>
  </Stop>

  <Stop label="Study time" required filled={!!config.weekly_minutes && config.blocks.length > 0} frozen={frozen}>
   <div className="settings-pair">
    <FieldRow label="Weekly budget in hours"><input type="number" min={0} max={168} step="any" value={config.weekly_minutes == null ? '' : config.weekly_minutes / 60} onChange={e => update({ weekly_minutes: e.target.value === '' ? null : Math.round(Number(e.target.value) * 60) })} /></FieldRow>
    <FieldRow label="Preferred session in minutes"><input type="number" min={15} max={480} step={5} value={config.preferred_session_minutes} onChange={e => update({ preferred_session_minutes: Math.round(Number(e.target.value)) })} /></FieldRow>
    <FieldRow label="Buffer percentage"><input type="number" min={0} max={50} step={5} value={config.buffer_percent} onChange={e => update({ buffer_percent: Math.round(Number(e.target.value)) })} /></FieldRow>
   </div>
   <p className="small">The buffer stays free each week for catch-up and rescheduling.</p>
   {config.weekly_minutes == null && defaults.weekly_hours != null && <div className="settings-suggestions"><button type="button" className="chip sm" onClick={() => update({ weekly_minutes: Math.round(defaults.weekly_hours! * 60) })}>Use saved {defaults.weekly_hours} hours a week</button></div>}
   <h3>Recurring study blocks</h3>
   <p className="small">Time outside these blocks is treated as unavailable.</p>
   <div className="settings-tiles">{config.blocks.map((block, index) => <BlockRow key={index} block={block} index={index} change={patch => setBlocks(config.blocks.map((b, i) => i === index ? { ...b, ...patch } : b))} remove={() => setBlocks(config.blocks.filter((_, i) => i !== index))} />)}</div>
   <button type="button" className="btn ghost" disabled={config.blocks.length >= 28} onClick={() => setBlocks([...config.blocks, { day: 0, start_time: '19:00', duration_minutes: 60, kind: 'preferred' }])}>Add study block</button>
   <label className="settings-check"><input type="checkbox" checked={config.use_backup} onChange={e => update({ use_backup: e.target.checked })} />Allow backup blocks when preferred time runs out</label>
  </Stop>

  <Stop label="Blackout days and times" required={false} filled={config.blackouts.length > 0} frozen={frozen}>
   <BlackoutRules rules={config.blackouts} startDate={config.start_date || runway.resolved.start_date} update={blackouts => update({ blackouts })} />
   {blackoutPeriods.map(period => <p className="small" key={period.start_date}>You saved no availability from {period.start_date} to {period.end_date}. <button type="button" className="settings-link" onClick={() => update({ blackouts: [...config.blackouts, dailyBlackout(period.start_date, period.end_date)] })}>Add as blackout</button></p>)}
   {reduced.map(period => <p className="small" key={period.start_date}>You saved {period.weekly_hours} hours a week from {period.start_date} to {period.end_date}. This isn’t applied automatically, so adjust your budget or blackouts if needed.</p>)}
  </Stop>

  <Stop label="Learning focus" required={false} filled={config.learning_focus.length > 0 || !!config.learning_notes.trim()} frozen={frozen}>
   <div className="settings-focus">{focuses.map(([value, label]) => <label key={value} className="settings-check"><input type="checkbox" checked={config.learning_focus.includes(value)} onChange={e => update({ learning_focus: e.target.checked ? [...config.learning_focus, value] : config.learning_focus.filter(f => f !== value) })} />{label}</label>)}</div>
   <FieldRow label="Anything else about how you like to learn?"><textarea maxLength={1000} value={config.learning_notes} onChange={e => update({ learning_notes: e.target.value })} /></FieldRow>
  </Stop>

  <Stop label="Weekly check-in" required={false} filled frozen={frozen}>
   <p className="small">A short check-in opens at this time and stays open until you finish it or next week’s first task starts.</p>
   <div className="settings-pair">
    <FieldRow label="Check-in day"><select value={config.checkin_day} onChange={e => update({ checkin_day: Number(e.target.value) })}>{days.map((day, i) => <option key={day} value={i}>{day}</option>)}</select></FieldRow>
    <FieldRow label="Check-in time"><input type="time" value={config.checkin_time} onChange={e => { if (e.target.value) update({ checkin_time: e.target.value }); }} /></FieldRow>
   </div>
  </Stop>
  </div><div className="settings-column runway-column">
  <section className="settings-section settings-runway" aria-label="Your runway" aria-live="polite">
   <h2>Your runway</h2>
   {runway.calendar ? <>
    <dl className="runway-stats">
     <div className="runway-lead"><dt>Eligible study hours</dt><dd>{hours(runway.study.usable_minutes)}</dd></div>
     <div><dt>Available weeks</dt><dd>{runway.budget.available_weeks}</dd></div>
     <div><dt>Planned hours</dt><dd>{hours(runway.budget.planned_minutes)}</dd></div>
     <div><dt>Buffer hours</dt><dd>{hours(runway.budget.buffer_minutes)}</dd></div>
     <div><dt>Calendar time</dt><dd>{runway.calendar.label}</dd></div>
     <div><dt>From preferred blocks</dt><dd>{hours(runway.study.preferred_minutes)}</dd></div>
     <div><dt>Extra from backup blocks</dt><dd>+{hours(runway.study.backup_extra_minutes)}{config.use_backup ? ' (included)' : ' (not enabled)'}</dd></div>
    </dl>
    {runway.calendar.partial_first_week && <p className="small">Your first week is partial, so it only counts time from {longDate(config.start_date || runway.resolved.start_date)}.</p>}
    <div className="runway-bars" aria-hidden="true">{runway.weeks.map(week => <i key={week.week_start} title={`Week of ${week.week_start}: ${hours(week.usable_minutes)}`} style={{ height: `${Math.max(week.usable_minutes / Math.max(...runway.weeks.map(w => w.usable_minutes), 1) * 100, 3)}%` }} />)}</div>
    <details><summary>Week by week</summary><ul className="runway-weeks">{runway.weeks.map(week => <li key={week.week_start}><span>Week of {week.week_start}{week.partial ? ' (partial)' : ''}</span><span>{hours(week.usable_minutes)} eligible · {hours(week.planned_minutes)} planned{week.backup_extra_minutes > 0 && !config.use_backup ? ` · +${hours(week.backup_extra_minutes)} backup` : ''}</span></li>)}</ul></details>
   </> : <p className="small">Your runway appears once the dates are valid.</p>}
   {settings.calculating && <p role="status" className="small">Recalculating…</p>}
   {mode !== 'edit' && reasons.length > 0 && <div className="settings-blockers"><h3>Before you can generate</h3><ul>{reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul></div>}
   {context.ready && !validResearch && <label className="settings-check"><input type="checkbox" disabled={frozen} checked={partial} onChange={e => setPartial(e.target.checked)} />Continue with available evidence. Interview research is {context.research_coverage || 'unavailable'}; the comparison will be labelled partial.</label>}
   <div className="plan-actions">
    {mode === 'edit'
     ? <button type="button" className="btn primary" disabled={editBlocked || frozen} onClick={previewEdit}>Preview changes</button>
     : <button type="button" className="btn primary" disabled={blocked || frozen} onClick={generate}>{planner.active ? 'Generate new roadmap' : 'Generate roadmap'}</button>}
    {settings.dirty && mode !== 'edit' && <button type="button" className="btn ghost" disabled={frozen || !!settings.previewError} onClick={save}>Save settings</button>}
    {returnToReview && <button type="button" className="btn ghost" onClick={returnToReview}>Return to roadmap</button>}
   </div>
  </section>
  </div></div>
 </div>;
}

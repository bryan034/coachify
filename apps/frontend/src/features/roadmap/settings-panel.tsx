"use client";
import Link from 'next/link';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import { groupSkills } from '@/lib/skill-groups';
import { roadmapApi } from '@/lib/api/roadmap';
import { BlackoutRules, dailyBlackout, weeklyBlackout } from './blackout-rules';
import { fullDate, monthName, monthsBetween } from './roadmap-calendar';
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

/** A date written into the sentence. The native input takes over while it has focus, and clicking opens its picker. */
function DateToken({ name, value, shown, warn, required, onChange }: { name: string; value: string; shown: string; warn?: boolean; required?: boolean; onChange: (value: string) => void }) {
 return <label className={`token date-token${warn ? ' warn' : ''}${value ? '' : ' empty'}`}>
  <span aria-hidden="true">{shown}{warn && <i> ⚠</i>}</span>
  <input aria-label={name} type="date" required={required} value={value} onChange={event => onChange(event.target.value)} onClick={event => { try { event.currentTarget.showPicker?.(); } catch { /* The browser only allows this on a direct click. */ } }} />
 </label>;
}

/** Sizes an input to its text. Digits differ in width, so a width from the digit count leaves gaps. */
function FittedInput({ value, ...input }: React.InputHTMLAttributes<HTMLInputElement> & { value: number | '' }) {
 return <span className="token-fit"><span className="token-ghost" aria-hidden="true">{value === '' ? '0' : value}</span><input type="number" placeholder="0" value={value} {...input} /></span>;
}

/** A number written into the sentence, sized to what it holds. */
function NumberToken({ name, value, suffix, attached, onChange, ...limits }: { name: string; value: number | ''; suffix: string; attached?: boolean; onChange: (value: string) => void; min: number; max: number; step: number | 'any' }) {
 return <label className={`token${value === '' ? ' empty' : ''}`}>
  <FittedInput aria-label={name} value={value} onChange={event => onChange(event.target.value)} {...limits} />
  <span className={attached ? undefined : 'token-unit'}>{suffix}</span>
 </label>;
}

function BlockRow({ block, index, change, remove, close }: { block: StudyBlock; index: number; change: (patch: Partial<StudyBlock>) => void; remove: () => void; close: () => void }) {
 const name = `Block ${index + 1}`;
 return <div className="study-block">
  <label><span aria-hidden="true">Day</span><select aria-label={`${name} day`} value={block.day} onChange={e => change({ day: Number(e.target.value) })}>{days.map((day, i) => <option key={day} value={i}>{day}</option>)}</select></label>
  <label><span aria-hidden="true">Starts</span><input aria-label={`${name} start time`} type="time" value={block.start_time} onChange={e => { if (e.target.value) change({ start_time: e.target.value }); }} /></label>
  <label><span aria-hidden="true">Minutes</span><input aria-label={`${name} minutes`} type="number" min={15} max={480} step={5} value={block.duration_minutes} onChange={e => change({ duration_minutes: Math.round(Number(e.target.value)) })} /></label>
  <label><span aria-hidden="true">Type</span><select aria-label={`${name} type`} value={block.kind} onChange={e => change({ kind: e.target.value as StudyBlock['kind'] })}><option value="preferred">Preferred</option><option value="backup">Backup</option></select></label>
  <button type="button" className="btn ghost" aria-label={`Remove block ${index + 1}`} onClick={remove}>Remove</button>
  <button type="button" className="btn ghost" onClick={close}>Done</button>
 </div>;
}

/** The week of recurring study blocks. Choosing a block opens its details underneath. */
function StudyWeek({ blocks, setBlocks }: { blocks: StudyBlock[]; setBlocks: (blocks: StudyBlock[]) => void }) {
 const [editing, setEditing] = useState<number | null>(null);
 const add = (day: number) => { if (blocks.length >= 28) return; setBlocks([...blocks, { day, start_time: '19:00', duration_minutes: 60, kind: 'preferred' }]); setEditing(blocks.length); };
 const block = editing === null ? undefined : blocks[editing];
 return <>
  <div className="block-week">{days.map((name, day) => <div className="block-day" key={name}>
   <span className="block-day-name">{name.slice(0, 3)}</span>
   <div className="block-cell">
    {blocks.map((item, index) => ({ item, index })).filter(({ item }) => item.day === day).sort((a, b) => a.item.start_time.localeCompare(b.item.start_time)).map(({ item, index }) => <button type="button" key={index} className={`block-chip ${item.kind}`} aria-expanded={editing === index} aria-label={`Edit ${name} block: ${item.start_time}, ${item.duration_minutes} minutes, ${item.kind}`} onClick={() => setEditing(editing === index ? null : index)}><strong>{item.start_time}</strong><span>{item.duration_minutes} min</span><span className="block-kind">{item.kind === 'backup' ? 'Backup' : 'Preferred'}</span></button>)}
    <button type="button" className="block-add" aria-label={`Add study block on ${name}`} disabled={blocks.length >= 28} onClick={() => add(day)}><span aria-hidden="true">+</span></button>
   </div>
  </div>)}</div>
  {block && editing !== null && <BlockRow block={block} index={editing} change={patch => setBlocks(blocks.map((b, i) => i === editing ? { ...b, ...patch } : b))} remove={() => { setBlocks(blocks.filter((_, i) => i !== editing)); setEditing(null); }} close={() => setEditing(null)} />}
  <button type="button" className="btn ghost road-add" disabled={blocks.length >= 28} onClick={() => add(0)}><span aria-hidden="true">+ </span>Add study block</button>
 </>;
}

/** Start to target as a line of months. The stats beside it carry the numbers. */
function RunwayLine({ start, target }: { start: string; target: string }) {
 const months = monthsBetween(start, target);
 if (target <= start || months.length > 14) return null;
 return <ol className="runway-line">{months.map((month, index) => {
  const first = index === 0; const final = index === months.length - 1;
  return <li key={month} className={`${first ? 'start' : ''}${final ? ' target' : ''}`}><span className="runway-month">{monthName(month)}</span><i aria-hidden="true" />
   <span className="runway-point">{first && <span className="runway-start">Start · {fullDate(start)}</span>}{final && <span className="runway-target">Target · {longDate(target)}</span>}</span>
  </li>;
 })}</ol>;
}

/** Each stop's road runs from its own lane to the next stop's, so the stops zigzag gently down the page. */
const lane = (index: number) => index % 2 ? 72 : 28;
function Road({ index, travelled }: { index: number; travelled: boolean }) {
 const path = `M${lane(index)} 0C${lane(index)} 50 ${lane(index + 1)} 50 ${lane(index + 1)} 100`;
 return <svg className={`road-bend${travelled ? ' travelled' : ''}`} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
  <path className="road-bed" vectorEffect="non-scaling-stroke" d={path} />
  <path className="road-line" vectorEffect="non-scaling-stroke" d={path} />
 </svg>;
}

type StopSpec = { name: string; filled: boolean; required: boolean; content: ReactNode };

export function SettingsPanel({ workspace, settings, partial, setPartial, frozen, generate, save, returnToReview }: {
 workspace: Workspace; settings: ReturnType<typeof useSettingsDraft>; partial: boolean; setPartial: (value: boolean) => void; frozen: boolean;
 generate: () => void; save: () => void; returnToReview: (() => void) | null;
}) {
 const { context, planner } = workspace;
 const { config, runway, update } = settings;
 const device = useRef<string | null>(null);
 const [choosingFocus, setChoosingFocus] = useState(false);
 if (device.current === null) { try { device.current = deviceTimeZone(); } catch { device.current = ''; } }
 if (!config || !runway) return null;
 const zone = device.current;
 const target = config.duration ? runway.resolved.target_date : config.target_date;
 const duration: Duration | null = config.duration || runway.resolved.matched_duration;
 const start = config.start_date || runway.resolved.start_date;
 const issues = new Set(runway.issues.map(issue => issue.code));
 const targetProblem = issues.has('target_before_start') || issues.has('target_elapsed') || issues.has('runway_too_long');
 const validResearch = ['available', 'no_findings'].includes(context.research_coverage || '');
 const reasons = [
  ...(context.ready ? [] : [context.availability === 'unavailable' ? 'Your CV and Career goal can’t be checked right now.' : 'Finish the CV and Career goal steps shown above.']),
  ...runway.issues.map(issue => issue.message),
  ...(settings.previewError ? [settings.previewError] : []),
  ...(context.model_available ? [] : ['Your adviser is unavailable right now.']),
  ...(context.ready && !validResearch && !partial ? ['Interview research is incomplete. Tick “Continue with available evidence” below to proceed.'] : []),
 ];
 const blocked = reasons.length > 0 || settings.calculating;
 const groups = groupSkills(planner.inputs.skills, skill => skill.name ?? '', planner.inputs.skill_groups);
 const defaults = context.planning_defaults;
 const blackoutPeriods = defaults.availability_periods.filter(period => period.weekly_hours === 0);
 const reduced = defaults.availability_periods.filter(period => period.weekly_hours > 0);
 const jobDates = (context.goal?.job_dates || []).filter(date => date.date && date.date > runway.resolved.today);
 const chosenFocus = focuses.filter(([value]) => config.learning_focus.includes(value)).map(([, label]) => label);
 const showFocus = choosingFocus || !!config.learning_notes.trim();

 const stops: StopSpec[] = [
  { name: 'Start', required: true, filled: !issues.has('start_in_past'), content: <p className="road-clause">I’ll start on <DateToken name="Start date" required value={start} shown={fullDate(start)} warn={issues.has('start_in_past')} onChange={value => { if (value) update({ start_date: value }); }} /></p> },
  { name: 'Finish', required: true, filled: !!target && !targetProblem, content: <>
   <p className="road-clause">and finish by <DateToken name="Target date" value={target || ''} shown={target ? longDate(target) : 'choose a date'} warn={targetProblem} onChange={value => update({ target_date: value || null, duration: null })} />, that’s{' '}
    <span className={`token${duration || runway.calendar ? '' : ' empty'}${!duration && runway.calendar ? ' calculated' : ''}`} role="group" aria-label="Duration">
     {!duration && runway.calendar && <span className="token-shown" aria-hidden="true">{runway.calendar.label}</span>}
     <span className="token-edit">
      <FittedInput aria-label="Duration length" min={1} max={52} value={duration?.value ?? ''} onChange={e => { const value = Math.round(Number(e.target.value)); update(value >= 1 ? { duration: { value, unit: duration?.unit || 'weeks' }, target_date: null } : { duration: null }); }} />
      <select aria-label="Duration unit" value={duration?.unit || 'weeks'} onChange={e => update({ duration: { value: duration?.value || 1, unit: e.target.value as Duration['unit'] }, target_date: null })}><option value="weeks">weeks</option><option value="months">months</option></select>
     </span>
    </span>.
   </p>
   {(defaults.application_date || jobDates.length > 0) && <div className="settings-suggestions">{defaults.application_date && <button type="button" className="chip sm" onClick={() => update({ target_date: defaults.application_date, duration: null })}>Use saved application date ({defaults.application_date})</button>}{jobDates.map(date => <button type="button" className="chip sm" key={`${date.kind}${date.date}`} onClick={() => update({ target_date: date.date, duration: null })}>Use {date.kind.replaceAll('_', ' ')} ({date.date})</button>)}</div>}
  </> },
  { name: 'Weekly study time', required: true, filled: !!config.weekly_minutes, content: <>
   <p className="road-clause">I can study <NumberToken name="Weekly budget in hours" min={0} max={168} step="any" value={config.weekly_minutes == null ? '' : config.weekly_minutes / 60} suffix="hours" onChange={value => update({ weekly_minutes: value === '' ? null : Math.round(Number(value) * 60) })} /> a week</p>
   {config.weekly_minutes == null && defaults.weekly_hours != null && <div className="settings-suggestions"><button type="button" className="chip sm" onClick={() => update({ weekly_minutes: Math.round(defaults.weekly_hours! * 60) })}>Use saved {defaults.weekly_hours} hours a week</button></div>}
  </> },
  { name: 'Session length', required: true, filled: config.preferred_session_minutes > 0, content: <p className="road-clause">in <NumberToken name="Preferred session in minutes" min={15} max={480} step={5} value={config.preferred_session_minutes} suffix="-minute" attached onChange={value => update({ preferred_session_minutes: Math.round(Number(value)) })} /> sessions,</p> },
  { name: 'Recurring study blocks', required: true, filled: config.blocks.length > 0, content: <>
   <p className="road-clause">on these days each week:</p>
   <p className="small road-hint">Time outside these blocks is treated as unavailable.</p>
   <StudyWeek blocks={config.blocks} setBlocks={blocks => update({ blocks })} />
  </> },
  { name: 'Backup blocks', required: false, filled: config.use_backup, content: <p className="road-clause">Backup blocks are <label className={`token toggle-token${config.use_backup ? '' : ' off'}`}><input type="checkbox" aria-label="Allow backup blocks when preferred time runs out" checked={config.use_backup} onChange={e => update({ use_backup: e.target.checked })} /><span aria-hidden="true">{config.use_backup ? 'allowed' : 'not allowed'}</span></label> when preferred time runs out.</p> },
  { name: 'Learning focus', required: false, filled: chosenFocus.length > 0 || !!config.learning_notes.trim(), content: <>
   <p className="road-clause">I’d like to focus on <button type="button" className={`token token-button${chosenFocus.length ? '' : ' empty'}`} aria-expanded={showFocus} aria-label="Choose learning focus" onClick={() => setChoosingFocus(!showFocus)}>{chosenFocus.length ? chosenFocus.join(', ') : <><span aria-hidden="true">+ </span>choose focus</>}</button> <span className="small">Optional</span></p>
   {showFocus && <div className="focus-panel">
    <div className="focus-chips">{focuses.map(([value, label]) => <label key={value} className={`focus-chip${config.learning_focus.includes(value) ? ' on' : ''}`}><input type="checkbox" checked={config.learning_focus.includes(value)} onChange={e => update({ learning_focus: e.target.checked ? [...config.learning_focus, value] : config.learning_focus.filter(f => f !== value) })} />{label}</label>)}</div>
    <label className="settings-field"><span>Anything else about how you like to learn?</span><textarea maxLength={1000} value={config.learning_notes} onChange={e => update({ learning_notes: e.target.value })} /></label>
   </div>}
  </> },
  { name: 'Blackout days and times', required: false, filled: config.blackouts.length > 0, content: <>
   <p className="road-clause">{config.blackouts.length ? 'and I can’t study during these times.' : 'and I can’t study on'} <button type="button" className="token token-button empty" aria-label="Add blackout" disabled={config.blackouts.length >= 366} onClick={() => update({ blackouts: [...config.blackouts, weeklyBlackout(start)] })}><span aria-hidden="true">+ </span>{config.blackouts.length ? 'add another' : 'add blackout'}</button>{!config.blackouts.length && '.'} <span className="small">Optional</span></p>
   <BlackoutRules rules={config.blackouts} update={blackouts => update({ blackouts })} />
   {blackoutPeriods.map(period => <p className="small" key={period.start_date}>You saved no availability from {period.start_date} to {period.end_date}. <button type="button" className="settings-link" onClick={() => update({ blackouts: [...config.blackouts, dailyBlackout(period.start_date, period.end_date)] })}>Add as blackout</button></p>)}
   {reduced.map(period => <p className="small" key={period.start_date}>You saved {period.weekly_hours} hours a week from {period.start_date} to {period.end_date}. This isn’t applied automatically, so adjust your budget or blackouts if needed.</p>)}
  </> },
 ];
 // The road is travelled up to the first required detail still missing. Filling that in moves it on.
 const firstMissing = stops.findIndex(stop => stop.required && !stop.filled);
 const reached = firstMissing < 0 ? stops.length : firstMissing;

 return <div className="roadmap-settings">
  <section className="planner-uses" aria-labelledby="sent-title">
   <h2 id="sent-title">What elo will use</h2>
   <div className="use-chips">
    <span className="use-chip goal">{planner.inputs.goal?.role || 'No career goal yet'}</span>
    {planner.inputs.goal?.company && <span className="use-chip">{planner.inputs.goal.company}</span>}
    {!!planner.inputs.goal?.skills?.length && <details className="use-chip-menu"><summary className="use-chip">{count(planner.inputs.goal.skills.length, 'skill')} in this goal</summary><div className="use-panel"><ul>{planner.inputs.goal.skills.map(skill => <li key={skill.name}><strong>{skill.name}</strong></li>)}</ul></div></details>}
    {planner.inputs.cv?.name && <span className="use-chip">{planner.inputs.cv.name}</span>}
    <details className="use-chip-menu"><summary className="use-chip">Skills profile · {count(planner.inputs.skills.length, 'skill')}, {count(planner.inputs.experience.length, 'experience')}</summary><div className="use-panel">
     {!planner.inputs.skills.length && !planner.inputs.experience.length && <p className="small">No skills evidence is available yet.</p>}
     {groups.map(group => <div key={group.name}><h3>{group.name}</h3><ul>{group.items.map(skill => <li key={skill.ref}><strong>{skill.name}</strong>{skill.text && <span>{skill.text.slice(0, 160)}</span>}</li>)}</ul></div>)}
     {!!planner.inputs.experience.length && <div><h3>Experience</h3><ul>{planner.inputs.experience.map(item => <li key={item.ref}><strong>{item.name}</strong></li>)}</ul></div>}
     <Link href="/cv">Update your Skills Profile</Link>
    </div></details>
   </div>
  </section>

  <div className="road-intro"><h2>Your plan</h2><p className="small">Tap any highlighted part to change it. The road fills in as you go.</p></div>
  <ol className="plan-road">
   {stops.map((stop, index) => {
    const state = index === reached ? 'current' : index < reached ? 'passed' : 'ahead';
    return <li key={stop.name} className={`road-stop ${state}${stop.filled ? ' filled' : ''}`} aria-current={index === reached ? 'step' : undefined}>
     <div className="road-rail"><Road index={index} travelled={index < reached} /><i className="road-dot" style={{ left: `${lane(index)}%` }} aria-hidden="true" /></div>
     <fieldset className="road-content" aria-label={stop.name} disabled={frozen}>
      <span className="visually-hidden">{stop.filled ? 'Done: ' : stop.required ? 'Required: ' : 'Optional: '}</span>
      {stop.content}
     </fieldset>
    </li>;
   })}
   <li className={`road-stop road-end${reached === stops.length ? ' passed' : ' ahead'}`}>
    <div className="road-rail"><i className="road-dot road-flag" style={{ left: `${lane(stops.length)}%` }} aria-hidden="true" /></div>
    <section className="settings-section settings-runway" aria-label="Your runway" aria-live="polite">
     <h2>Your runway</h2>
     {!runway.calendar && <p className="small">Your runway appears once the dates are valid.</p>}
     <div className="runway-body">
      {target && <RunwayLine start={start} target={target} />}
      {runway.calendar && <div className="runway-figures">
       <dl className="runway-stats">
        <div className="runway-lead"><dt>Usable study time</dt><dd>{hours(runway.study.usable_minutes)}</dd></div>
        <div><dt>Calendar time</dt><dd>{runway.calendar.label}</dd></div>
        <div><dt>From preferred blocks</dt><dd>{hours(runway.study.preferred_minutes)}</dd></div>
        <div><dt>Extra from backup blocks</dt><dd>+{hours(runway.study.backup_extra_minutes)}{config.use_backup ? ' (included)' : ' (not enabled)'}</dd></div>
       </dl>
       {runway.calendar.partial_first_week && <p className="small">Your first week is partial, so it only counts time from {longDate(start)}.</p>}
      </div>}
     </div>
     <p className="small">Times are in {config.time_zone}.{zone && zone !== config.time_zone && <> Your device uses {zone}. <button type="button" className="settings-link" onClick={() => update({ time_zone: zone })}>Use {zone}</button></>}</p>
     {runway.calendar && <details><summary>Week by week</summary><ul className="runway-weeks">{runway.weeks.map(week => <li key={week.week_start}><span>Week of {week.week_start}{week.partial ? ' (partial)' : ''}</span><span>{hours(week.usable_minutes)}{week.backup_extra_minutes > 0 && !config.use_backup ? ` · +${hours(week.backup_extra_minutes)} backup` : ''}</span></li>)}</ul></details>}
     {settings.calculating && <p role="status" className="small">Recalculating…</p>}
     {reasons.length > 0 && <div className="settings-blockers"><h3>Before you can generate</h3><ul>{reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul></div>}
     {context.ready && !validResearch && <label className="settings-check"><input type="checkbox" disabled={frozen} checked={partial} onChange={e => setPartial(e.target.checked)} />Continue with available evidence. Interview research is {context.research_coverage || 'unavailable'}; the comparison will be labelled partial.</label>}
     <div className="plan-actions">
      <button type="button" className="btn primary" disabled={blocked || frozen} onClick={generate}>{planner.active ? 'Preview updated roadmap' : 'Generate roadmap'}</button>
      {settings.dirty && <button type="button" className="btn ghost" disabled={frozen || !!settings.previewError} onClick={save}>Save settings</button>}
      {returnToReview && <button type="button" className="btn ghost" onClick={returnToReview}>Return to roadmap</button>}
     </div>
    </section>
   </li>
  </ol>
 </div>;
}

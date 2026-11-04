"use client";
import type { BlackoutFrequency, BlackoutRule } from './types';

const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const frequencies: [BlackoutFrequency, string][] = [['once', 'One day only'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['monthly', 'Monthly']];
const units: Partial<Record<BlackoutFrequency, string>> = { daily: 'day', weekly: 'week', monthly: 'month' };
const shortDate = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const weekdayOf = (value: string) => (new Date(`${value}T12:00:00Z`).getUTCDay() + 6) % 7;

export const weeklyBlackout = (start_date: string): BlackoutRule => ({ frequency: 'weekly', start_date, end_date: null, interval: 1, weekdays: [weekdayOf(start_date)], start_time: null, end_time: null });
export const dailyBlackout = (start_date: string, end_date: string): BlackoutRule => ({ frequency: 'daily', start_date, end_date, interval: 1, weekdays: [], start_time: null, end_time: null });

/** The rule in words, so a person can check what they configured. Capacity itself is calculated by the backend. */
export function describeBlackout(rule: BlackoutRule) {
 const every = rule.interval > 1 ? `Every ${rule.interval} ${units[rule.frequency]}s` : `Every ${units[rule.frequency]}`;
 const day = Number(rule.start_date.slice(8));
 const when = rule.frequency === 'once' ? shortDate(rule.start_date)
  : rule.frequency === 'daily' ? every
  : rule.frequency === 'weekly' ? `${every} on ${[...rule.weekdays].sort().map(index => weekdays[index].slice(0, 3)).join(', ') || 'no days yet'}`
  : `${every} on day ${day}${day > 28 ? ' or the month’s last day' : ''}`;
 const time = rule.start_time && rule.end_time ? `${rule.start_time}–${rule.end_time}` : 'all day';
 const range = rule.frequency === 'once' ? '' : `, from ${shortDate(rule.start_date)}${rule.end_date ? ` until ${shortDate(rule.end_date)}` : ''}`;
 return `${when}, ${time}${range}`;
}

function withFrequency(rule: BlackoutRule, frequency: BlackoutFrequency): BlackoutRule {
 return { ...rule, frequency, interval: 1, end_date: frequency === 'once' ? null : rule.end_date, weekdays: frequency !== 'weekly' ? [] : rule.weekdays.length ? rule.weekdays : [weekdayOf(rule.start_date)] };
}

function Rule({ rule, number, change, remove }: { rule: BlackoutRule; number: number; change: (rule: BlackoutRule) => void; remove: () => void }) {
 const name = `Blackout ${number}`;
 const once = rule.frequency === 'once';
 const allDay = rule.start_time === null && rule.end_time === null;
 return <div className="blackout-rule" role="group" aria-label={name}>
  <p className="blackout-summary">{describeBlackout(rule)}</p>
  <div className="blackout-fields">
   <label><span aria-hidden="true">Repeats</span><select aria-label={`${name} repeats`} value={rule.frequency} onChange={e => change(withFrequency(rule, e.target.value as BlackoutFrequency))}>{frequencies.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
   {!once && <label><span aria-hidden="true">Repeat every ({units[rule.frequency]}s)</span><input aria-label={`${name} interval`} type="number" min={1} max={52} value={rule.interval} onChange={e => change({ ...rule, interval: Math.min(52, Math.max(1, Math.round(Number(e.target.value)))) })} /></label>}
   <label><span aria-hidden="true">{once ? 'Date' : 'From'}</span><input aria-label={`${name} ${once ? 'date' : 'start date'}`} type="date" value={rule.start_date} onChange={e => { if (e.target.value) change({ ...rule, start_date: e.target.value }); }} /></label>
   {!once && <label><span aria-hidden="true">Until (optional)</span><input aria-label={`${name} end date`} type="date" value={rule.end_date || ''} onChange={e => change({ ...rule, end_date: e.target.value || null })} /></label>}
  </div>
  {rule.frequency === 'weekly' && <div className="blackout-weekdays">{weekdays.map((label, index) => <label key={label}><input type="checkbox" aria-label={`${name} on ${label}`} checked={rule.weekdays.includes(index)} onChange={e => change({ ...rule, weekdays: e.target.checked ? [...rule.weekdays, index].sort() : rule.weekdays.filter(day => day !== index) })} /><span aria-hidden="true">{label.slice(0, 3)}</span></label>)}</div>}
  <div className="blackout-time">
   <label className="settings-check"><input type="checkbox" aria-label={`${name} all day`} checked={allDay} onChange={e => change({ ...rule, start_time: e.target.checked ? null : '18:00', end_time: e.target.checked ? null : '20:00' })} /><span aria-hidden="true">All day</span></label>
   {!allDay && <><label><span aria-hidden="true">From</span><input aria-label={`${name} start time`} type="time" value={rule.start_time || ''} onChange={e => { if (e.target.value) change({ ...rule, start_time: e.target.value }); }} /></label>
   <label><span aria-hidden="true">To</span><input aria-label={`${name} end time`} type="time" value={rule.end_time || ''} onChange={e => { if (e.target.value) change({ ...rule, end_time: e.target.value }); }} /></label></>}
   <button type="button" className="btn ghost" aria-label={`Remove blackout ${number}`} onClick={remove}>Remove</button>
  </div>
 </div>;
}

export function BlackoutRules({ rules, startDate, update }: { rules: BlackoutRule[]; startDate: string; update: (rules: BlackoutRule[]) => void }) {
 return <>
  <p className="small">Days or times you can’t study. Study blocks that overlap them are removed from your runway.</p>
  <div className="settings-tiles">{rules.map((rule, index) => <Rule key={index} rule={rule} number={index + 1} change={next => update(rules.map((r, i) => i === index ? next : r))} remove={() => update(rules.filter((_, i) => i !== index))} />)}</div>
  <button type="button" className="btn ghost" disabled={rules.length >= 366} onClick={() => update([...rules, weeklyBlackout(startDate)])}>Add blackout</button>
 </>;
}

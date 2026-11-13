"use client";
import { useEffect, useRef, useState } from 'react';
import { addDays, monthName, dayOfMonth, shortDate, weekStart, weekdayName } from './roadmap-calendar';
import { minutesOf, shortLength, toClock, toMinutes } from './roadmap-day';
import type { ViewContext } from './day-list';
import type { BacklogProposal, FreeDay, Session } from './types';

const range = (start: string, minutes: number) => `${start}–${toClock(toMinutes(start) + minutes)}`;
const dayLabel = (day: string, today: string) => day === today ? 'Today' : day === addDays(today, 1) ? 'Tomorrow' : `${weekdayName(day)} ${dayOfMonth(day)}${weekStart(day) !== weekStart(today) ? ` ${monthName(day)}` : ''}`;
const dayText = (day: string, today: string) => day === today ? 'today' : `${weekdayName(day)} ${shortDate(day)}`;

/** Move one task to a free time. Times come from the roadmap service, which checks the final choice again. */
export function ReschedulePanel({ session, context, onMoved, onClose }: { session: Session; context: ViewContext; onMoved: (message: string) => void; onClose: () => void }) {
 const { actions, today, version, frozen } = context;
 const [days, setDays] = useState<FreeDay[] | null>(null); const [failed, setFailed] = useState(false);
 const [choice, setChoice] = useState<{ date: string; start: string } | null>(null);
 const [note, setNote] = useState(''); const [busy, setBusy] = useState(false);
 const chosen = useRef(choice); chosen.current = choice;
 // Recalculated whenever the saved schedule changes, so a time taken elsewhere is never offered.
 useEffect(() => {
  let live = true;
  void actions.freeTimes(session.duration_minutes, session.id).then(value => {
   if (!live) return;
   if (!value) { setFailed(true); return; }
   setFailed(false); setDays(value.days);
   const current = chosen.current;
   if (!current) { const first = value.days.find(day => !day.rest_day && day.starts.length); if (first) setChoice({ date: first.date, start: first.starts[0] }); return; }
   const day = value.days.find(item => item.date === current.date);
   if (day && !day.starts.includes(current.start) && day.starts.length) {
    const next = day.starts.find(start => start > current.start) || day.starts[0];
    setChoice({ date: current.date, start: next });
    setNote(`${current.start} ${current.date === today ? 'today' : `on ${dayText(current.date, today)}`} was just taken, so this moved to the next free time, ${range(next, session.duration_minutes)}.`);
   }
  });
  return () => { live = false; };
 }, [version, session.id, session.duration_minutes]); // eslint-disable-line react-hooks/exhaustive-deps
 const pick = (date: string, start: string | undefined) => { setNote(''); setChoice(start ? { date, start } : { date, start: '' }); };
 const day = choice ? days?.find(item => item.date === choice.date) : undefined;
 const valid = !!choice && !!day && day.starts.includes(choice.start);
 const thisWeek = weekStart(today);
 const chip = (item: FreeDay) => <button key={item.date} type="button" className={`rv-opt${item.rest_day ? ' rest' : ''}`} aria-pressed={choice?.date === item.date} disabled={!item.starts.length} onClick={() => pick(item.date, item.starts[0])}>{item.rest_day ? `${weekdayName(item.date)} ${dayOfMonth(item.date)} · rest day` : dayLabel(item.date, today)}</button>;
 async function confirm() {
  if (!valid || busy) return;
  setBusy(true);
  const moved = await actions.move([{ session_id: session.id, date: choice!.date, start_time: choice!.start }]);
  setBusy(false);
  if (moved) onMoved(`Moved “${session.title}” to ${dayText(choice!.date, today)}, ${range(choice!.start, session.duration_minutes)}.`);
 }
 async function eloPick() {
  const plan = await actions.backlogPlan([session.id]); const move = plan?.moves.find(item => item.session_id === session.id);
  if (move?.date && move.start_time) pick(move.date, move.start_time);
  else { const first = days?.find(item => !item.rest_day && item.starts.length); if (first) pick(first.date, first.starts[0]); }
 }
 return <div className="rv-rs" role="group" aria-label={`Reschedule ${session.title}`}>
  {failed && <p className="rv-rs-warn" role="alert">Free times couldn’t be loaded. Close this and try again.</p>}
  {!days && !failed && <p className="rv-note" role="status">Finding free times…</p>}
  {days && <>
   <p className="rv-rs-h">Suggested times<span>Never overlaps your other tasks</span></p>
   <div className="rv-rs-sugs">{days.filter(item => !item.rest_day && item.starts.length).slice(0, 3).map(item => <button key={item.date} type="button" className="rv-rs-sug" aria-pressed={choice?.date === item.date && choice.start === item.starts[0]} onClick={() => pick(item.date, item.starts[0])}>{dayLabel(item.date, today)}<span>{range(item.starts[0], session.duration_minutes)}{item.kind === 'after_block' ? ', after your block' : ''}</span></button>)}</div>
   {!days.some(item => item.starts.length) && <p className="rv-note">No free time in the next two weeks.</p>}
   <p className="rv-rs-h">Or choose a day</p>
   <p className="rv-rs-sub">This week</p>
   <div className="rv-chips">{days.filter(item => weekStart(item.date) === thisWeek).map(chip)}</div>
   {days.some(item => weekStart(item.date) !== thisWeek) && <><p className="rv-rs-sub">Next week</p><div className="rv-chips">{days.filter(item => weekStart(item.date) !== thisWeek).map(chip)}</div></>}
   {day && <>
    {day.rest_day && <p className="rv-rs-rest">{weekdayName(day.date)} is a rest day in your plan. You can still use it; elo just won’t suggest it.</p>}
    <p className="rv-rs-h">Free times {day.date === today ? 'today' : `on ${dayText(day.date, today)}`}</p>
    {day.starts.length > 0 ? <div className="rv-chips">{day.starts.slice(0, 8).map(start => <button key={start} type="button" className="rv-opt" aria-pressed={choice?.start === start} onClick={() => pick(day.date, start)}>{range(start, session.duration_minutes)}</button>)}</div>
     : <p className="rv-note">No free time left that day. Choose another day.</p>}
    {day.kind === 'after_block' && <p className="rv-note">Your study block is full that day, so these start after it.</p>}
   </>}
   {note && <p className="rv-rs-warn" role="status">{note}</p>}
  </>}
  <div className="rv-chips"><button className="rv-btn sm pri" type="button" disabled={!valid || busy || frozen} onClick={() => void confirm()}>{valid ? `Move to ${dayText(choice!.date, today)}, ${range(choice!.start, session.duration_minutes)}` : 'Choose a day'}</button><button className="rv-btn sm" type="button" onClick={onClose}>Cancel</button></div>
  <div className="rv-rs-more"><button type="button" className="rv-link" disabled={!days || busy} onClick={() => void eloPick()}>Let elo pick a time</button>
   {session.missed && <button type="button" className="rv-link danger" disabled={busy || frozen} onClick={() => void actions.skip(session.id).then(done => { if (done) onMoved(`Skipped “${session.title}”.`); })}>Skip this session</button>}</div>
 </div>;
}

const Grip = () => <span className="rv-grip" aria-hidden="true"><svg width="16" height="20" viewBox="0 0 16 20" fill="currentColor"><circle cx="5" cy="5" r="1.6" /><circle cx="11" cy="5" r="1.6" /><circle cx="5" cy="10" r="1.6" /><circle cx="11" cy="10" r="1.6" /><circle cx="5" cy="15" r="1.6" /><circle cx="11" cy="15" r="1.6" /></svg></span>;

/** Sessions that weren't ticked off on their day. A strip on Today, a panel beside the week. */
export function Backlog({ context, panel = false, autoOpen = 0 }: { context: ViewContext; panel?: boolean; autoOpen?: number }) {
 const { sessions, actions, today, frozen } = context;
 const items = sessions.filter(item => item.missed);
 const [openId, setOpenId] = useState<string | null>(null);
 const [proposal, setProposal] = useState<BacklogProposal[] | null>(null);
 const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false);
 async function propose() { setOpenId(null); setBusy(true); const plan = await actions.backlogPlan(); setBusy(false); if (plan) setProposal(plan.moves); }
 // "Fill the gap with backlog" on the weekly goal asks for the same proposal.
 useEffect(() => { if (autoOpen && items.length) void propose(); }, [autoOpen]); // eslint-disable-line react-hooks/exhaustive-deps
 const placed = proposal?.filter(item => item.date && item.start_time) || [];
 async function apply() {
  setBusy(true);
  const moved = await actions.move(placed.map(item => ({ session_id: item.session_id, date: item.date!, start_time: item.start_time! })));
  setBusy(false);
  if (moved) { setProposal(null); setMessage(`elo moved ${placed.length} ${placed.length === 1 ? 'task' : 'tasks'} into free times this week and next.`); }
 }
 if (!items.length && !panel && !message) return null;
 const autoButton = items.length > 0 && <button className="rv-btn sm warn" type="button" disabled={busy || frozen} onClick={() => void propose()}>Let elo reschedule all</button>;
 return <section className={panel ? 'rv-card rv-backlog panel' : 'rv-backlog'} aria-label="Backlog">
  {items.length > 0 || panel ? <div className="rv-row-between" style={{ padding: panel ? 0 : '8px 0', alignItems: panel ? 'baseline' : 'center' }}>
   {panel ? <h2 className="rv-lab">Backlog · {items.length}</h2> : <p className="rv-lab">Backlog · {items.length} to reschedule</p>}
   {panel ? items.length > 0 && <span className="rv-note" style={{ fontSize: 12, color: 'var(--growing-ink)' }}>{shortLength(minutesOf(items))}</span> : autoButton}
  </div> : null}
  {panel && <p className="rv-note" style={{ margin: '8px 0 12px' }}>Sessions you didn’t tick off. Choose where each one goes, or let elo place them all.</p>}
  {panel && autoButton && <div style={{ marginBottom: 12 }}>{autoButton}</div>}
  {proposal && items.length > 0 && <div className="rv-rs" role="region" aria-label="elo’s suggested times for your backlog">
   <p className="rv-rs-h">elo’s suggested times</p>
   <p className="rv-note" style={{ fontSize: 12 }}>Spread over this week and next, inside your study blocks. No overlaps, rest days skipped, and at most one moved task per day while there’s room.</p>
   <ul className="rv-auto-rows">{proposal.map(item => <li key={item.session_id}><span>{item.title}</span><strong className={item.date ? undefined : 'none'}>{item.date && item.start_time ? `${dayLabel(item.date, today)}, ${range(item.start_time, item.duration_minutes)}` : 'No free time in the next two weeks'}</strong></li>)}</ul>
   <div className="rv-chips"><button className="rv-btn sm pri" type="button" disabled={!placed.length || busy || frozen} onClick={() => void apply()}>Move {placed.length} {placed.length === 1 ? 'task' : 'tasks'}</button><button className="rv-btn sm" type="button" onClick={() => setProposal(null)}>Cancel</button></div>
   <p className="rv-note" style={{ fontSize: 12 }}>You can still move any of them afterwards.</p>
  </div>}
  {message && <p className="rv-status" role="status" style={{ margin: '0 0 12px' }}>{message}</p>}
  {panel && !items.length && <p className="rv-status" style={{ margin: 0 }}>Backlog clear. Nice work.</p>}
  <ul className="rv-backlog-list">{items.map(item => [
   <li className="rv-backlog-item" key={item.id}><Grip />
    <div className="rv-task-body"><div className="rv-ttl">{item.title}</div><div className="rv-task-meta"><span>Missed {weekdayName(item.date)}, {shortDate(item.date)}</span><span>{shortLength(item.duration_minutes)}</span>{item.skills.map(skill => <span className="rv-tag sk" key={skill.name}>{skill.name}</span>)}</div></div>
    <button className="rv-btn sm" type="button" aria-expanded={openId === item.id} aria-label={`Reschedule ${item.title}`} onClick={() => { setProposal(null); setOpenId(openId === item.id ? null : item.id); }}>Reschedule</button>
   </li>,
   openId === item.id && <li key={`${item.id}-panel`} style={{ listStyle: 'none' }}><ReschedulePanel session={item} context={context} onClose={() => setOpenId(null)} onMoved={text => { setOpenId(null); setMessage(text); }} /></li>,
  ])}</ul>
 </section>;
}

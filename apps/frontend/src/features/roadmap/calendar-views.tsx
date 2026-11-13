"use client";
import { useState } from 'react';
import { Backlog, ReschedulePanel } from './backlog';
import { BusyLabels, DayTimeline, TaskList, Tick, studyBlockLine, type TaskEditor, type ViewContext } from './day-list';
import { addDays, addMonths, dayOfMonth, fullDate, monthKey, monthName, monthTitle, monthWeeks, shortDate, weekColumns, weekDates, weekStart, weekdayName } from './roadmap-calendar';
import { currentMilestone, inDays, isDone, listOrder, milestoneProgress, minutesOf, nextCheckpoint, onDay, orderedMilestones, shortLength, studyBlocks, timeRange, toMinutes, weekSummary } from './roadmap-day';
import type { Session } from './types';

const Chevron = ({ back = false }: { back?: boolean }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={back ? 'm15 6-6 6 6 6' : 'm9 6 6 6-6 6'} /></svg>;
const count = (value: number, noun: string) => `${value} ${noun}${value === 1 ? '' : 's'}`;
const dayTitle = (day: string) => `${weekdayName(day)}, ${shortDate(day)}`;
export const weekRange = (day: string) => { const first = weekStart(day), last = addDays(first, 6); return monthKey(first) === monthKey(last) ? `${dayOfMonth(first)}–${dayOfMonth(last)} ${monthName(last)}` : `${shortDate(first)} – ${shortDate(last)}`; };
/** The plan's own span, so the arrows stop where the plan does. */
export function planBounds({ plan, sessions, today }: ViewContext) {
 const edges = [plan.config.start_date, plan.config.target_date, today, ...sessions.map(item => item.date), ...plan.milestones.flatMap(item => [item.projected_start, item.projected_end])].filter((value): value is string => !!value).sort();
 return { first: edges[0], last: edges[edges.length - 1] };
}
/** The task to do next: the first open, timed task that has not finished yet. */
export function upNext({ sessions, today, nowMinute }: ViewContext) {
 return [...sessions].sort((a, b) => a.date.localeCompare(b.date) || listOrder(a, b)).find(item => !isDone(item) && !!item.start_time && (item.date > today || (item.date === today && toMinutes(item.start_time) + item.duration_minutes > (nowMinute ?? 0))))?.id ?? null;
}

function WeeklyGoal({ context, onFill }: { context: ViewContext; onFill: () => void }) {
 const { sessions, today, plan } = context;
 const [unit, setUnit] = useState<'tasks' | 'hours'>('tasks');
 const goal = plan.config.weekly_minutes || 0;
 const week = weekSummary(sessions, today, today, goal);
 const circumference = 2 * Math.PI * 50;
 const arc = (minutes: number) => `${(goal ? Math.min(minutes, goal) / goal * circumference : 0).toFixed(1)} ${circumference.toFixed(1)}`;
 const backlog = sessions.some(item => item.missed);
 return <section className="rv-card" aria-labelledby="goal-h">
  <div className="rv-row-between"><h2 id="goal-h">This week’s goal <span className="rv-soft" style={{ fontSize: 13 }}>{weekRange(today)}</span></h2>
   <div className="rv-seg" role="group" aria-label="Measure the goal in"><button type="button" aria-pressed={unit === 'tasks'} onClick={() => setUnit('tasks')}>Tasks</button><button type="button" aria-pressed={unit === 'hours'} onClick={() => setUnit('hours')}>Hours</button></div></div>
  {unit === 'tasks' ? <>
   <p className="rv-big">{week.done} <span>of {count(week.total, 'task')} done</span></p>
   <p className="rv-note" style={{ marginTop: 4, fontSize: 14, color: 'var(--ink)' }}>{week.total ? `${week.due} ${week.due === 1 ? 'was' : 'were'} due by tonight. ${week.behind > 0 ? `Finish ${week.behind} more to stay on pace.` : 'You’re on pace.'}` : 'No tasks are planned for this week yet.'}</p>
   {week.total > 0 && <div className="rv-pips" role="img" aria-label={`${week.done} of ${week.total} tasks done this week; ${week.due} were due by tonight`}>
    {week.dates.filter(day => onDay(week.items, day).length).map(day => { const items = onDay(week.items, day).sort(listOrder); return <div key={day} className={`rv-pip-day${day === today ? ' today' : day < today ? ' past' : ''}`} style={{ flex: `${items.length} 1 0` }}>
     <div>{items.map(item => <span key={item.id} className={`rv-pip${isDone(item) ? ' done' : day <= today ? ' due' : ''}`} />)}</div><span>{day === today ? 'Today' : weekdayName(day)}</span></div>; })}
   </div>}
   <p className="rv-legend"><span><i className="rv-sw done" />Done</span><span><i className="rv-sw due" />Due by tonight</span><span><i className="rv-sw later" />Later this week</span></p>
  </> : <>
   <div className="rv-hours">
    <div className="rv-hours-ring">
     <svg width="120" height="120" viewBox="0 0 120 120" role="img" aria-label={`${shortLength(week.doneMinutes)} done of a ${shortLength(goal)} weekly goal; ${shortLength(week.gap)} not yet scheduled`}>
      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--cloud)" strokeWidth="12" />
      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--rv-mint-soft)" strokeWidth="12" strokeDasharray={arc(week.doneMinutes + week.scheduledLeft)} transform="rotate(-90 60 60)" />
      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--mint)" strokeWidth="12" strokeDasharray={arc(week.doneMinutes)} transform="rotate(-90 60 60)" />
     </svg>
     <div aria-hidden="true"><strong>{shortLength(week.doneMinutes)}</strong><span>of {shortLength(goal)}</span></div>
    </div>
    <div className="rv-hours-key"><span><i className="rv-sw done" />Done {shortLength(week.doneMinutes)}</span><span><i className="rv-sw sched" />Scheduled {shortLength(week.scheduledLeft)}</span><span><i className="rv-sw" />Not scheduled {shortLength(week.gap)}</span></div>
   </div>
   <p className="rv-note" style={{ marginTop: 16, fontSize: 14, color: 'var(--ink)' }}><strong>{shortLength(week.toGo)} to go</strong> this week. {week.gap > 0 ? `Your sessions cover all but ${shortLength(week.gap)}.` : 'Your sessions cover your goal.'}</p>
   {backlog && week.gap > 0 && <button className="rv-btn sm" type="button" style={{ marginTop: 12 }} onClick={onFill}>Fill the gap with backlog</button>}
  </>}
 </section>;
}

function NextCheckpoint({ context }: { context: ViewContext }) {
 const { plan, sessions, today, go } = context;
 const next = nextCheckpoint(plan); const { list, current } = currentMilestone(plan);
 const milestone = next?.milestone ?? current;
 if (!milestone) return null;
 const progress = milestoneProgress(milestone, sessions, today);
 return <section className="rv-card" aria-labelledby="cp-h">
  <div className="rv-row-between" style={{ alignItems: 'baseline' }}><h2 id="cp-h" className="rv-lab">Next checkpoint</h2>{next && <span className="rv-tag am">{inDays(today, next.checkpoint.date)}</span>}</div>
  <p style={{ margin: '12px 0 2px', fontSize: 15, fontWeight: 600 }}>{next ? next.checkpoint.title : 'No checkpoints left in this plan'}</p>
  <p className="rv-note">{next ? `${dayTitle(next.checkpoint.date)} · ` : ''}Milestone {list.indexOf(milestone) + 1}: {milestone.title}</p>
  <div className="rv-bar ink" style={{ margin: '14px 0 6px' }}><i style={{ width: `${progress.percent}%` }} /></div>
  <p className="rv-note" style={{ fontSize: 12 }}>Milestone {progress.percent}% · {progress.done} of {count(progress.total, 'session')}</p>
  <button type="button" className="rv-link" style={{ marginTop: 6 }} onClick={() => go('milestones')}>All milestones</button>
 </section>;
}

/** The day view: one date's to-do list with its timeline, and the week at a glance beside it. */
export function TodayView({ context, day, editor }: { context: ViewContext; day: string; editor: TaskEditor }) {
 const { sessions, today, go } = context;
 const [fill, setFill] = useState(0);
 const items = onDay(sessions, day); const done = items.filter(isDone);
 const { first, last } = planBounds(context);
 const percent = items.length ? Math.round(done.length / items.length * 100) : 0;
 const isToday = day === today;
 const move = (to: string) => editor.leave(() => go('day', to));
 return <div className="rv-cols">
  <section className="rv-card wide rv-main" aria-labelledby="day-title">
   <div className="rv-row-between">
    <div className="rv-nav">
     <button className="rv-ico" type="button" aria-label="Previous day" disabled={addDays(day, -1) < first} onClick={() => move(addDays(day, -1))}><Chevron back /></button>
     <h2 id="day-title" className="rv-title">{isToday ? <>Today <span>{dayTitle(day)}</span></> : dayTitle(day)}</h2>
     <button className="rv-ico" type="button" aria-label="Next day" disabled={addDays(day, 1) > last} onClick={() => move(addDays(day, 1))}><Chevron /></button>
     <BusyLabels sessions={items} />
    </div>
    <p className="rv-note" style={{ fontSize: 14 }}>{items.length ? <><strong style={{ color: 'var(--ink)' }}>{done.length} of {items.length}</strong> done · {shortLength(minutesOf(done))} of {shortLength(minutesOf(items))}</> : 'Nothing planned'}</p>
   </div>
   <div className="rv-bar" role="progressbar" aria-label={`${isToday ? 'Today’s' : 'This day’s'} tasks done`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} style={{ margin: '16px 0 8px' }}><i style={{ width: `${percent}%` }} /></div>
   {day < today && <p className="rv-note">This day has passed. You can still tick or untick tasks; anything left unticked goes to your backlog.</p>}
   <DayTimeline day={day} items={items} context={context} editor={editor} />
   {isToday && <Backlog context={context} autoOpen={fill} />}
   <p className="rv-lab" style={{ marginTop: 22 }}>{studyBlockLine(context, day)}</p>
   <TaskList day={day} items={items} context={context} editor={editor} nextId={upNext(context)} canAdd={day >= today} />
   {!items.length && day < today && <p className="rv-empty">Nothing was planned for {fullDate(day)}.</p>}
   <p className="rv-note" style={{ margin: '12px 8px 0' }}>Ticking records what you did. It doesn’t change your assessed skills.</p>
  </section>
  <aside className="rv-rail" aria-label="This week at a glance">
   <WeeklyGoal context={context} onFill={() => { if (!isToday) go('day', today); setFill(value => value + 1); }} />
   <section className="rv-card rv-next" aria-labelledby="next-h">
    <div className="rv-row-between" style={{ alignItems: 'baseline' }}><h2 id="next-h">Next 2 days</h2><button type="button" className="rv-link" onClick={() => go('week', day)}>See week</button></div>
    {[1, 2].map(offset => { const date = addDays(day, offset); const list = onDay(sessions, date).sort(listOrder); return <div key={date}>
     <h3>{date === addDays(today, 1) ? 'Tomorrow' : weekdayName(date)}, {shortDate(date)} <span>· {list.length ? `${count(list.length, 'task')}, ${shortLength(minutesOf(list))}` : 'nothing planned'}</span></h3>
     <ol>{list.map(item => <li key={item.id}><span>{timeRange(item)}</span><span>{item.title}<small>{shortLength(item.duration_minutes)}{item.skills.length ? ` · ${item.skills.map(skill => skill.name).join(', ')}` : ''}</small></span></li>)}</ol>
    </div>; })}
   </section>
   <NextCheckpoint context={context} />
  </aside>
 </div>;
}

/** The week: a completion ring per day, each day's list, and the backlog to place. */
export function WeekView({ context, day, editor }: { context: ViewContext; day: string; editor: TaskEditor }) {
 const { sessions, today, plan, go } = context;
 const [unfolded, setUnfolded] = useState<Record<string, boolean>>({});
 const goal = plan.config.weekly_minutes || 0;
 const week = weekSummary(sessions, day, today, goal);
 const current = week.dates.includes(today);
 const { first, last } = planBounds(context);
 const circumference = 2 * Math.PI * 26; const next = upNext(context);
 const rest = week.dates.filter(date => !studyBlocks(plan.config, date).length && !onDay(week.items, date).length);
 const shown = week.dates.filter(date => !rest.includes(date) && (onDay(week.items, date).length || date >= today));
 const move = (to: string) => editor.leave(() => go('week', to));
 return <div className="rv-cols">
  <section className="rv-card wide rv-main" aria-labelledby="wk-title">
   <div className="rv-row-between">
    <div className="rv-nav">
     <button className="rv-ico" type="button" aria-label="Previous week" disabled={addDays(week.dates[0], -1) < first} onClick={() => move(addDays(week.dates[0], -7))}><Chevron back /></button>
     <h2 id="wk-title" className="rv-title">{current ? 'This week' : 'Week of'} <span>{current ? weekRange(day) : shortDate(week.dates[0])}</span></h2>
     <button className="rv-ico" type="button" aria-label="Next week" disabled={addDays(week.dates[0], 7) > last} onClick={() => move(addDays(week.dates[0], 7))}><Chevron /></button>
    </div>
    <p className="rv-note" style={{ fontSize: 14 }}><strong style={{ color: 'var(--ink)' }}>{week.done} of {count(week.total, 'task')}</strong>{current ? `, ${week.due} due by tonight` : ''} · {shortLength(week.doneMinutes)}{goal ? ` of your ${shortLength(goal)} goal` : ' done'}</p>
   </div>
   <div className="rv-rings" role="group" aria-label="Tasks done each day. Choose a day to see its to-do list.">
    {week.dates.map(date => { const items = onDay(week.items, date); const done = items.filter(isDone).length; const resting = rest.includes(date);
     const sub = resting ? 'Rest day' : date === today ? 'Today' : date < today ? (items.length ? done === items.length ? 'All done' : `${items.length - done} missed` : 'Nothing planned') : count(items.length, 'task');
     return <button key={date} type="button" className={`rv-ring-btn${date === today ? ' today' : ''}`} aria-label={`${weekdayName(date)} ${shortDate(date)}: ${resting ? 'rest day' : `${done} of ${count(items.length, 'task')} done`}. Show this day’s to-do list.`} onClick={() => editor.leave(() => go('day', date))}>
      <span className="rv-ring-fig"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="26" fill="none" stroke={resting ? 'var(--cloud)' : 'var(--ready-bg)'} strokeWidth="9" /><circle cx="32" cy="32" r="26" fill="none" stroke="var(--mint)" strokeWidth="9" strokeLinecap={done ? 'round' : 'butt'} strokeDasharray={`${(items.length ? done / items.length * circumference : 0).toFixed(1)} ${circumference.toFixed(1)}`} transform="rotate(-90 32 32)" /></svg><span>{resting ? '–' : `${done}/${items.length}`}</span></span>
      <span className="rv-ring-name">{weekdayName(date)} {dayOfMonth(date)}</span><span className="rv-ring-sub">{sub}</span>
     </button>; })}
   </div>
   <p className="rv-note" style={{ fontSize: 12 }}>A full ring means every task that day is done. Today has a green outline. Choose a day to see its to-do list, including past days.</p>
   {shown.map(date => { const items = onDay(week.items, date); const done = items.filter(isDone);
    const folded = items.length > 0 && done.length === items.length && date < today && !unfolded[date];
    return <div key={date} className={`rv-day${date === today ? ' today' : ''}`}>
     <div className="rv-day-head"><div><h3><button type="button" className="rv-day-link" aria-label={`Open the to-do list for ${date === today ? 'today' : fullDate(date)}`} onClick={() => editor.leave(() => go('day', date))}>{date === today ? 'Today' : weekdayName(date)} <span>{shortDate(date)}</span></button></h3><BusyLabels sessions={items} /></div>
      <span>{items.length ? `${done.length} of ${items.length} done · ${shortLength(minutesOf(items))}` : 'Nothing planned'}</span></div>
     {folded ? <button type="button" className="rv-fold" onClick={() => setUnfolded(value => ({ ...value, [date]: true }))}>All {items.length} done · show</button>
      : <TaskList day={date} items={items} context={context} editor={editor} nextId={next} canAdd={date >= today} addLabel={`Add a task to ${date === today ? 'today' : `${weekdayName(date)} ${shortDate(date)}`}`} />}
    </div>; })}
   {!week.total && <p className="rv-empty">{week.dates[6] < today ? 'No sessions were planned for this week.' : 'Sessions for this week aren’t planned yet. elo plans one week at a time.'}</p>}
   {rest.length > 0 && <p className="rv-note" style={{ margin: '14px 6px 0' }}>{rest.map(date => `${weekdayName(date)} ${dayOfMonth(date)}`).join(' and ')} {rest.length === 1 ? 'is a rest day' : 'are rest days'} in your plan. Use Plan settings to preview the next week when you reach it.</p>}
  </section>
  <aside className="rv-rail" aria-label="Backlog">
   <Backlog context={context} panel />
   <section className="rv-card" aria-labelledby="fit-h">
    <h2 id="fit-h" className="rv-lab">Room this week</h2>
    <p style={{ margin: '10px 0 4px', fontSize: 22, fontWeight: 600 }}>{goal ? `${shortLength(week.gap)} free` : 'No weekly goal'}</p>
    <p className="rv-note">{goal ? week.gap > 0 ? `Your ${shortLength(goal)} goal has ${shortLength(week.gap)} without a session. Backlog items and new tasks fit inside your study blocks.` : `Your sessions cover your ${shortLength(goal)} goal for this week.` : 'Set a weekly study budget in Plan settings to see how much room is left.'}</p>
   </section>
  </aside>
 </div>;
}

const Flag = ({ size = 11 }: { size?: number }) => <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><path d="M5 22V3h11l-2 4 2 4H5" fill="currentColor" /></svg>;
const chipState = (session: Session) => isDone(session) ? 'done' : session.missed ? 'miss' : 'up';
const chipText = (session: Session) => isDone(session) ? `✓ ${session.title}` : session.missed ? `Missed · ${session.title}` : `${session.start_time ? `${session.start_time} ` : ''}${session.title}`;

/** The month as a calendar: tasks as chips, milestones as bars, checkpoints as flags. */
export function MonthView({ context, day }: { context: ViewContext; day: string }) {
 const { sessions, today, plan, go, actions, frozen } = context;
 const [selected, setSelected] = useState<string | null>(null); const [moving, setMoving] = useState(false); const [message, setMessage] = useState('');
 const { first, last } = planBounds(context);
 const milestones = orderedMilestones(plan);
 const checkpoints = milestones.flatMap(milestone => (milestone.checkpoints || []).map(checkpoint => ({ ...checkpoint, milestone })));
 const lastDated = sessions.map(item => item.date).sort().pop() ?? today;
 const inMonth = sessions.filter(item => monthKey(item.date) === monthKey(day));
 const due = inMonth.filter(item => item.date <= today);
 const monthCheckpoints = checkpoints.filter(item => monthKey(item.date) === monthKey(day));
 const session = sessions.find(item => item.id === selected);
 const milestoneOf = (item: Session) => { const index = milestones.findIndex(entry => entry.key === item.milestone_key); return index < 0 ? 'None' : `${index + 1} · ${milestones[index].title}`; };
 const pick = (id: string | null) => { setSelected(id); setMoving(false); setMessage(''); };
 const status = session && (isDone(session) ? ['Done', 'sk'] : session.missed ? ['Missed', 'am'] : [session.date === today ? 'Today' : 'Scheduled', 'dk']);
 return <div className="rv-cols">
  <section className="rv-card rv-main" style={{ flexBasis: 640 }} aria-labelledby="m-title">
   <div className="rv-row-between" style={{ marginBottom: 14 }}>
    <div className="rv-nav">
     <button className="rv-ico" type="button" aria-label="Previous month" disabled={monthKey(addMonths(day, -1)) < monthKey(first)} onClick={() => go('month', addMonths(day, -1))}><Chevron back /></button>
     <h2 id="m-title" className="rv-title">{monthTitle(day)}</h2>
     <button className="rv-ico" type="button" aria-label="Next month" disabled={monthKey(addMonths(day, 1)) > monthKey(last)} onClick={() => go('month', addMonths(day, 1))}><Chevron /></button>
    </div>
    <p className="rv-legend" style={{ margin: 0 }}><span><i className="rv-chip key done" />Done</span><span><i className="rv-chip key miss" />Missed</span><span><i className="rv-chip key up" />Scheduled</span><span><i className="rv-chip key proj" />Study time, sessions not planned yet</span><span><Flag size={12} />Checkpoint</span></p>
   </div>
   <div className="rv-month-scroll"><div className="rv-month">
    <div className="rv-month-head" aria-hidden="true">{weekDates('2030-01-07').map(date => <span key={date}>{weekdayName(date)}</span>)}</div>
    {monthWeeks(day).map(monday => {
     const bars = milestones.flatMap((milestone, index) => { const columns = weekColumns(monday, milestone.projected_start, milestone.projected_end); return columns ? [{ milestone, index, ...columns }] : []; });
     return <div className="rv-month-week" key={monday}>
      {bars.length > 0 && <div className="rv-month-bars">{bars.map(({ milestone, index, from, to, startsHere }) => <button key={milestone.id} type="button" className={`rv-mbar${startsHere ? '' : ' cont'}${milestone.outcome.demonstrated ? ' reached' : ''}`} style={{ gridColumn: `${from} / ${to + 1}` }} onClick={() => go('milestones')}>{index + 1} · {milestone.title}{milestone.outcome.demonstrated ? ' ✓' : startsHere ? '' : ' (continues)'}</button>)}</div>}
      <div className="rv-month-days">{weekDates(monday).map(date => {
       const items = onDay(sessions, date).sort(listOrder); const done = items.filter(isDone);
       const flag = checkpoints.find(item => item.date === date);
       const study = studyBlocks(plan.config, date).reduce((total, [start, end]) => total + end - start, 0);
       const projected = !items.length && date > lastDated && date > today && study > 0 && !!plan.config.target_date && date <= plan.config.target_date;
       return <div key={date} className={`rv-cell${monthKey(date) !== monthKey(day) ? ' outside' : ''}${date === today ? ' today' : ''}`}>
        <button type="button" className="rv-daylink" aria-label={`Open ${fullDate(date)} in Today`} onClick={() => go('day', date)} />
        <div className="rv-cell-top"><span className="rv-cell-num">{dayOfMonth(date)}</span>{items.length > 0 && <span className="rv-cell-hours">{done.length && done.length < items.length ? `${shortLength(minutesOf(done))} / ` : ''}{shortLength(minutesOf(items))}</span>}</div>
        {flag && <span className="rv-flag"><Flag />{flag.title}</span>}
        {items.slice(0, 2).map(item => <button key={item.id} type="button" className={`rv-chip ${chipState(item)}`} aria-pressed={selected === item.id} aria-label={`Details: ${item.title}${item.start_time ? `, ${item.start_time}` : ''}`} onClick={() => pick(item.id)}>{chipText(item)}</button>)}
        {items.length > 2 && <span className="rv-more">+{items.length - 2} more</span>}
        {projected && <span className="rv-chip proj">{shortLength(study)} study time</span>}
       </div>; })}</div>
     </div>; })}
   </div></div>
   <p className="rv-note" style={{ marginTop: 12 }}>Choose a day to open it in Today, or a task to see its details. elo dates sessions one week ahead, so later weeks show your study time until they’re planned.</p>
  </section>
  <aside className="rv-rail" style={{ maxWidth: 360 }} aria-label={`Details and ${monthName(day)} summary`}>
   {session && status && <section className="rv-card" style={{ border: '2px solid var(--ink)' }} aria-labelledby="td-h">
    <div className="rv-row-between"><span className={`rv-tag ${status[1]}`} style={{ fontWeight: 600 }}>{status[0]}</span><button className="rv-ico" type="button" aria-label="Close task details" onClick={() => pick(null)}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg></button></div>
    <h2 id="td-h" style={{ marginTop: 10, fontSize: 19, lineHeight: 1.35 }}>{session.title}</h2>
    <dl className="rv-dl-list"><dt>When</dt><dd>{dayTitle(session.date)}, {session.start_time ? timeRange(session) : 'any time'}</dd><dt>Length</dt><dd>{shortLength(session.duration_minutes)}</dd><dt>Skills</dt><dd>{session.skills.length ? session.skills.map(skill => skill.name).join(', ') : 'No specific skill'}</dd><dt>Milestone</dt><dd>{milestoneOf(session)}</dd></dl>
    <h3 style={{ margin: '18px 0 4px', fontSize: 14, fontWeight: 600 }}>Done when</h3>
    <p className="rv-note" style={{ fontSize: 14, color: 'var(--ink)' }}>{session.completion_criterion}</p>
    {session.missed && <p className="rv-rs-rest" style={{ marginTop: 16, fontSize: 14 }}>You didn’t tick this off. It’s waiting in your backlog.</p>}
    <div className="rv-chips" style={{ marginTop: 18 }}>
     {!isDone(session) && <button className="rv-btn sm pri" type="button" disabled={frozen} onClick={() => void actions.setDone(session, true)}>Mark done</button>}
     {!isDone(session) && <button className="rv-btn sm" type="button" aria-expanded={moving} onClick={() => setMoving(value => !value)}>Move to another day</button>}
     <button className="rv-btn sm" type="button" onClick={() => go('day', session.date)}>Open {weekdayName(session.date)} {dayOfMonth(session.date)} in Today</button>
    </div>
    {moving && <div style={{ marginTop: 14 }}><ReschedulePanel session={session} context={context} onClose={() => setMoving(false)} onMoved={text => { setMoving(false); setMessage(text); }} /></div>}
    {message && <p className="rv-status" role="status">{message}</p>}
   </section>}
   <section className="rv-card" aria-labelledby="ms-h">
    <h2 id="ms-h" className="rv-lab">{monthName(day)} {monthKey(day) <= monthKey(today) ? 'so far' : 'ahead'}</h2>
    <dl className="rv-stats">
     <div><dt>Hours logged</dt><dd>{shortLength(minutesOf(inMonth.filter(isDone)))}</dd></div>
     <div><dt>Tasks done</dt><dd>{inMonth.filter(isDone).length}<span> / {due.length} due</span></dd></div>
     <div><dt>Missed</dt><dd>{inMonth.filter(item => item.missed).length}</dd></div>
     <div><dt>Checkpoints</dt><dd>{monthCheckpoints.filter(item => item.reached_at).length}<span> / {monthCheckpoints.length}</span></dd></div>
    </dl>
   </section>
   <section className="rv-card" aria-labelledby="mm-h">
    <h2 id="mm-h" className="rv-lab">Milestones this month</h2>
    <ul className="rv-plain">{milestones.map((milestone, index) => ({ milestone, index })).filter(({ milestone }) => monthKey(milestone.projected_start) <= monthKey(day) && monthKey(milestone.projected_end) >= monthKey(day)).map(({ milestone, index }) => { const progress = milestoneProgress(milestone, sessions, today);
     return <li key={milestone.id}><div className="rv-row-between" style={{ flexWrap: 'nowrap', alignItems: 'baseline' }}><strong style={{ fontWeight: 600 }}>{index + 1} · {milestone.title}</strong>{milestone.outcome.demonstrated ? <span className="rv-tag sk">Reached</span> : <span className="rv-note" style={{ fontSize: 12 }}>{progress.percent}%</span>}</div>
      <div className="rv-bar thin ink" style={{ marginTop: 8 }}><i style={{ width: `${progress.percent}%`, background: milestone.outcome.demonstrated ? 'var(--mint)' : undefined }} /></div>
      {!milestone.outcome.demonstrated && <p className="rv-note" style={{ marginTop: 6, fontSize: 12 }}>Projected to finish {fullDate(milestone.projected_end)}</p>}</li>; })}</ul>
    <button type="button" className="rv-link" style={{ marginTop: 10 }} onClick={() => go('milestones')}>Open milestones</button>
   </section>
  </aside>
 </div>;
}
export { Tick };

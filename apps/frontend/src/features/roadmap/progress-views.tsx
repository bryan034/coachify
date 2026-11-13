"use client";
import { useState } from 'react';
import { Tick, type ViewContext } from './day-list';
import { addDays, dayOfMonth, fullDate, shortDate, weekDates, weekStart, weekdayName } from './roadmap-calendar';
import { currentMilestone, daysBetween, inDays, isDone, milestoneProgress, minutesOf, onDay, progressBars, recentPace, shortLength, skillCounts, studyStreak, weekSummary } from './roadmap-day';
import { weekRange } from './calendar-views';
import type { Confirmation, PlanGap, PlanMilestone, Planner } from './types';

const count = (value: number, noun: string) => `${value} ${noun}${value === 1 ? '' : 's'}`;
const answers: [Confirmation['answer'], string][] = [['have_experience', 'Yes'], ['some_experience', 'Somewhat'], ['no_experience', 'No'], ['not_sure', 'Not sure']];

/** elo's experience questions. An answer only shapes the plan; it never edits the Skills Profile. */
export function GapQuestions({ gaps, confirmations, frozen, confirm }: { gaps: PlanGap[]; confirmations: Planner['confirmations']; frozen: boolean; confirm: (gap: PlanGap, answer: Confirmation['answer']) => void }) {
 const asked = gaps.filter(gap => gap.resolution === 'confirm_experience' && gap.confirmation_question);
 if (!asked.length) return null;
 return <section className="rv-card" aria-labelledby="ask-h">
  <h2 id="ask-h" className="rv-lab">Questions from elo</h2>
  {asked.map(gap => <fieldset className="rv-question" key={gap.id} disabled={frozen}><legend>{gap.confirmation_question}</legend>
   <div className="rv-chips">{answers.map(([value, label]) => <label key={value} className={`rv-opt${confirmations[gap.id]?.answer === value ? ' on' : ''}`}><input type="radio" className="rv-vh" name={`confirm-${gap.id}`} checked={confirmations[gap.id]?.answer === value} onChange={() => confirm(gap, value)} />{label}</label>)}</div></fieldset>)}
  <p className="rv-note" style={{ marginTop: 12, fontSize: 12 }}>Your answers only affect this plan. To change your saved evidence, update your Skills Profile.</p>
 </section>;
}

function OutcomeForm({ milestone, frozen, record }: { milestone: PlanMilestone; frozen: boolean; record: (demonstrated: boolean, note: string) => void }) {
 const [open, setOpen] = useState(false); const [note, setNote] = useState('');
 if (milestone.outcome.demonstrated) return <p style={{ marginBottom: 0 }}>You recorded: {milestone.outcome.note} <button type="button" className="rv-link" disabled={frozen} onClick={() => record(false, '')}>Remove</button></p>;
 if (!open) return <button className="rv-btn sm pri" type="button" disabled={frozen} onClick={() => setOpen(true)}>Record how you showed it</button>;
 return <form onSubmit={event => { event.preventDefault(); if (note.trim()) record(true, note.trim()); }}>
  <label htmlFor={`show-${milestone.id}`}>How did you show it?</label>
  <textarea id={`show-${milestone.id}`} className="rv-input" required maxLength={2000} autoFocus value={note} onChange={event => setNote(event.target.value)} />
  <div className="rv-chips"><button className="rv-btn sm pri" disabled={frozen || !note.trim()}>Save</button><button type="button" className="rv-btn sm" onClick={() => setOpen(false)}>Cancel</button></div>
 </form>;
}

function Checkpoints({ milestone, context, readOnly }: { milestone: PlanMilestone; context: ViewContext; readOnly: boolean }) {
 const items = milestone.checkpoints || []; const { today, actions, frozen } = context;
 if (!items.length) return <p className="rv-note" style={{ marginTop: 6 }}>This plan was made before checkpoints. They’ll appear when elo next updates your roadmap.</p>;
 const next = items.find(item => !item.reached_at);
 return <ol className="rv-cps">{items.map((item, index) => <li key={item.key} className={`rv-cp${item === next ? ' next' : ''}`}>
  <button type="button" className="rv-cp-tick" aria-pressed={!!item.reached_at} aria-label={`${item.reached_at ? 'Mark not reached' : 'Mark reached'}: ${item.title}`} disabled={frozen || readOnly} onClick={() => actions.reachCheckpoint(milestone, item.key, !item.reached_at)}><i>{item.reached_at && <Tick size={11} />}</i></button>
  <div>{item.title}<small>{item.reached_at ? `Reached ${fullDate(item.reached_at.slice(0, 10))}` : `${weekdayName(item.date)}, ${shortDate(item.date)}${index === items.length - 1 ? ' · completes the milestone' : ''}`}</small></div>
  {item === next && <span className="rv-tag am">{inDays(today, item.date)}</span>}
 </li>)}</ol>;
}

/** The route to the goal, the milestone in hand with its checkpoints, and what the plan adds up to. */
export function MilestonesView({ context, planner }: { context: ViewContext; planner: Planner }) {
 const { plan, sessions, today, actions, frozen } = context;
 const { list, current, allReached } = currentMilestone(plan);
 const target = plan.config.target_date;
 const reached = list.filter(item => item.outcome.demonstrated).length;
 const marks = list.flatMap(item => item.checkpoints || []);
 const span = Math.max(daysBetween(plan.config.start_date || plan.first_planning_week, target || today), 1);
 const walked = Math.min(Math.max(daysBetween(plan.config.start_date || plan.first_planning_week, today) / span, 0), 1);
 const skills = skillCounts(sessions);
 return <>
  <section className="rv-card rv-route" aria-labelledby="route-h">
   <div className="rv-row-between" style={{ alignItems: 'baseline' }}><h2 id="route-h">Your route to {plan.assessment.role}</h2><p>{reached} of {count(list.length, 'milestone')} reached{marks.length ? ` · ${marks.filter(item => item.reached_at).length} of ${count(marks.length, 'checkpoint')}` : ''}</p></div>
   <ol>
    <li aria-hidden="true" className="rv-route-line" /><li aria-hidden="true" className="rv-route-walked" style={{ width: `calc((100% - 36px) * ${walked.toFixed(3)})` }} />
    {list.map((milestone, index) => { const done = milestone.outcome.demonstrated, here = milestone === current && !allReached; const progress = milestoneProgress(milestone, sessions, today);
     return <li className="stop" key={milestone.id}><span className={`rv-stop${done ? ' reached' : here ? ' here' : ''}`}>{done ? <Tick /> : index + 1}</span><strong>{milestone.title}</strong>
      <small>{done ? `Reached${milestone.outcome.recorded_at ? ` ${shortDate(milestone.outcome.recorded_at.slice(0, 10))}` : ''}` : here ? `You are here · ${progress.percent}%` : `By ${shortDate(milestone.projected_end)}`}</small></li>; })}
    <li className="stop"><span className="rv-stop reached" aria-hidden="true">★</span><strong>Ready to apply</strong><small>{target ? fullDate(target) : 'No target date'}</small></li>
   </ol>
  </section>
  <div className="rv-cols">
   <div className="rv-ms-list">
    {!list.length && <p className="rv-empty">No milestones are needed for this plan.</p>}
    {list.map((milestone, index) => {
     const progress = milestoneProgress(milestone, sessions, today); const marksHere = milestone.checkpoints || [];
     const names = plan.gaps.filter(gap => milestone.gap_ids.includes(gap.id)).map(gap => gap.name);
     if (milestone !== current || allReached) return <details className="rv-card rv-ms" key={milestone.id}>
      <summary><span className={`rv-stop sm ${milestone.outcome.demonstrated ? 'reached' : 'plain'}`}>{milestone.outcome.demonstrated ? <Tick size={12} /> : index + 1}</span><strong>{milestone.title}</strong>
       {milestone.outcome.demonstrated && <span className="rv-tag sk">Reached</span>}
       <span>{milestone.outcome.demonstrated ? `${progress.done} of ${count(progress.total, 'session')}` : `${shortDate(milestone.projected_start)} – ${shortDate(milestone.projected_end)}${marksHere.length ? ` · ${count(marksHere.length, 'checkpoint')}` : ''}`}</span></summary>
      <div className="rv-ms-body" style={{ marginTop: 12 }}>
       <p className="rv-note" style={{ fontSize: 14 }}>Show this: {milestone.demonstrable_outcome}</p>
       <p className="rv-lab" style={{ marginTop: 14 }}>Checkpoints</p><Checkpoints milestone={milestone} context={context} readOnly={false} />
       <div className="rv-show"><OutcomeForm milestone={milestone} frozen={frozen} record={(demonstrated, note) => actions.recordOutcome(milestone, demonstrated, note)} /></div>
      </div>
     </details>;
     return <section className="rv-card rv-ms current" key={milestone.id} aria-labelledby="ms-current">
      <div className="rv-ms-top"><span className="rv-stop sm ink">{index + 1}</span><h2 id="ms-current">{milestone.title}</h2><span className="rv-tag dk">In progress</span></div>
      <div className="rv-ms-body">
       <p className="rv-note" style={{ marginTop: 8 }}>{shortDate(milestone.projected_start)} – {fullDate(milestone.projected_end)} (projected){names.length ? ` · ${names.join(' · ')}` : ''}</p>
       <div className="rv-ms-figs">
        <div><p>Progress</p><p className="fig">{progress.percent}%</p><div className="rv-bar ink"><i style={{ width: `${progress.percent}%` }} /></div></div>
        <div><p>Tasks</p><p className="fig">{progress.done} <span>of {progress.total}</span></p>{progress.expected > progress.done && <p className="late">{progress.expected} expected by today</p>}</div>
        <div><p>Time</p><p className="fig">{shortLength(progress.doneMinutes)} <span>of {shortLength(progress.totalMinutes)}</span></p></div>
       </div>
       <p className="rv-lab" style={{ marginTop: 20 }}>Checkpoints</p><Checkpoints milestone={milestone} context={context} readOnly={false} />
       <div className="rv-show"><p className="rv-lab">Show this to reach the milestone</p><p>{milestone.demonstrable_outcome}</p><OutcomeForm milestone={milestone} frozen={frozen} record={(demonstrated, note) => actions.recordOutcome(milestone, demonstrated, note)} /></div>
      </div>
     </section>;
    })}
    <p className="rv-note" style={{ margin: '2px 4px 0' }}>Dates after this week are projections. Finishing sessions records progress, not proficiency.</p>
   </div>
   <aside className="rv-rail" aria-label="Outcome and skills">
    <section className="rv-card" aria-labelledby="reach-h">
     <h2 id="reach-h" className="rv-lab">{target ? `By ${weekdayName(target)}, ${shortDate(target)} you can show` : 'What you can show'}</h2>
     <p className="rv-note" style={{ marginTop: 12, fontSize: 14, color: 'var(--ink)' }}>{plan.deadline_outcome.summary}</p>
     {plan.deadline_outcome.achievable_by_target.length > 0 && <ul className="rv-bullets">{plan.deadline_outcome.achievable_by_target.map((item, index) => <li key={index}>{item}</li>)}</ul>}
     <p className="rv-note" style={{ marginTop: 12, fontSize: 12 }}>A projection, not a guarantee of readiness.</p>
     {plan.beyond_deadline.length > 0 && <><p className="rv-lab" style={{ marginTop: 16 }}>Doesn’t fit before your date</p><ul className="rv-bullets">{plan.beyond_deadline.map((item, index) => <li key={index}>{item.title}, about {shortLength(item.estimated_minutes)}</li>)}</ul></>}
    </section>
    <section className="rv-card" aria-labelledby="sk-h">
     <h2 id="sk-h" className="rv-lab">Skills these build</h2>
     {skills.length ? <ul className="rv-skill-rows">{skills.map(skill => <li key={skill.name}><div><span>{skill.name}</span><span>{skill.done} of {skill.total}</span></div><div className="rv-bar thin"><i style={{ width: `${skill.done / skill.total * 100}%` }} /></div></li>)}</ul> : <p className="rv-note" style={{ marginTop: 12 }}>No sessions are linked to a skill yet.</p>}
     <p className="rv-note" style={{ marginTop: 12, fontSize: 12 }}>Sessions done of sessions planned.</p>
    </section>
    <GapQuestions gaps={plan.gaps} confirmations={planner.confirmations} frozen={frozen} confirm={actions.confirm} />
   </aside>
  </div>
 </>;
}

/** Tasks and hours against the plan: this week's figures, a chart, the pace and time by skill. */
export function ProgressView({ context }: { context: ViewContext }) {
 const { plan, sessions, today, go } = context;
 const [measure, setMeasure] = useState<'tasks' | 'hours'>('tasks'); const [group, setGroup] = useState<'day' | 'week'>('day');
 const goal = plan.config.weekly_minutes || 0;
 const week = weekSummary(sessions, today, today, goal);
 const todays = onDay(sessions, today); const doneToday = todays.filter(isDone);
 const logged = sessions.filter(isDone); const start = plan.config.start_date || plan.first_planning_week;
 const streak = studyStreak(sessions, today);
 const bars = progressBars(sessions, today, measure, group, start, plan.config.target_date || today);
 const studyDays = weekDates(today).filter(day => plan.config.blocks.some(block => block.day === (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7)).length || 7;
 const line = measure === 'hours' && goal ? (group === 'day' ? goal / studyDays : goal) : 0;
 const top = Math.max(...bars.map(bar => Math.max(bar.planned, bar.done)), line, 1) * 1.15;
 const show = (value: number) => measure === 'tasks' ? String(value) : shortLength(value);
 const label = (bar: (typeof bars)[number]) => group === 'day' ? `${weekdayName(bar.label)} ${dayOfMonth(bar.label)}` : weekRange(bar.label);
 const pace = recentPace(sessions, today, start); const { current, index, allReached } = currentMilestone(plan);
 const left = current ? current.estimated_minutes : 0;
 const finish = current && !allReached && pace.minutes > 0 ? addDays(today, Math.ceil(left / pace.minutes * 7)) : null;
 const backlog = sessions.filter(item => item.missed);
 const bySkill = skillCounts(sessions).filter(item => item.minutes > 0).sort((a, b) => b.minutes - a.minutes);
 const shownSkills = bySkill.slice(0, 5); const skillTotal = shownSkills.reduce((total, item) => total + item.minutes, 0);
 const dueSoFar = sessions.filter(item => item.date <= today);
 return <>
  <dl className="rv-kpis">
   <div className="rv-card rv-kpi"><dt>This week</dt><dd>{shortLength(week.doneMinutes)}{goal > 0 && <span> / {shortLength(goal)}</span>}</dd>{goal > 0 && <div className="rv-bar"><i style={{ width: `${Math.min(week.doneMinutes / goal, 1) * 100}%` }} /></div>}<p>{goal ? week.toGo > 0 ? `${shortLength(week.toGo)} to your weekly goal` : 'Weekly goal reached' : 'No weekly goal set'}</p></div>
   <div className="rv-card rv-kpi"><dt>Tasks this week</dt><dd>{week.done}<span> / {week.total}</span></dd>
    {week.total > 0 && <div className="rv-kpi-pips" aria-hidden="true">{Array.from({ length: week.total }, (_, position) => <i key={position} className={position < week.done ? 'done' : position < week.due ? 'due' : undefined} />)}</div>}
    <p>{week.total ? `${week.due} ${week.due === 1 ? 'was' : 'were'} due by tonight${week.behind ? `, so you’re ${week.behind} behind` : ''}` : 'Nothing planned this week yet'}</p></div>
   <div className="rv-card rv-kpi"><dt>Today</dt><dd>{shortLength(minutesOf(doneToday))}<span> / {shortLength(minutesOf(todays))}</span></dd><p>{todays.length ? `${count(todays.length - doneToday.length, 'session')} left today` : 'Nothing planned today'}</p></div>
   <div className="rv-card rv-kpi"><dt>Logged since {shortDate(start)}</dt><dd>{shortLength(minutesOf(logged))}</dd><p>Across {count(logged.length, 'session')}</p></div>
   <div className="rv-card rv-kpi"><dt>Study streak</dt><dd>{count(streak, 'day')}</dd><p>Days with nothing planned don’t break it</p></div>
  </dl>
  <div className="rv-cols">
   <section className="rv-card rv-main" style={{ padding: '24px 28px', flexBasis: 560 }} aria-labelledby="hrs-h">
    <div className="rv-row-between">
     <h2 id="hrs-h" style={{ fontSize: 18 }}>{measure === 'tasks' ? group === 'day' ? 'Tasks done against expected, this week' : 'Tasks done against planned, by week' : group === 'day' ? 'Hours this week, by day' : 'Hours by week'}</h2>
     <div className="rv-chips"><div className="rv-seg" role="group" aria-label="Measure"><button type="button" aria-pressed={measure === 'tasks'} onClick={() => setMeasure('tasks')}>Tasks</button><button type="button" aria-pressed={measure === 'hours'} onClick={() => setMeasure('hours')}>Hours</button></div>
      <div className="rv-seg" role="group" aria-label="Group by"><button type="button" aria-pressed={group === 'day'} onClick={() => setGroup('day')}>By day</button><button type="button" aria-pressed={group === 'week'} onClick={() => setGroup('week')}>By week</button></div></div>
    </div>
    <p className="rv-note" style={{ marginTop: 6 }}>{measure === 'tasks' && group === 'day' ? `Each bar is a running total: ${week.due} ${week.due === 1 ? 'task was' : 'tasks were'} due by tonight and ${week.done} ${week.done === 1 ? 'is' : 'are'} done. Dashed bars are what’s still ahead.` : group === 'week' ? 'Later weeks have no dated tasks yet. Use Plan settings to preview the next week when you reach it.' : `${shortLength(week.doneMinutes)} logged of ${shortLength(week.planned)} planned this week.`}</p>
    <div className="rv-chart" role="img" style={{ gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))` }} aria-label={`${measure === 'tasks' ? 'Tasks' : 'Hours'} ${group === 'day' ? 'by day this week' : 'by week'}: ${bars.map(bar => `${label(bar)} ${show(bar.done)} of ${show(bar.planned)}`).join(', ')}`}>
     {line > 0 && <div className="rv-chart-goal" aria-hidden="true" style={{ bottom: line / top * 200 }}><span>{group === 'day' ? `${shortLength(Math.round(line))} a day` : `${shortLength(goal)} goal`}</span></div>}
     {bars.map(bar => <div className="rv-chart-col" key={bar.key}><span>{bar.when === 'ahead' ? bar.planned ? show(bar.planned) : measure === 'tasks' ? 'Not planned' : '–' : measure === 'tasks' ? `${bar.done} / ${bar.planned}` : show(bar.done)}</span>
      <div className={`rv-chart-plan${bar.when === 'ahead' ? ' ahead' : ''}`} style={{ height: Math.max(Math.max(bar.planned, bar.done) / top * 200, 2) }}><i style={{ height: `${Math.max(bar.planned, bar.done) ? bar.done / Math.max(bar.planned, bar.done) * 100 : 0}%` }} /></div></div>)}
    </div>
    <div className="rv-chart-labels" style={{ gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))` }}>{bars.map(bar => <span key={bar.key} className={bar.when === 'now' ? 'now' : undefined}>{label(bar)}</span>)}</div>
    <p className="rv-legend" style={{ marginTop: 16 }}><span><i className="rv-sw done" />{measure === 'tasks' ? 'Done' : 'Logged'}</span><span><i className="rv-sw" />{measure === 'tasks' && group === 'day' ? 'Expected by that day' : 'Planned'}</span>{line > 0 && <span><i className="rv-sw line" />Goal</span>}</p>
   </section>
   <aside className="rv-rail" aria-label="Pace and time by skill">
    <section className="rv-card rv-pace" aria-labelledby="pace-h">
     <h2 id="pace-h" className="rv-lab">Pace check</h2>
     <p><strong>{pace.weeks ? `Your recent pace is ${shortLength(pace.minutes)} a week.` : `You’ve logged ${shortLength(pace.minutes)} so far this week.`}</strong>{finish && current ? ` At that pace Milestone ${index + 1} finishes around ${fullDate(finish)}${finish > current.projected_end ? `, after its projected ${shortDate(current.projected_end)}` : ', on or before its projected date'}.` : ''}</p>
     <p>By tasks, you’ve finished {dueSoFar.filter(isDone).length} of the {dueSoFar.length} due since {shortDate(start)}.</p>
     {(goal > 0 || backlog.length > 0) && <p className="rv-note">{goal > 0 ? `Your weekly goal is ${shortLength(goal)}. ` : ''}{backlog.length > 0 ? `Clearing the ${count(backlog.length, 'backlog session')} adds ${shortLength(minutesOf(backlog))}.` : ''}</p>}
     {backlog.length > 0 && <button className="rv-btn sm" type="button" style={{ marginTop: 14 }} onClick={() => go('week', weekStart(today))}>Plan the backlog</button>}
    </section>
    <section className="rv-card" aria-labelledby="skill-h">
     <h2 id="skill-h" className="rv-lab">Time by skill</h2>
     {shownSkills.length ? <>
      <div className="rv-split" role="img" aria-label={`Time logged by skill: ${shownSkills.map(item => `${item.name} ${shortLength(Math.round(item.minutes))}`).join(', ')}`}>{shownSkills.map((item, position) => <span key={item.name} className={`rv-tone-${position}`} style={{ width: `${item.minutes / skillTotal * 100}%` }} />)}</div>
      <ul className="rv-split-key">{shownSkills.map((item, position) => <li key={item.name}><i className={`rv-sw rv-tone-${position}`} /><span>{item.name}</span><strong>{shortLength(Math.round(item.minutes))}</strong></li>)}</ul>
     </> : <p className="rv-note" style={{ marginTop: 12 }}>Tick off a session to see where your time goes.</p>}
    </section>
   </aside>
  </div>
 </>;
}

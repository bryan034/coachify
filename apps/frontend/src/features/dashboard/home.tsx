"use client";
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CardSkeleton } from '@/components/ui/workspace-ui';
import { useToast } from '@/components/ui/toast';
import { announceInputsChanged, useComparison } from '@/features/assessment/comparison';
import { sourceLink } from '@/features/career/source-links';
import { AccountPanel } from '@/features/profile/account-panel';
import { useProfile } from '@/features/profile/profile-provider';
import type { Workspace } from '@/features/roadmap/types';
import { careerApi, type CurrentGoal, type IntelligenceFinding, type OpportunityView } from '@/lib/api/career';
import type { Application } from '@/lib/api/jobs';
import { roadmapApi } from '@/lib/api/roadmap';
import { loadApplications, loadGoal, loadRoadmap, loadSkills, useSection, type Section, type SkillsSummary } from '@/lib/api/workspace-summary';
import { errorText } from '@/lib/errors';
import { formatDate, formatDayMonthYear } from '@/lib/format';
import { daysBetween, homeSessions, hours, longDay, monthTicks, nextCheckpoint, nextTasks, planWeek, plural, recentWins, shortDate, timeline, weekDays, weeksOnTrack, type HomeSession } from './home-data';
import '@/styles/workspace-pages.css';

type Flag = boolean | 'loading' | 'error';
export type StopState = 'done' | 'next' | 'later' | 'checking' | 'unavailable';
const flag = <T,>(section: Section<T>, test: (data: T) => boolean): Flag => section.status === 'ready' ? test(section.data) : section.status;

/** The set-up steps, in the order the pages build on each other. */
const stops = [
 { name: 'Background', href: '/profile', x: 6, y: 84 },
 { name: 'Career goal', href: '/career-goal', x: 28, y: 61 },
 { name: 'Skills profile', href: '/cv', x: 50, y: 38 },
 { name: 'Roadmap', href: '/roadmap', x: 72, y: 15 },
];
const stateWords: Record<StopState, string> = { done: 'Done', next: 'Up next', later: 'Later', checking: 'Checking', unavailable: 'Not available' };

/** The first unfinished stop is only named once every stop is known, so the path never points at the wrong one. */
export function journeyStates(flags: Flag[]): StopState[] {
 const settled = flags.every(value => value !== 'loading');
 const next = settled ? flags.indexOf(false) : -1;
 return flags.map((value, index) => value === true ? 'done' : value === 'loading' ? 'checking' : value === 'error' ? 'unavailable' : index === next ? 'next' : settled ? 'later' : 'checking');
}

function Unavailable({ message, retry, label }: { message: string; retry: () => void; label: string }) {
 return <div className="ws-error" role="alert"><p>{message}</p><button type="button" className="ws-mini" onClick={retry}>Retry {label}</button></div>;
}

/* ---------- Hero ---------- */
type Step = { label: string; when: string; title: string; chips: string[]; go: string; href: string; after: string };

function SetupPath({ states }: { states: StopState[] }) {
 const done = states.filter(state => state === 'done').length;
 return <div className="ws-hero-path">
  <div className="ws-tl-top"><span><b>Setting up</b></span>{!states.includes('unavailable') && <span>{done} of {stops.length} steps done</span>}</div>
  <div className="ws-journey">
   <svg className="ws-journey-line" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
    {stops.slice(1).map((stop, index) => { const from = stops[index], walked = states[index] === 'done' && (states[index + 1] === 'done' || states[index + 1] === 'next');
     return <line key={stop.name} className={walked ? 'is-walked' : ''} x1={from.x} y1={from.y} x2={stop.x} y2={stop.y} vectorEffect="non-scaling-stroke"/>; })}
   </svg>
   <ol aria-label="Setup steps">
    {stops.map((stop, index) => <li key={stop.name} className={`ws-stop is-${states[index]}`} style={{ left: `${stop.x}%`, top: `${stop.y}%` }}>
     <Link href={stop.href} aria-current={states[index] === 'next' ? 'step' : undefined}><span className="ws-stop-node">{states[index] === 'done' && <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m4 8.4 2.6 2.6L12 5.4"/></svg>}</span><span className="ws-stop-text"><strong>{stop.name}</strong><small>{stateWords[states[index]]}</small></span></Link>
    </li>)}
   </ol>
  </div>
 </div>;
}

function RoadmapTimeline({ planner, today }: { planner: NonNullable<Workspace['planner']>; today: string }) {
 const plan = planner.active!, target = planner.config.target_date ?? planner.runway.resolved.target_date;
 const sessions = useMemo(() => homeSessions(planner), [planner]);
 const line = useMemo(() => timeline(plan.milestones, sessions, today, target), [plan, sessions, today, target]);
 const weeks = planner.runway.calendar?.weeks;
 const week = planWeek(planner.active?.first_planning_week ?? planner.runway.resolved.start_date, today, weeks);
 const end = target ?? line.rows[line.rows.length - 1]?.end ?? today;
 const cls = (index: number) => index === 0 ? 's1' : index === 1 ? 's2' : 's3';
 return <div className="ws-hero-path">
  <div className="ws-tl-top"><span><b>Today</b> {longDay(today)}</span>{week && weeks ? <span>Week {week} of {weeks}</span> : <span/>}<span><b>Target</b> {formatDayMonthYear(end)}</span></div>
  {line.rows.length > 0 ? <>
   <div className="ws-tl-bar" role="img" aria-label={`Timeline of ${plural(line.rows.length, 'milestone')}${line.buffer ? ` and a ${plural(line.buffer, 'day')} buffer before the target` : ''}`}>
    {line.rows.map((row, index) => <i key={row.id} className={cls(index)} style={{ flex: row.days }}/>)}
    {line.buffer > 0 && <i className="sb" style={{ flex: line.buffer }}/>}
   </div>
   <div className="ws-tl-months" aria-hidden="true">{monthTicks(today, end).map((name, index) => <span key={index}>{name}</span>)}</div>
   <div className="ws-tl-cards">{line.rows.map((row, index) => <div key={row.id} className={`ws-tl-card${row.id === line.current ? ' now' : ''}`}>
    <div className="ws-tl-head"><span className={`num${index === 1 ? ' n2' : index > 1 ? ' n3' : ''}`}>{index + 1}</span><span className="meta">{row.started && row.total ? `${row.done} of ${plural(row.total, 'session')}` : row.started ? hours(row.minutes) : row.startsIn > 0 ? `Starts in ${plural(row.startsIn, 'day')}` : hours(row.minutes)}</span></div>
    <b>{row.title}</b><span className="dates">{shortDate(row.start)} – {shortDate(row.end)}</span>
    <div className="ws-cps" role={row.checkpoints.length ? 'img' : undefined} aria-label={row.checkpoints.length ? `${row.checkpoints.filter(Boolean).length} of ${row.checkpoints.length} checkpoints reached` : undefined}>{row.checkpoints.map((on, dot) => <i key={dot} className={`ws-cp${on ? ' on' : ''}`}/>)}</div>
   </div>)}</div>
   <p className="ws-tl-note">Dots are checkpoints.{line.buffer > 0 ? ` The dashed segment is a ${plural(line.buffer, 'day')} buffer.` : ''}</p>
  </> : <p className="ws-sub" style={{ color: '#94a3b8' }}>Your roadmap has no milestones yet.</p>}
 </div>;
}

/** Marks the next session done through the same Roadmap command the Roadmap page uses. */
function NextStep({ step, session, after, workspace, reload, show }: { step: Step | null; session: HomeSession | null; after: HomeSession | null; workspace: Workspace | null; reload: () => void; show: (message: string) => void }) {
 const { token } = useProfile();
 const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
 const command = useRef<{ task: string; id: string } | null>(null);
 useEffect(() => { setOpen(false); setError(''); }, [session?.id]);
 async function done() {
  if (!token || !session?.taskId || !workspace || busy) return;
  const taskId = session.taskId;
  if (command.current?.task !== taskId) command.current = { task: taskId, id: crypto.randomUUID() };
  setBusy(true); setError('');
  try {
   await roadmapApi<Workspace>('/planner/tasks/status', token, { expected_version: workspace.version, mutation_id: command.current.id, task_id: taskId, status: 'completed' });
   command.current = null; show('Marked as done'); announceInputsChanged(); reload();
  } catch (cause) {
   setError(errorText(cause, 'This could not be saved. Try again.'));
   if (cause && typeof cause === 'object' && 'status' in cause && cause.status === 409) { command.current = null; reload(); }
  } finally { setBusy(false); }
 }
 if (session) {
  const when = `${shortDate(session.date)}${session.startTime ? `, ${session.startTime}` : ''}`;
  const details = [session.instructions && session.instructions !== session.title ? session.instructions : '', session.criterion ? `Done when: ${session.criterion}` : ''].filter(Boolean).join('\n\n');
  return <div className="ws-hero-next"><div className="ws-next">
   <div className="ws-next-top"><span>Your next step</span><span className="when">{when}</span></div>
   <h2>{session.title}</h2>
   <div className="ws-chips"><span className="ws-chip sm">{session.minutes} min</span>{session.skills.slice(0, 2).map(name => <span key={name} className="ws-chip sm skill">{name}</span>)}</div>
   {open && details && <p className="ws-next-details" id="next-details">{details}</p>}
   <div className="ws-actions">
    <button type="button" className="ws-btn primary" disabled={busy || !session.taskId} onClick={() => void done()}>{busy ? 'Saving…' : 'Mark as done'}</button>
    {details && <button type="button" className="ws-btn ghost" aria-expanded={open} aria-controls="next-details" onClick={() => setOpen(value => !value)}>{open ? 'Hide details' : 'See details'}</button>}
    <Link className="ws-btn ghost" href="/roadmap">Open roadmap</Link>
   </div>
   {error && <p className="ws-next-error" role="alert">{error}</p>}
  </div><p className="ws-after">{after ? <>After this: <b>{after.title}</b>, {shortDate(after.date)}{after.startTime ? `, ${after.startTime}` : ''}</> : 'This is the last planned task.'}</p></div>;
 }
 if (!step) return <div className="ws-hero-next"><div className="ws-next"><div className="ws-next-top"><span>All caught up</span></div><h2>You’ve finished the planned tasks</h2><div className="ws-actions"><Link className="ws-btn primary" href="/roadmap">Plan next steps</Link></div></div></div>;
 return <div className="ws-hero-next"><div className="ws-next">
  <div className="ws-next-top"><span>{step.label}</span><span className="when">{step.when}</span></div>
  <h2>{step.title}</h2>
  {step.chips.length > 0 && <div className="ws-chips">{step.chips.map(chip => <span key={chip} className="ws-chip sm">{chip}</span>)}</div>}
  <div className="ws-actions"><Link className="ws-btn primary" href={step.href}>{step.go}</Link></div>
 </div><p className="ws-after">{step.after}</p></div>;
}

/* ---------- Cards ---------- */
const matchWords = { supported: 'Have', covered: 'Have', partial: 'Partial', confirmed_shortfall: 'Gap', uncertain: 'Unknown' } as const;
const matchPill = { supported: 'have', covered: 'have', partial: 'part', confirmed_shortfall: 'gap', uncertain: 'unk' } as const;
const isEssential = (priority?: string) => priority === 'required' || priority === 'preferred';
const importanceLabel = (priority?: string) => isEssential(priority) ? 'Essential' : 'Nice to have';
const priorityRank = (priority?: string) => isEssential(priority) ? 0 : 1;
const Pencil = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/></svg>;

/** Goal match reads the same saved comparison as Career Goal; nothing is recomputed here. */
function GoalMatch({ section, skills, retry, comparison }: { section: Section<CurrentGoal>; skills: Section<SkillsSummary>; retry: () => void; comparison: ReturnType<typeof useComparison> }) {
 const goal = section.status === 'ready' ? section.data.goal : null;
 const matches = comparison.matches;
 const counts = { have: 0, partial: 0, gap: 0, unknown: 0 };
 if (goal && matches) for (const skill of goal.skills) { const m = skill.item_id ? matches[skill.item_id] : undefined; if (m === 'supported' || m === 'covered') counts.have++; else if (m === 'partial') counts.partial++; else if (m === 'confirmed_shortfall') counts.gap++; else counts.unknown++; }
 const gaps = goal && matches ? goal.skills.filter(skill => skill.item_id && ['confirmed_shortfall', 'partial'].includes(matches[skill.item_id] ?? ''))
  .sort((a, b) => Number(matches[a.item_id!] === 'partial') - Number(matches[b.item_id!] === 'partial') || priorityRank(a.priority) - priorityRank(b.priority)).slice(0, 3) : [];
 const total = goal?.skills.length ?? 0;
 const label = goal ? [goal.role, goal.company].filter(Boolean).join(' at ') : '';
 const colors = { have: 'var(--ws-mint-ink)', partial: 'var(--ws-partial)', gap: '#F59E0B', unknown: 'var(--ws-unknown)' } as const;
 return <article className="ws-card" aria-labelledby="home-match-title">
  <div className="ws-k"><span id="home-match-title">Goal match</span>{goal && <Link href="/career-goal">See all goal skills</Link>}</div>
  {section.status === 'loading' && <CardSkeleton label="Loading your career goal…"/>}
  {section.status === 'error' && <Unavailable message={section.message} retry={retry} label="career goal"/>}
  {section.status === 'ready' && !goal && <>
   <h3>Pick a role to aim for</h3>
   <p className="ws-sub">Bring a job description, or explore careers to find one. You’ll see the skills it needs and how yours compare.</p>
   <div className="ws-actions" style={{ marginTop: 'auto' }}><Link className="ws-mini solid" href="/career-goal">Set Career Goal</Link><Link className="ws-mini" href="/career-goal/discovery">Explore careers</Link></div>
  </>}
  {goal && <>
   <Link className="ws-goalbtn" href="/career-goal" aria-label={`${label}. Change or edit your career goal`}>{label}<Pencil/></Link>
   {matches ? <>
    <div className="ws-big" style={{ marginTop: 6 }}>{counts.have}<small>of {plural(total, 'goal skill')} you already have</small></div>
    {total > 0 && <div className="ws-bar" role="img" aria-label={`Have ${counts.have}, partial ${counts.partial}, gap ${counts.gap}, unknown ${counts.unknown}`} style={{ marginTop: 10 }}>{(['have', 'partial', 'gap', 'unknown'] as const).map(key => counts[key] ? <i key={key} style={{ flex: counts[key], background: colors[key] }}/> : null)}</div>}
    <div className="ws-keys">{(['have', 'partial', 'gap', 'unknown'] as const).map(key => <span key={key}><i className="ws-dot" style={{ background: colors[key] }} aria-hidden="true"/>{key[0].toUpperCase() + key.slice(1)} {counts[key]}</span>)}</div>
    {gaps.length > 0 && <>
     <div className="ws-divider"/>
     <h3 style={{ fontSize: 15 }}>Top {gaps.length === 1 ? 'skill' : `${gaps.length}`} to strengthen</h3>
     <div className="ws-gaps-head"><span className="n"/><span className="gname">Skill</span>
      <span className="ws-colh c-imp" tabIndex={0} aria-describedby="def-imp">Importance to the role<span className="ws-q" aria-hidden="true">?</span><span className="ws-tip" role="tooltip" id="def-imp"><b>Essential:</b> listed as required or preferred in the job description, or mentioned often across sources.<br/><b>Nice to have:</b> mentioned once or inferred by elo.</span></span>
      <span className="ws-colh c-lvl" tabIndex={0} aria-describedby="def-lvl">Your level<span className="ws-q" aria-hidden="true">?</span><span className="ws-tip" role="tooltip" id="def-lvl"><b>Have:</b> your CV and answers show you’ve used it at the level the role needs.<br/><b>Partial:</b> some evidence, but not yet at that level.<br/><b>Gap:</b> no evidence yet.<br/><b>Unknown:</b> not enough detail to judge.</span></span>
     </div>
     <ol className="ws-gaps">{gaps.map((skill, index) => { const m = matches[skill.item_id!] as keyof typeof matchWords; return <li key={skill.item_id}><span className="n">{index + 1}</span><span className="gname">{skill.name}</span><span className="c-imp"><span className={`ws-pill ${isEssential(skill.priority) ? 'ess' : 'imp'}`}>{importanceLabel(skill.priority)}</span></span><span className="c-lvl"><span className={`ws-pill ${matchPill[m]}`}>{matchWords[m]}</span></span></li>; })}</ol>
    </>}
    {comparison.result && !['available', 'no_findings'].includes(comparison.result.research_coverage) && <p className="ws-sub">Partial comparison: interview research is {comparison.result.research_coverage}.</p>}
   </> : <>
    <div className="ws-big" style={{ marginTop: 6 }}>{total}<small>{total === 1 ? 'skill' : 'skills'} this role needs</small></div>
    <p className="ws-sub">{comparison.error ? comparison.error : 'Your skills haven’t been compared with this role yet.'}</p>
    <div className="ws-actions"><Link className="ws-mini solid" href="/career-goal">{comparison.current ? 'Compare my skills' : 'Open Career Goal'}</Link></div>
   </>}
   <div className="ws-footrow">
    <span className="ws-sub">{skills.status === 'ready' && skills.data.total ? <>Based on <b>{plural(skills.data.total, 'skill')}</b> in your profile, from {plural(skills.data.experiences, 'experience')}</> : skills.status === 'loading' ? 'Reading your skills…' : 'Add a CV to see how your skills compare.'}</span>
    <Link className="ws-link" href="/cv">{skills.status === 'ready' && skills.data.total ? 'View Skills Profile' : 'Build Skills Profile'}</Link>
   </div>
  </>}
 </article>;
}

function RoadmapCard({ section, retry, sessions }: { section: Section<Workspace>; retry: () => void; sessions: HomeSession[] }) {
 const planner = section.status === 'ready' ? section.data.planner : null;
 const plan = planner?.active ?? null;
 const target = planner?.config.target_date ?? planner?.runway.resolved.target_date ?? null;
 const today = planner?.runway.resolved.today;
 const days = target && today ? Math.max(0, daysBetween(today, target)) : null;
 const weeks = planner?.runway.calendar?.weeks ?? null;
 const start = plan?.first_planning_week ?? planner?.runway.resolved.start_date ?? null;
 const week = start && today ? planWeek(start, today, weeks) : null;
 const strip = today ? weekDays(sessions, today) : [];
 const inWeek = strip.length ? sessions.filter(item => item.date >= strip[0].date && item.date <= strip[6].date) : [];
 const upcoming = today ? sessions.filter(item => !item.done && item.date >= today).sort((a, b) => a.date.localeCompare(b.date))[0] : null;
 const checkpoint = plan && today ? nextCheckpoint(plan.milestones, sessions, today) : null;
 return <article className="ws-card" aria-labelledby="home-roadmap-title">
  <div className="ws-k"><span id="home-roadmap-title">Roadmap</span><Link href="/roadmap">Open roadmap</Link></div>
  {section.status === 'loading' && <CardSkeleton label="Loading your roadmap…"/>}
  {section.status === 'error' && <Unavailable message={section.message} retry={retry} label="roadmap"/>}
  {planner && <>
   {days !== null && target ? <div className="ws-big">{days}<small>{days === 1 ? 'day' : 'days'} to {formatDayMonthYear(target)}</small></div>
    : <><h3>Plan your roadmap</h3><p className="ws-sub">Choose a target date and the hours you can give each week.</p><div className="ws-actions"><Link className="ws-mini solid" href="/roadmap">{planner.candidate ? 'Review your draft roadmap' : 'Plan your roadmap'}</Link></div></>}
   {week && weeks ? <><div className="ws-track thin" role="progressbar" aria-label="Weeks into your roadmap" aria-valuemin={0} aria-valuemax={weeks} aria-valuenow={week}><i style={{ width: `${week / weeks * 100}%` }}/></div><span className="ws-sub">Week {week} of {weeks}</span></> : null}
   {plan && today && <>
    <div className="ws-divider"/>
    <div className="ws-k">This week <span className="ws-sub">{shortDate(strip[0].date)} to {shortDate(strip[6].date)}</span></div>
    <div className="ws-week" role="img" aria-label={inWeek.length ? `${inWeek.filter(item => item.done).length} of ${plural(inWeek.length, 'session')} done this week` : 'No sessions this week'}>{strip.map(day => <span key={day.date} className={`ws-day${day.today ? ' today' : ''}${day.state === 'planned' ? ' has' : day.state === 'done' ? ' done' : ''}`}><b>{day.letter}</b><i/></span>)}</div>
    <span className="ws-sub">{inWeek.length ? `${inWeek.filter(item => item.done).length} of ${plural(inWeek.length, 'session')} done this week.` : <>No sessions this week.{upcoming ? ` Your next session is ${shortDate(upcoming.date)}.` : ''}</>} <Link className="ws-inline" href="/roadmap">Add a task</Link></span>
    {checkpoint && <div className="ws-checkpoint">
     <div className="ws-k" style={{ color: 'var(--ws-mint-ink)' }}>Next checkpoint <span className={`ws-pill soon`}>{checkpoint.days <= 0 ? 'Due' : `In ${plural(checkpoint.days, 'day')}`}</span></div>
     <h3>{checkpoint.title}</h3>
     <span className="ws-sub">{shortDate(checkpoint.date)}, {checkpoint.milestone.title}</span>
     {checkpoint.total > 0 && <><div className="ws-track" role="progressbar" aria-label="Milestone progress" aria-valuemin={0} aria-valuemax={checkpoint.total} aria-valuenow={checkpoint.done}><i style={{ width: `${checkpoint.done / checkpoint.total * 100}%` }}/></div><span className="ws-sub">{checkpoint.done} of {plural(checkpoint.total, 'session')} done</span></>}
    </div>}
   </>}
  </>}
 </article>;
}

function ProgressCard({ section, sessions, matchHave, total }: { section: Section<Workspace>; sessions: HomeSession[]; matchHave: number | null; total: number }) {
 const planner = section.status === 'ready' ? section.data.planner : null;
 const today = planner?.runway.resolved.today;
 const progress = today ? weeksOnTrack(sessions, today, planner?.active?.first_planning_week ?? planner?.runway.resolved.start_date ?? null) : null;
 const wins = planner?.active && today ? recentWins(sessions, planner.active.milestones, 3).map(win => win.text) : [];
 if (matchHave) wins.push(`You already have ${matchHave} of the ${total} skills your goal needs`);
 const shown = wins.slice(0, 3);
 return <article className="ws-card" aria-labelledby="home-progress-title">
  <div className="ws-k"><span id="home-progress-title">Your progress</span>{progress && <span className="ws-pill ok">Week {progress.week}</span>}</div>
  {section.status === 'loading' && <CardSkeleton label="Loading your progress…"/>}
  {section.status === 'error' && <p className="ws-sub">Your progress appears once your roadmap loads.</p>}
  {progress && <div className="ws-progress-top">
   <div className="ws-streak" aria-live="polite"><span className="ws-big">{progress.count}</span><span className="ws-sub">{progress.count === 1 ? 'week on track' : 'weeks on track'}</span></div>
   <div className="ws-weeks" aria-hidden="true">{progress.dots.map((dot, index) => <i key={index} className={dot.on ? 'on' : dot.now ? 'now' : ''}/>)}</div>
  </div>}
  {section.status !== 'loading' && <>
   <h3 style={{ fontSize: 15, marginTop: 6 }}>Recent wins</h3>
   <ul className="ws-wins">{!shown.length && <li className="empty"><span className="ic">+</span>Your first win is one task away.</li>}{shown.map(win => <li key={win}><span className="ic">✓</span>{win}</li>)}</ul>
  </>}
 </article>;
}

type Upcoming = { date: string; title: string; detail: string };
function ComingUp({ applications, goal, today, retry }: { applications: Section<Application[]>; goal: Section<CurrentGoal>; today: string; retry: () => void }) {
 const items: Upcoming[] = [];
 if (applications.status === 'ready') for (const item of applications.data) {
  const job = `${item.snapshot.title} · ${item.snapshot.company}`;
  if (item.deadline && item.deadline >= today && item.status === 'saved') items.push({ date: item.deadline, title: 'Application deadline', detail: job });
  if (item.follow_up_at && item.follow_up_at >= today) items.push({ date: item.follow_up_at.slice(0, 10), title: 'Follow up', detail: job });
 }
 const saved = goal.status === 'ready' ? goal.data.goal : null;
 for (const date of saved?.job_dates ?? []) if (date.kind === 'application_deadline' && date.date && date.date >= today && !items.some(item => item.date === date.date)) items.push({ date: date.date, title: 'Application deadline', detail: [saved?.role, saved?.company].filter(Boolean).join(' · ') });
 items.sort((a, b) => a.date.localeCompare(b.date));
 const days = (date: string) => daysBetween(today, date);
 return <article className="ws-card" aria-labelledby="home-upcoming-title">
  <div className="ws-k"><span id="home-upcoming-title">Coming up</span><Link href="/jobs#saved-jobs">Saved jobs</Link></div>
  {applications.status === 'loading' ? <CardSkeleton label="Loading your applications…"/> : applications.status === 'error' ? <Unavailable message={applications.message} retry={retry} label="applications"/> : items.length ? <ul className="ws-upcoming">{items.slice(0, 4).map(item => { const d = new Date(`${item.date}T12:00:00Z`); return <li key={item.date + item.title + item.detail}>
   <span className="ws-date" aria-hidden="true"><small>{d.toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' })}</small><b>{d.getUTCDate()}</b></span>
   <span><strong>{item.title}</strong><span className="ws-sub">{item.detail}{days(item.date) <= 14 ? ` · ${days(item.date) === 0 ? 'today' : `in ${plural(days(item.date), 'day')}`}` : ''}</span><span className="visually-hidden">{formatDate(item.date)}</span></span>
  </li>; })}</ul> : <>
   <h3>Nothing coming up</h3>
   <span className="ws-sub">No deadlines or follow-ups yet. Save a job to track its dates here.</span>
   <Link className="ws-apply" href="/jobs">Search jobs</Link>
  </>}
 </article>;
}

/* ---------- Daily tip and practice question ---------- */
type Daily = { text: string; source: string; cta: string; href: string; external: boolean };
const tipCategories = ['internship_insights', 'company_intelligence', 'career_progression', 'conversion_outcomes'] as const;
const dayIndex = (today: string) => Math.floor(Date.parse(`${today}T00:00:00Z`) / 86400000);
const usable = (finding: IntelligenceFinding) => finding.value.trim().length > 20 && finding.value.length < 400 && finding.confidence !== 'insufficient_evidence';

/** One cited tip and one interview question from the saved research on the goal. Reading never starts research. */
function DailyCard({ goal, today }: { goal: Section<CurrentGoal>; today: string }) {
 const { token } = useProfile();
 const goalId = goal.status === 'ready' ? goal.data.goal?._id : undefined, role = goal.status === 'ready' ? goal.data.goal?.role : undefined;
 const [view, setView] = useState<OpportunityView | null>(null), [kind, setKind] = useState<'tip' | 'pq'>('tip');
 useEffect(() => {
  if (!token || !goalId) { setView(null); return; }
  const abort = new AbortController();
  careerApi<OpportunityView>(`/goals/${goalId}/opportunity-research`, token, { signal: abort.signal }).then(value => { if (!abort.signal.aborted) setView(value); }).catch(() => { if (!abort.signal.aborted) setView(null); });
  return () => abort.abort();
 }, [token, goalId]);
 const items = useMemo(() => {
  if (!view) return { tip: null as Daily | null, pq: null as Daily | null };
  const sources = view.sources ?? [];
  const pick = <T,>(list: T[]) => list.length ? list[dayIndex(today) % list.length] : null;
  const tipFinding = pick(tipCategories.flatMap(category => view.categories[category]?.findings ?? []).filter(finding => usable(finding) && finding.source_ids.some(id => { const source = sources.find(item => item.source_id === id); return source && sourceLink(source.url); })));
  const link = tipFinding ? sources.filter(item => tipFinding.source_ids.includes(item.source_id)).map(item => sourceLink(item.url)).find(Boolean) : null;
  const question = pick((view.categories.interview_intelligence?.findings ?? []).filter(finding => finding.field === 'interview_questions' && usable(finding)));
  return {
   tip: tipFinding && link ? { text: tipFinding.value, source: `Found by elo on ${link.domain}. Check the source.`, cta: 'See source', href: link.url, external: true } : null,
   pq: question ? { text: question.value, source: role ? `For your ${role} goal` : 'For your career goal', cta: 'Practise this question', href: '/career-goal/interview', external: false } : null,
  };
 }, [view, today, role]);
 const shown = items[kind] ? kind : items.tip ? 'tip' : 'pq', item = items[shown];
 if (!item) return null;
 return <section className="ws-practice" aria-label="Daily">
  <div className="ws-miniseg" role="tablist" aria-label="Daily item">
   <button type="button" role="tab" aria-selected={shown === 'tip'} disabled={!items.tip} onClick={() => setKind('tip')}>Tip of the day</button>
   <button type="button" role="tab" aria-selected={shown === 'pq'} disabled={!items.pq} onClick={() => setKind('pq')}>Practice question</button>
  </div>
  <div className="ws-pq-body" role="tabpanel" aria-live="polite"><span className="ws-pq-text">{item.text}</span><span className="ws-pq-src">{item.source}</span></div>
  {item.external ? <a className="ws-apply" href={item.href} target="_blank" rel="noopener noreferrer">{item.cta}</a> : <Link className="ws-apply" href={item.href}>{item.cta}</Link>}
 </section>;
}

/* ---------- Page ---------- */
export function HomeDashboard() {
 const { profile, loading, account, token, configError, loadError } = useProfile();
 const comparison = useComparison(token);
 const goal = useSection(loadGoal, token), skills = useSection(loadSkills, token), roadmap = useSection(loadRoadmap, token), applications = useSection(loadApplications, token);
 const [toast, show] = useToast();
 const flags: Flag[] = [
  loading ? 'loading' : configError || loadError ? 'error' : Boolean(profile?.occupational_status),
  flag(goal.state, data => Boolean(data.goal)),
  flag(skills.state, data => data.total > 0),
  flag(roadmap.state, data => Boolean(data.planner.active)),
 ];
 const states = journeyStates(flags);
 const settled = !flags.includes('loading');
 const workspace = roadmap.state.status === 'ready' ? roadmap.state.data : null;
 const planner = workspace?.planner ?? null;
 const today = planner?.runway.resolved.today ?? new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
 const sessions = useMemo(() => homeSessions(planner), [planner]);
 const { next, after } = useMemo(() => nextTasks(sessions), [sessions]);
 const allSet = states.every(state => state === 'done');
 const reload = useCallback(() => { roadmap.retry(); }, [roadmap]);
 const reviewNeeded = skills.state.status === 'ready' && skills.state.data.reviewNeeded;

 // While set-up is unfinished the hero names the one step still open; afterwards it shows the next planned session.
 const open = states.indexOf('next');
 const step: Step | null = (() => {
  const base = { label: 'Finish setting up', when: `Step ${open + 1} of ${stops.length}`, chips: [] as string[], after: 'Once your roadmap is accepted, your daily tasks will appear here.' };
  if (open === 0) return { ...base, title: 'Tell elo about your background', go: 'Add your background', href: '/profile' };
  if (open === 1) return { ...base, title: 'Choose the role you are aiming for', go: 'Set Career Goal', href: '/career-goal' };
  if (open === 2) return { ...base, title: reviewNeeded ? 'Finish your CV review so elo understands what you did' : 'Add your CV so elo can see your skills', go: reviewNeeded ? 'Continue CV review' : 'Build Skills Profile', href: '/cv' };
  if (open === 3) return !comparison.current ? null : !comparison.result
   ? { ...base, title: 'Compare your skills with your career goal', go: 'Compare my skills', href: '/career-goal' }
   : { ...base, title: planner?.candidate ? 'Review and accept your roadmap' : 'Turn your gaps into a study plan', go: planner?.candidate ? 'Review roadmap' : 'Generate roadmap', href: '/roadmap', chips: goal.state.status === 'ready' && goal.state.data.goal ? [[goal.state.data.goal.role, goal.state.data.goal.company].filter(Boolean).join(', ')] : [] };
  return null;
 })();
 const firstName = account?.name?.trim().split(/\s+/)[0];
 const have = comparison.matches && goal.state.status === 'ready' && goal.state.data.goal ? goal.state.data.goal.skills.filter(skill => skill.item_id && ['supported', 'covered'].includes(comparison.matches![skill.item_id] ?? '')).length : null;
 const totalGoalSkills = goal.state.status === 'ready' ? goal.state.data.goal?.skills.length ?? 0 : 0;
 return <section className="page on ws-page ws-home">
  {toast}
  <section className="ws-hero" aria-labelledby="home-hi">
   <div className="ws-hero-head"><div className="ws-eyebrow">{longDay(today)}</div><h1 id="home-hi">Welcome back{firstName ? `, ${firstName}` : ''}.</h1></div>
   {settled && (allSet && planner?.active ? <RoadmapTimeline planner={planner} today={today}/> : <SetupPath states={states}/>)}
   {settled && !flags.includes('error') && (allSet || step) && <NextStep step={allSet ? null : step} session={allSet ? next : null} after={allSet ? after : null} workspace={workspace} reload={reload} show={show}/>}
   {!settled && <p role="status" className="ws-hero-next ws-sub" style={{ color: '#94a3b8' }}>Checking your progress…</p>}
   {settled && flags.includes('error') && <div className="ws-hero-next ws-sub" style={{ color: '#fcd34d' }} role="alert">Some of your information could not be loaded. Retry it in the cards below.</div>}
  </section>
  <AccountPanel/>
  <section className="ws-grid2" aria-label="Your progress">
   <GoalMatch section={goal.state} skills={skills.state} retry={goal.retry} comparison={comparison}/>
   <RoadmapCard section={roadmap.state} retry={roadmap.retry} sessions={sessions}/>
  </section>
  <section className="ws-grid2 even" aria-label="Momentum">
   <ProgressCard section={roadmap.state} sessions={sessions} matchHave={have} total={totalGoalSkills}/>
   <ComingUp applications={applications.state} goal={goal.state} today={today} retry={applications.retry}/>
  </section>
  <DailyCard goal={goal.state} today={today}/>
 </section>;
}

"use client";
import { useComparison, ComparisonPanel } from '@/features/assessment/comparison';
import Link from 'next/link';
import { AccountPanel } from '@/features/profile/account-panel';
import { useProfile } from '@/features/profile/profile-provider';
import type { Workspace } from '@/features/roadmap/types';
import type { CurrentGoal } from '@/lib/api/career';
import type { Application } from '@/lib/api/jobs';
import { loadApplications, loadGoal, loadRoadmap, loadSkills, useSection, type Section, type SkillsSummary } from '@/lib/api/workspace-summary';
import '@/styles/home.css';
import { formatDate } from '@/lib/format';
import { CardSkeleton } from '@/components/ui/workspace-ui';

type Flag = boolean | 'loading' | 'error';
export type StopState = 'done' | 'next' | 'later' | 'checking' | 'unavailable';
const flag = <T,>(section: Section<T>, test: (data: T) => boolean): Flag => section.status === 'ready' ? test(section.data) : section.status;

const stops = [
 { name: 'Background', href: '/profile', action: 'Add your background', x: 7, y: 86 },
 { name: 'Career goal', href: '/career-goal', action: 'Choose your career goal', x: 24, y: 66 },
 { name: 'Skills profile', href: '/cv', action: 'Build your skills profile', x: 41, y: 47 },
 { name: 'Roadmap', href: '/roadmap', action: 'Plan your roadmap', x: 58, y: 29 },
 { name: 'Applications', href: '/jobs', action: 'Find jobs to apply for', x: 75, y: 11 },
];
const stateWords: Record<StopState, string> = { done: 'Done', next: 'Up next', later: 'Later', checking: 'Checking', unavailable: 'Not available' };

/** The first unfinished stop is only named once every stop is known, so the path never points at the wrong one. */
export function journeyStates(flags: Flag[]): StopState[] {
 const settled = flags.every(value => value !== 'loading');
 const next = settled ? flags.indexOf(false) : -1;
 return flags.map((value, index) => value === true ? 'done' : value === 'loading' ? 'checking' : value === 'error' ? 'unavailable' : index === next ? 'next' : settled ? 'later' : 'checking');
}

const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

function Check() { return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m4 8.4 2.6 2.6L12 5.4"/></svg>; }

function Unavailable({ section, retry, label }: { section: { message: string }; retry: () => void; label: string }) {
 return <div className="home-unavailable" role="alert"><p>{section.message}</p><button type="button" className="btn ghost sm" onClick={retry}>Retry {label}</button></div>;
}

function Journey({ states }: { states: StopState[] }) {
 return <div className="home-journey">
  <svg className="home-journey-line" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
   {stops.slice(1).map((stop, index) => { const from = stops[index], walked = states[index] === 'done' && (states[index + 1] === 'done' || states[index + 1] === 'next');
    return <line key={stop.name} className={walked ? 'is-walked' : ''} x1={from.x} y1={from.y} x2={stop.x} y2={stop.y} vectorEffect="non-scaling-stroke"/>; })}
  </svg>
  <ol aria-label="Your path">
   {stops.map((stop, index) => <li key={stop.name} className={`home-stop is-${states[index]}`} style={{ left: `${stop.x}%`, top: `${stop.y}%` }}>
    <Link href={stop.href} aria-current={states[index] === 'next' ? 'step' : undefined}><span className="home-stop-node">{states[index] === 'done' && <Check/>}</span><span className="home-stop-text"><strong>{stop.name}</strong><small>{stateWords[states[index]]}</small></span></Link>
   </li>)}
  </ol>
 </div>;
}

const matchLabels = { supported: 'Have', covered: 'Have', partial: 'Partial', confirmed_shortfall: 'Gap', uncertain: 'Unknown' } as const;
const importanceLabel = (priority?: string) => priority === 'required' ? 'Essential' : priority === 'preferred' ? 'Important' : 'Nice to have';
const priorityRank = (priority?: string) => priority === 'required' ? 0 : priority === 'preferred' ? 1 : 2;

/** Goal match reads the same saved comparison as Career Goal; nothing is recomputed here. */
function GoalMatch({ section, retry, comparison }: { section: Section<CurrentGoal>; retry: () => void; comparison: ReturnType<typeof useComparison> }) {
 const goal = section.status === 'ready' ? section.data.goal : null;
 const matches = comparison.matches, result = comparison.result;
 const counts = { have: 0, partial: 0, gap: 0, unknown: 0 };
 const statusOf = (ref: string) => matches?.[ref];
 if (goal && matches) for (const skill of goal.skills) { const m = skill.item_id ? statusOf(skill.item_id) : undefined; if (m === 'supported' || m === 'covered') counts.have++; else if (m === 'partial') counts.partial++; else if (m === 'confirmed_shortfall') counts.gap++; else counts.unknown++; }
 const gaps = goal && result ? goal.skills.filter(skill => skill.item_id && ['confirmed_shortfall', 'partial'].includes(statusOf(skill.item_id) ?? ''))
  .sort((a, b) => Number(statusOf(a.item_id!) === 'partial') - Number(statusOf(b.item_id!) === 'partial') || priorityRank(a.priority) - priorityRank(b.priority)).slice(0, 3) : [];
 const total = goal?.skills.length ?? 0;
 return <section className="home-card home-match" aria-labelledby="home-match-title">
  {section.status === 'loading' && <><h2 id="home-match-title" className="home-eyebrow">Goal match</h2><CardSkeleton label="Loading your career goal…"/></>}
  {section.status === 'error' && <><h2 id="home-match-title" className="home-eyebrow">Goal match</h2><Unavailable section={section} retry={retry} label="career goal"/></>}
  {section.status === 'ready' && !goal && <div className="home-empty"><h2 id="home-match-title" className="home-eyebrow">Goal match</h2><p className="home-goal-role">Pick a role to aim for</p><p className="home-muted">Bring a job description, or explore careers to find one. You&rsquo;ll see the skills it needs and how yours compare.</p><div className="home-actions"><Link className="btn pri" href="/career-goal">Choose your career goal</Link><Link className="btn ghost" href="/career-goal/discovery">Explore careers</Link></div></div>}
  {goal && <>
   <header><div><p className="home-eyebrow">Goal match · {[goal.role, goal.company].filter(Boolean).join(', ')}</p>
    <h2 id="home-match-title">{result ? <><span className="home-big">{counts.have}</span> of {plural(total, 'skill')} you already have</> : <>{plural(total, 'skill')} this role needs</>}</h2></div>
    <Link className="home-link" href="/career-goal">See all goal skills</Link></header>
   {result && !['available', 'no_findings'].includes(result.research_coverage) && <p className="home-muted">Partial comparison: interview research is {result.research_coverage}.</p>}
   {result && total > 0 && <>
    <div className="home-match-bar" role="img" aria-label={`Have ${counts.have}, partial ${counts.partial}, gap ${counts.gap}, unknown ${counts.unknown}`}>{(['have', 'partial', 'gap', 'unknown'] as const).map(key => counts[key] ? <span key={key} className={`is-${key}`} style={{ flex: counts[key] }}/> : null)}</div>
    <ul className="home-match-legend">{(['have', 'partial', 'gap', 'unknown'] as const).map(key => <li key={key}><i className={`is-${key}`} aria-hidden="true"/>{key[0].toUpperCase() + key.slice(1)} {counts[key]}</li>)}</ul>
    {gaps.length > 0 && <><hr/><p className="home-eyebrow">Top {gaps.length === 1 ? 'gap' : `${gaps.length} gaps`}</p>
     <ol className="home-gaps">{gaps.map((skill, index) => <li key={skill.item_id}><span className="home-gap-rank">{index + 1}</span><span className="home-gap-name">{skill.name}{skill.learning_items?.length ? <span className="home-muted"> — {skill.learning_items.slice(0, 2).map(item => item.name).join(', ')}</span> : null}</span><span className={`home-chip importance-${skill.priority}`}>{importanceLabel(skill.priority)}</span><span className={`home-chip match-${statusOf(skill.item_id!)}`}>{matchLabels[statusOf(skill.item_id!) as keyof typeof matchLabels]}</span></li>)}</ol>
     <Link className="home-link" href="/roadmap">Close these gaps in your roadmap</Link></>}
   </>}
   {!result && <ComparisonPanel comparison={comparison} className="home-match-compare"/>}
  </>}
 </section>;
}

const weekStart = (date: string) => { const d = new Date(`${date}T12:00:00Z`); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); };
const addDays = (date: string, days: number) => { const d = new Date(`${date}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
const endTime = (start: string, minutes: number) => { const [h, m] = start.split(':').map(Number); const t = h * 60 + m + minutes; return `${String(Math.floor(t / 60) % 24).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };
const weekday = (date: string) => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' });

function RoadmapCard({ section, retry }: { section: Section<Workspace>; retry: () => void }) {
 const planner = section.status === 'ready' ? section.data.planner : null;
 const active = planner?.active ?? null;
 const target = planner?.runway.resolved.target_date ?? null;
 const today = planner?.runway.resolved.today;
 const days = target && today ? Math.max(0, Math.ceil((Date.parse(target) - Date.parse(today)) / 86400000)) : null;
 const start = active?.first_planning_week ?? planner?.runway.resolved.start_date ?? null;
 const weeks = planner?.runway.calendar?.weeks ?? null;
 const week = start && today && weeks ? Math.min(weeks, Math.max(1, Math.floor((Date.parse(today) - Date.parse(weekStart(start))) / 604800000) + 1)) : null;
 const next = active?.assignments.find(item => item.id === planner?.active_review?.next_assignment_id);
 return <section className="home-card home-roadmap" aria-labelledby="home-roadmap-title">
  <p className="home-eyebrow">Roadmap</p>
  {section.status === 'loading' && <CardSkeleton label="Loading your roadmap…"/>}
  {section.status === 'error' && <Unavailable section={section} retry={retry} label="roadmap"/>}
  {planner && <>
   {days !== null && target ? <h2 id="home-roadmap-title"><span className="home-big home-block">{plural(days, 'day')}</span> until your target date</h2> : <h2 id="home-roadmap-title">Choose a target date and the hours you can give each week.</h2>}
   {target && <p className="home-muted">{formatDate(target)}{week && weeks ? ` · Week ${week} of ${weeks}` : ''}</p>}
   {week && weeks ? <div className="home-progress" role="progressbar" aria-label="Weeks into your roadmap" aria-valuemin={0} aria-valuemax={weeks} aria-valuenow={week}><i style={{ width: `${week / weeks * 100}%` }}/></div> : null}
   {next ? <div className="home-today"><p className="home-eyebrow">{next.date === today ? 'Today' : formatDate(next.date)}, {next.start_time}–{endTime(next.start_time, next.duration_minutes)}</p><p><strong>{next.task}</strong></p><Link className="home-link" href="/roadmap">{next.date === today ? 'Open today’s session' : 'Open your roadmap'}</Link></div>
    : <Link className="home-link" href="/roadmap">{active ? 'Open your roadmap' : planner.candidate ? 'Review your draft roadmap' : 'Plan your roadmap'}</Link>}
  </>}
 </section>;
}

function ThisWeek({ section }: { section: Section<Workspace> }) {
 const planner = section.status === 'ready' ? section.data.planner : null;
 const today = planner?.runway.resolved.today;
 const items = planner?.active && today ? planner.active.assignments.filter(item => item.date >= weekStart(today) && item.date < addDays(weekStart(today), 7)).sort((a, b) => (a.date + a.start_time).localeCompare(b.date + b.start_time)) : [];
 if (section.status !== 'ready' || !planner?.active) return null;
 return <section className="home-card home-week" aria-labelledby="home-week-title">
  <header><h2 id="home-week-title">This week</h2>{items.length > 0 && <span className="home-muted">{items.filter(item => item.status === 'completed').length} of {items.length} done</span>}</header>
  {items.length ? <ul>{items.slice(0, 6).map(item => <li key={item.id} className={item.status === 'completed' ? 'is-done' : ''}><span className="home-tick" aria-hidden="true">{item.status === 'completed' && <Check/>}</span><span>{item.task} <span className="home-muted">· {weekday(item.date)}</span></span><span className="cv-visually-hidden">{item.status === 'completed' ? 'Done' : 'Not done'}</span></li>)}</ul> : <p className="home-muted">No sessions this week.</p>}
 </section>;
}

type Upcoming = { date: string; title: string; detail: string };
function ComingUp({ applications, goal, today }: { applications: Section<Application[]>; goal: Section<CurrentGoal>; today: string }) {
 const items: Upcoming[] = [];
 if (applications.status === 'ready') for (const item of applications.data) {
  const job = `${item.snapshot.title} · ${item.snapshot.company}`;
  if (item.deadline && item.deadline >= today && ['saved'].includes(item.status)) items.push({ date: item.deadline, title: 'Application deadline', detail: job });
  if (item.follow_up_at && item.follow_up_at >= today) items.push({ date: item.follow_up_at.slice(0, 10), title: 'Follow up', detail: job });
 }
 const saved = goal.status === 'ready' ? goal.data.goal : null;
 for (const date of saved?.job_dates ?? []) if (date.kind === 'application_deadline' && date.date && date.date >= today && !items.some(item => item.date === date.date)) items.push({ date: date.date, title: 'Application deadline', detail: [saved?.role, saved?.company].filter(Boolean).join(' · ') });
 items.sort((a, b) => a.date.localeCompare(b.date));
 const days = (date: string) => Math.round((Date.parse(date) - Date.parse(today)) / 86400000);
 return <section className="home-card home-upcoming" aria-labelledby="home-upcoming-title">
  <h2 id="home-upcoming-title">Coming up</h2>
  {applications.status === 'loading' ? <CardSkeleton label="Loading your applications…"/> : items.length ? <ul>{items.slice(0, 4).map(item => { const d = new Date(`${item.date}T12:00:00Z`); return <li key={item.date + item.title + item.detail}><span className="home-date" aria-hidden="true"><small>{d.toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' })}</small><b>{d.getUTCDate()}</b></span><span><strong>{item.title}</strong><span className="home-muted">{item.detail}{days(item.date) <= 14 ? ` · ${days(item.date) === 0 ? 'today' : `in ${plural(days(item.date), 'day')}`}` : ''}</span><span className="cv-visually-hidden">{formatDate(item.date)}</span></span></li>; })}</ul> : <p className="home-muted">No deadlines or follow-ups coming up. Add dates to saved jobs in My applications.</p>}
  <Link className="home-link" href="/jobs#saved-jobs">Saved jobs</Link>
 </section>;
}

function SkillsCard({ section, retry }: { section: Section<SkillsSummary>; retry: () => void }) {
 return <section className="home-card home-skills-count" aria-labelledby="home-skills-title">
  <h2 id="home-skills-title">Skills Profile</h2>
  {section.status === 'loading' && <CardSkeleton label="Loading your skills…"/>}
  {section.status === 'error' && <Unavailable section={section} retry={retry} label="skills"/>}
  {section.status === 'ready' && (section.data.total ? <><p className="home-stat-big">{plural(section.data.total, 'skill')}</p><p className="home-muted">from {plural(section.data.experiences, 'experience')} · {plural(section.data.groups.length, 'category', 'categories')}</p></> : <p className="home-muted">Upload your CV or add skills to build your profile.</p>)}
  <Link className="home-link" href="/cv">{section.status === 'ready' && section.data.total ? 'View Skills Profile' : 'Build your Skills Profile'}</Link>
 </section>;
}

export function HomeDashboard() {
 const { profile, loading, account, token, configError, loadError } = useProfile();
 const comparison = useComparison(token);
 const goal = useSection(loadGoal, token), skills = useSection(loadSkills, token), roadmap = useSection(loadRoadmap, token), applications = useSection(loadApplications, token);
 const flags: Flag[] = [
  loading ? 'loading' : configError || loadError ? 'error' : Boolean(profile?.occupational_status),
  flag(goal.state, data => Boolean(data.goal)),
  flag(skills.state, data => data.total > 0),
  flag(roadmap.state, data => Boolean(data.planner.active)),
  flag(applications.state, data => data.some(item => item.status !== 'saved')),
 ];
 const states = journeyStates(flags);
 const settled = !flags.includes('loading');
 const nextStop = stops[states.indexOf('next')];
 const doneCount = states.filter(state => state === 'done').length;
 const planner = roadmap.state.status === 'ready' ? roadmap.state.data.planner : null;
 const nextSession = planner?.active?.assignments.find(item => item.id === planner.active_review?.next_assignment_id);
 const today = planner?.runway.resolved.today ?? new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Singapore',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const deadline = goal.state.status === 'ready' ? goal.state.data.goal?.job_dates?.filter(item => item.kind === 'application_deadline' && item.date && item.date >= today).sort((a,b) => a.date!.localeCompare(b.date!))[0] : null;
 const nextAction: { href: string; action: string; why: string } | null = nextStop?.href === '/profile' || nextStop?.href === '/career-goal' || nextStop?.href === '/cv' ? { ...nextStop, why: nextStop.href === '/profile' ? 'Next: tell elo about your background.' : nextStop.href === '/career-goal' ? 'Next: choose the role you are aiming for.' : 'Next: add your CV so elo can see your skills.' }
  : skills.state.status === 'ready' && skills.state.data.reviewNeeded ? { href: '/cv', action: 'Continue CV review', why: 'Next: finish your CV review so elo understands what you did.' }
  : !comparison.current ? null
  : !comparison.result ? { href: '/career-goal', action: 'Compare my skills', why: 'Next: compare your skills with your career goal.' }
  : !planner?.active ? { href: '/roadmap', action: planner?.candidate ? 'Review your draft roadmap' : 'Generate roadmap', why: 'Next: turn your gaps into a study plan.' }
  : nextSession ? { href: '/roadmap', action: nextSession.date === today ? 'Open today’s session' : 'Open your roadmap', why: `Next: ${nextSession.task}${nextSession.date === today ? ' today' : ` on ${formatDate(nextSession.date)}`}.` }
  : deadline ? { href: '/jobs', action: 'Search jobs', why: `Next: your application deadline is ${formatDate(deadline.date!)}.` } : nextStop ? { ...nextStop, why: 'Next: keep going on your path.' } : null;
 const firstName = account?.name?.trim().split(/\s+/)[0];
 return <section className="page on home-board">
  <div className="home-welcome">
   <div className="home-welcome-copy">
    <p className="home-welcome-lede">{formatDate(today)}</p>
    <h1>Welcome back{firstName ? `, ${firstName}` : ''}.</h1>
    <div className="home-next-step">
     <p className="home-next-label">Your next step</p>
     <p className="home-next-why">{settled && nextAction ? nextAction.why : 'A clearer path to your next role.'}</p>
     {settled && !flags.includes('error') && <ol className="home-step-bar" aria-hidden="true">{states.map((state, index) => <li key={stops[index].name} className={state === 'done' ? 'is-done' : ''}/>)}</ol>}
     <div className="home-welcome-actions" aria-live="polite">
      {settled && nextAction && <Link className="btn home-mint" href={nextAction.href}>{nextAction.action}</Link>}
      {settled && !flags.includes('error') && <span>{doneCount} of {stops.length} steps done</span>}
     </div>
    </div>
   </div>
   <Journey states={states}/>
  </div>
  <AccountPanel/>
  <div className="home-grid home-grid-top">
   <GoalMatch section={goal.state} retry={goal.retry} comparison={comparison}/>
   <RoadmapCard section={roadmap.state} retry={roadmap.retry}/>
  </div>
  <div className="home-grid home-grid-bottom">
   <ThisWeek section={roadmap.state}/>
   <ComingUp applications={applications.state} goal={goal.state} today={today}/>
   <SkillsCard section={skills.state} retry={skills.retry}/>
  </div>
 </section>;
}

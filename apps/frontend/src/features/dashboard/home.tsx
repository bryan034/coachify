"use client";
import Link from 'next/link';
import { Icon } from '@/components/ui/icon';
import { AccountPanel } from '@/features/profile/account-panel';
import { useProfile } from '@/features/profile/profile-provider';
import { statuses, studyYearLabel } from '@/features/profile/types';
import { shortDate } from '@/features/roadmap/roadmap-calendar';
import type { LearningPlan, Workspace } from '@/features/roadmap/types';
import type { CurrentGoal } from '@/lib/api/career';
import type { Application } from '@/lib/api/jobs';
import { loadApplications, loadGoal, loadLearning, loadRoadmap, loadSkills, useSection, type Section } from '@/lib/api/workspace-summary';
import { groupSkills } from '@/lib/skill-groups';
import '@/styles/home.css';

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

const longDate = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-SG', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const hours = (minutes: number) => { const value = minutes / 60; return Number.isInteger(value) ? String(value) : value.toFixed(1); };
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

function GoalCard({ section, retry }: { section: Section<CurrentGoal>; retry: () => void }) {
 const goal = section.status === 'ready' ? section.data.goal : null;
 const groups = goal ? groupSkills(goal.skills, skill => skill.name, section.status === 'ready' ? section.data.skill_groups : {}) : [];
 const type = goal?.employment_type && goal.employment_type !== 'unknown' ? goal.employment_type.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase()) : null;
 return <section className="home-card home-goal" aria-labelledby="home-goal-title">
  <header><h2 id="home-goal-title">Career goal</h2>{goal && <Link className="home-link" href="/career-goal">See what the role needs</Link>}</header>
  {section.status === 'loading' && <p role="status" className="home-muted">Loading your career goal…</p>}
  {section.status === 'error' && <Unavailable section={section} retry={retry} label="career goal"/>}
  {section.status === 'ready' && (goal ? <>
   <p className="home-goal-role">{goal.role}</p>
   <p className="home-muted">{[type, goal.target_type === 'career_exploration' ? 'Career exploration' : 'Specific job', goal.company].filter(Boolean).join(' · ')}</p>
   <div className="home-goal-skills">
    <p>{plural(goal.skills.length, 'skill')} this role needs</p>
    {groups.length > 0 && <ul>{groups.map(group => <li key={group.name}>{group.name}<b>{group.items.length}</b></li>)}</ul>}
   </div>
  </> : <div className="home-empty">
   <p className="home-goal-role">Pick a role to aim for</p>
   <p className="home-muted">Bring a job description, or explore careers to find one. You&rsquo;ll see the skills it needs, by category.</p>
   <div className="home-actions"><Link className="btn pri" href="/career-goal">Choose your career goal</Link><Link className="btn ghost" href="/career-goal/discovery">Explore careers</Link></div>
  </div>)}
 </section>;
}

/** Column chart: one measure, drawn from a zero baseline and labelled directly. The largest category takes the accent. */
function SkillsCard({ section, retry }: { section: Section<{ total: number; groups: { name: string; count: number }[] }>; retry: () => void }) {
 const columns = section.status === 'ready' ? (section.data.groups.length > 6
  ? [...section.data.groups.slice(0, 5), { name: `${section.data.groups.length - 5} more categories`, count: section.data.groups.slice(5).reduce((sum, group) => sum + group.count, 0) }]
  : section.data.groups) : [];
 const tallest = Math.max(1, ...columns.map(column => column.count));
 return <section className="home-card home-skills" aria-labelledby="home-skills-title">
  <header><h2 id="home-skills-title">Skills profile</h2>{section.status === 'ready' && section.data.total > 0 && <Link className="home-link" href="/cv">Review skills</Link>}</header>
  {section.status === 'loading' && <p role="status" className="home-muted">Loading your skills…</p>}
  {section.status === 'error' && <Unavailable section={section} retry={retry} label="skills"/>}
  {section.status === 'ready' && (section.data.total ? <>
   <p className="home-stat"><strong>{section.data.total}</strong> {section.data.total === 1 ? 'skill' : 'skills'} in {plural(section.data.groups.length, 'category', 'categories')}</p>
   <ul className="home-columns" aria-label="Skills per category">{columns.map(column => <li key={column.name} title={`${column.name}: ${plural(column.count, 'skill')}`}>
    <span className="home-column-count">{column.count}</span>
    <span className="home-column-track"><i className={column.count === tallest ? 'is-largest' : ''} style={{ height: `${column.count / tallest * 100}%` }}/></span>
    <span className="home-column-name">{column.name}</span>
   </li>)}</ul>
  </> : <div className="home-empty">
   <p className="home-muted">Add your CV or talk it through. Your skills and the experience behind them will appear here.</p>
   <div className="home-actions"><Link className="btn pri" href="/cv">Build your skills profile</Link></div>
  </div>)}
 </section>;
}

function RoadmapCard({ section, retry }: { section: Section<Workspace>; retry: () => void }) {
 const planner = section.status === 'ready' ? section.data.planner : null;
 const active = planner?.active ?? null;
 const target = planner?.runway.resolved.target_date ?? null;
 const days = target ? planner?.runway.calendar?.days ?? null : null;
 const done = active?.assignments.filter(item => item.status === 'completed').length ?? 0;
 const total = active?.assignments.length ?? 0;
 const next = active?.assignments.find(item => item.id === planner?.active_review?.next_assignment_id);
 const weekly = planner?.config.weekly_minutes;
 const session = planner?.config.preferred_session_minutes;
 return <section className="home-card home-roadmap" aria-labelledby="home-roadmap-title">
  <header><h2 id="home-roadmap-title">Roadmap</h2></header>
  {section.status === 'loading' && <p role="status" className="home-muted">Loading your roadmap…</p>}
  {section.status === 'error' && <Unavailable section={section} retry={retry} label="roadmap"/>}
  {planner && <>
   {days !== null && target ? <p className="home-stat"><strong>{days}</strong> {days === 1 ? 'day' : 'days'} to {longDate(target)}</p> : <p className="home-roadmap-empty">Choose a target date and the hours you can give each week.</p>}
   {total > 0 && <div className="home-progress"><div role="progressbar" aria-label="Sessions done" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}><i style={{ width: `${done / total * 100}%` }}/></div><p>{done} of {plural(total, 'session')} done</p></div>}
   {next && <p className="home-next-session">Next: {next.task}</p>}
   {weekly && <ul className="home-roadmap-facts"><li>{hours(weekly)} hrs a week</li>{session && <li>{session % 60 === 0 ? `${session / 60}-hr` : `${session}-min`} sessions</li>}</ul>}
   <Link className="btn home-mint" href="/roadmap">{active ? 'Open your roadmap' : planner.candidate ? 'Review your draft roadmap' : planner.runway.can_generate ? 'Generate roadmap' : 'Set up your roadmap'}</Link>
  </>}
 </section>;
}

const learningWords: Record<LearningPlan['steps'][number]['state'], string> = { not_scheduled: 'Not in this plan yet', not_started: 'Not started', in_progress: 'In progress', done: 'Done' };
const SHOWN_STEPS = 4;

/** Each skill the roadmap works on, most important first. Progress means sessions done, not a tested level. */
function LearningSteps({ plan }: { plan: LearningPlan }) {
 const hidden = plan.steps.length - SHOWN_STEPS;
 return <section className="home-learning" id="home-learning" aria-labelledby="home-learning-title">
  <header><h2 id="home-learning-title">Learning &amp; skills</h2><span>{plan.skills_started} of {plural(plan.skills_total, 'skill')} started</span><Link className="home-link" href="/roadmap">Open your roadmap</Link></header>
  <ol>{plan.steps.slice(0, SHOWN_STEPS).map(step => <li key={step.gap_id}>
   <div className="home-learning-name"><strong>{step.name}</strong><em className={`is-${step.state}`}>{learningWords[step.state]}</em></div>
   {step.sessions_total > 0 && <div className="home-learning-bar" role="progressbar" aria-label={`${step.name} sessions done`} aria-valuemin={0} aria-valuemax={step.sessions_total} aria-valuenow={step.sessions_completed}><i style={{ width: `${step.sessions_completed / step.sessions_total * 100}%` }}/></div>}
   {step.sessions_total > 0 && <p>{step.sessions_completed} of {plural(step.sessions_total, 'session')} done{step.sessions_missed ? `, ${step.sessions_missed} missed` : ''}</p>}
   {step.next_session && <p>Next on {shortDate(step.next_session.date)}: {step.next_session.task}</p>}
  </li>)}</ol>
  {hidden > 0 && <p className="home-muted">{hidden} more on your roadmap.</p>}
 </section>;
}

function LearningLine({ section }: { section: Section<LearningPlan> }) {
 if (section.status === 'loading') return <>Checking your learning steps…</>;
 if (section.status === 'error') return <>Your learning steps are not available right now.</>;
 if (!section.data.has_roadmap) return <>Personal steps appear once you have a roadmap.</>;
 return <>{section.data.skills_started} of {plural(section.data.skills_total, 'skill')} started</>;
}

function ApplicationsLine({ section }: { section: Section<Application[]> }) {
 if (section.status === 'loading') return <>Checking your saved jobs…</>;
 if (section.status === 'error') return <>Your saved jobs are not available right now.</>;
 if (!section.data.length) return <>Search Singapore jobs and internships, and track them here.</>;
 const saved = section.data.filter(item => item.status === 'saved').length;
 return <>{section.data.length - saved} applied, {saved} saved</>;
}

export function HomeDashboard() {
 const { profile, loading, account, token, configError, loadError } = useProfile();
 const goal = useSection(loadGoal, token), skills = useSection(loadSkills, token), roadmap = useSection(loadRoadmap, token), applications = useSection(loadApplications, token), learning = useSection(loadLearning, token);
 const hasSteps = learning.state.status === 'ready' && learning.state.data.steps.length > 0;
 const status = statuses.find(s => s.id === profile?.occupational_status)?.label;
 const year = profile?.current_study_year && profile.school_category ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
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
 const firstName = account?.name?.trim().split(/\s+/)[0];
 return <section className="page on home-board">
  <div className="home-welcome">
   <div className="home-welcome-copy">
    <p className="home-welcome-lede">Your next chapter starts here</p>
    <h1>Welcome to elo{firstName ? `, ${firstName}` : ''}.</h1>
    <p>A clearer path to your next role.</p>
    <div className="home-welcome-actions" aria-live="polite">
     {settled && (nextStop ? <Link className="btn home-mint" href={nextStop.href}>{nextStop.action}</Link> : !flags.includes('error') && <Link className="btn home-mint" href="/roadmap">Open your roadmap</Link>)}
     {settled && !flags.includes('error') && <span>{doneCount} of {stops.length} steps done</span>}
    </div>
   </div>
   <Journey states={states}/>
  </div>
  <AccountPanel/>
  <div className="home-grid">
   <section className="home-card home-background" aria-labelledby="home-background-title">
    <header><h2 id="home-background-title">Your background</h2></header>
    <div className="home-background-body" aria-label="Saved background">
     <span className="home-background-icon"><Icon name="user"/></span>
     <h3>{loading ? 'Loading your profile…' : status || 'Make it yours'}</h3>
     {(profile?.education.institution || profile?.education.course || year) ? <>{profile?.education.institution && <p className="institution-name">{profile.education.institution.name}</p>}<p className="home-muted">{[profile?.education.course, year].filter(Boolean).join(' · ') || 'No course added'}</p></> : <p className="home-muted">Your education and current status help establish where you are today.</p>}
     {profile?.education_review_required && <p className="notice">Your education details need a review.</p>}
    </div>
    <Link className="home-link" href={profile?.occupational_status ? '/profile/edit' : '/profile'}>{profile?.occupational_status ? 'Edit profile' : 'Add your background'}</Link>
   </section>
   <GoalCard section={goal.state} retry={goal.retry}/>
   <SkillsCard section={skills.state} retry={skills.retry}/>
   <RoadmapCard section={roadmap.state} retry={roadmap.retry}/>
  </div>
  {learning.state.status === 'ready' && hasSteps && <LearningSteps plan={learning.state.data}/>}
  <section className="home-next" aria-labelledby="home-next-title">
   <h2 id="home-next-title">Up next</h2>
   <ul>
    <li><Link href="/jobs"><span className="home-next-icon is-live"><Icon name="search"/></span><span><strong>Job applications</strong><small><ApplicationsLine section={applications.state}/></small></span></Link></li>
    <li><Link href={hasSteps ? '#home-learning' : '/roadmap'}><span className="home-next-icon is-live"><Icon name="book"/></span><span><strong>Learning &amp; skills</strong><small><LearningLine section={learning.state}/></small></span></Link></li>
    <li><Link href="/career-goal/discovery"><span className="home-next-icon is-live"><Icon name="brief"/></span><span><strong>Explore careers</strong><small>Find roles worth aiming for.</small></span></Link></li>
    <li><Link href="/calendar"><span className="home-next-icon"><Icon name="cal"/></span><span><strong>Events</strong><small>Internships, projects and events.</small></span><em>Soon</em></Link></li>
    <li><Link href="/chats"><span className="home-next-icon"><Icon name="chat"/></span><span><strong>Expert conversations</strong><small>Coffee chats with people in the role.</small></span><em>Soon</em></Link></li>
   </ul>
  </section>
 </section>;
}

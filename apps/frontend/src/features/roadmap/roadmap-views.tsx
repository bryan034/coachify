"use client";
import { useEffect, useMemo, useState } from 'react';
import { MonthView, TodayView, WeekView } from './calendar-views';
import { useNowMinute, useTaskEditor, type RoadmapActions, type ViewContext, type ViewName } from './day-list';
import { MilestonesView, ProgressView } from './progress-views';
import { fullDate } from './roadmap-calendar';
import { currentMilestone, daysBetween, planSessions } from './roadmap-day';
import type { SkillOption } from './task-form';
import type { PlanReview, PlannedRoadmap, Planner } from './types';
import '@/styles/roadmap-views.css';

const tabs: [ViewName, string][] = [['day', 'Today'], ['week', 'Week'], ['month', 'Month'], ['milestones', 'Milestones'], ['progress', 'Progress']];
const isDay = (value: string | null): value is string => !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T12:00:00Z`));

/** Skills a task can name: this plan's gaps first, then the whole Skills Profile. The service checks the same lists. */
export function skillCatalog(plan: PlannedRoadmap, planner: Planner): SkillOption[] {
 const seen = new Set<string>(); const options: SkillOption[] = [];
 const add = (name: string | null | undefined, group: string) => { const key = name?.trim().toLowerCase(); if (key && !seen.has(key)) { seen.add(key); options.push({ name: name!.trim(), group }); } };
 [...plan.gaps].sort((a, b) => a.priority - b.priority).forEach(gap => add(gap.name, 'In this plan'));
 plan.assessment.skill_profile?.skills.forEach(skill => add(skill.name, 'Skills Profile'));
 planner.inputs.skills.forEach(skill => add(skill.name, 'Skills Profile'));
 return options;
}
/** The view and date live in the address, e.g. /roadmap?view=day&date=2026-11-26, so a day can be linked and reloaded. */
function readAddress(today: string): { view: ViewName; date: string } {
 if (typeof window === 'undefined') return { view: 'day', date: today };
 const params = new URLSearchParams(window.location.search); const view = params.get('view'); const date = params.get('date');
 return { view: tabs.some(([name]) => name === view) ? view as ViewName : 'day', date: isDay(date) ? date : today };
}

/** The active roadmap: one header, five views. Plan settings is the only way out to the planning page. */
export function RoadmapViews({ plan, review, planner, goal, version, frozen, updates, openSettings, actions }: {
 plan: PlannedRoadmap; review: PlanReview; planner: Planner; goal: string; version: number; frozen: boolean; updates: number; openSettings: () => void; actions: RoadmapActions;
}) {
 const today = review.remaining.resolved.today;
 const [place, setPlace] = useState(() => readAddress(today));
 const nowMinute = useNowMinute(plan.config.time_zone);
 const sessions = useMemo(() => planSessions(planner, plan, false, today), [planner, plan, today]);
 const catalog = useMemo(() => skillCatalog(plan, planner), [plan, planner]);
 const go = (view: ViewName, date?: string) => {
  const next = { view, date: date ?? (view === 'day' ? today : place.date) };
  setPlace(next);
  const params = new URLSearchParams(window.location.search); params.set('view', next.view);
  if (next.view === 'day' || next.view === 'week' || next.view === 'month') params.set('date', next.date); else params.delete('date');
  window.history.replaceState(window.history.state, '', `${window.location.pathname}?${params}`);
 };
 const context: ViewContext = { plan, review, sessions, today, nowMinute, version, catalog, frozen, actions, go };
 const editor = useTaskEditor(context);
 // Moving to another view or day through the tabs follows the same unsaved-changes rule as closing the panel.
 const leave = (view: ViewName, date?: string) => editor.leave(() => { editor.cancelNew(); go(view, date); });
 useEffect(() => { const back = () => setPlace(readAddress(today)); window.addEventListener('popstate', back); return () => window.removeEventListener('popstate', back); }, [today]);
 const target = plan.config.target_date; const left = target ? daysBetween(today, target) : null;
 const { list, index } = currentMilestone(plan);
 return <div className="rv">
  <header className="rv-head">
   <div><h1>Roadmap</h1>
    <p className="rv-meta"><span className="rv-tag sk goal">{goal}</span>{target && left !== null && left >= 0 && <span><strong>{left === 0 ? 'Today' : `${left} ${left === 1 ? 'day' : 'days'}`}</strong>{left === 0 ? ' is your target date' : ` to ${fullDate(target)}`}</span>}{list.length > 0 && <span>Milestone {index + 1} of {list.length}</span>}</p>
   </div>
   <button type="button" className="rv-btn" onClick={() => editor.leave(openSettings)} aria-label={updates ? `Plan settings, ${updates} ${updates === 1 ? 'update' : 'updates'}` : undefined}>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></svg>Plan settings{updates > 0 && <span className="rv-badge" aria-hidden="true">{updates}</span>}
   </button>
  </header>
  <nav className="rv-tabs" aria-label="Roadmap views">{tabs.map(([name, label]) => <button key={name} type="button" className="rv-tab" aria-current={place.view === name ? 'page' : undefined} onClick={() => leave(name, name === 'day' ? today : name === 'week' || name === 'month' ? (place.view === 'day' || place.view === 'week' || place.view === 'month' ? place.date : today) : undefined)}>{label}</button>)}</nav>
  {place.view === 'day' && <TodayView context={context} day={place.date} editor={editor} />}
  {place.view === 'week' && <WeekView context={context} day={place.date} editor={editor} />}
  {place.view === 'month' && <MonthView context={context} day={place.date} />}
  {place.view === 'milestones' && <MilestonesView context={context} planner={planner} />}
  {place.view === 'progress' && <ProgressView context={context} />}
  {editor.dialog}
 </div>;
}

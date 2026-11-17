import type { Planner, PlanMilestone } from '@/features/roadmap/types';

/** Pure reads of the saved roadmap for Home. Nothing here is stored or invented; every figure comes from the plan. */
export type HomeSession = {
 id: string; taskId: string | null; title: string; instructions: string; criterion: string; date: string; startTime: string | null;
 minutes: number; done: boolean; completedAt: string | null; milestoneKey: string | null; skills: string[];
};

const noon = (date: string) => new Date(`${date}T12:00:00Z`);
export const addDays = (date: string, days: number) => { const d = noon(date); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
export const daysBetween = (from: string, to: string) => Math.round((noon(to).getTime() - noon(from).getTime()) / 86400000);
/** The Monday of the week a date falls in. */
export const weekStart = (date: string) => addDays(date, -((noon(date).getUTCDay() + 6) % 7));
/** Which week of the roadmap today falls in (1-based, capped at the roadmap's length), or null when its length is unknown. */
export const planWeek = (start: string, today: string, weeks: number | null | undefined) => weeks ? Math.min(weeks, Math.max(1, Math.floor(daysBetween(weekStart(start), weekStart(today)) / 7) + 1)) : null;
export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
/** "24 Nov". */
export const shortDate = (date: string) => noon(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
/** "15 November". */
export const longDay = (date: string) => noon(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' });
export const monthName = (date: string) => noon(date).toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' });
export const hours = (minutes: number) => `${Math.round(minutes / 60)}h`;

/** Every session of the active roadmap in one shape, from the task view when the service sent it. */
export function homeSessions(planner: Planner | null): HomeSession[] {
 if (!planner?.active) return [];
 if (planner.active_sessions) return planner.active_sessions.map(item => ({ id: item.id, taskId: item.task_id, title: item.title, instructions: item.instructions, criterion: item.completion_criterion, date: item.date, startTime: item.start_time, minutes: item.duration_minutes, done: item.status === 'completed', completedAt: item.completed_at ?? null, milestoneKey: item.milestone_key, skills: item.skills.map(skill => skill.name) }));
 const gapNames = new Map(planner.active.gaps.map(gap => [gap.id, gap.name]));
 return planner.active.assignments.map(item => ({ id: item.id, taskId: item.task_id ?? null, title: item.title || item.task, instructions: item.task, criterion: item.completion_criterion, date: item.date, startTime: item.start_time, minutes: item.duration_minutes, done: item.status === 'completed', completedAt: item.completed_at, milestoneKey: item.milestone_key, skills: (item.gap_ids ?? (item.gap_id ? [item.gap_id] : [])).map(id => gapNames.get(id)).filter((name): name is string => Boolean(name)) }));
}
const order = (a: HomeSession, b: HomeSession) => (a.date + (a.startTime ?? '')).localeCompare(b.date + (b.startTime ?? ''));

/** The earliest session still to do, then the one after it. Missed sessions come first: they are what is overdue. */
export function nextTasks(sessions: HomeSession[]) {
 const todo = sessions.filter(item => !item.done).sort(order);
 return { next: todo[0] ?? null, after: todo[1] ?? null };
}

export type WeekDay = { date: string; letter: string; state: 'none' | 'planned' | 'done'; today: boolean };
/** Monday to Sunday of the week containing today, with what is planned and finished each day. */
export function weekDays(sessions: HomeSession[], today: string): WeekDay[] {
 const start = weekStart(today);
 return Array.from({ length: 7 }, (_, index) => {
  const date = addDays(start, index), day = sessions.filter(item => item.date === date);
  return { date, letter: 'MTWTFSS'[index], today: date === today, state: !day.length ? 'none' : day.every(item => item.done) ? 'done' : 'planned' };
 });
}

/**
 * Weeks on track: consecutive weeks in which every planned session was finished. The current week counts once it is
 * complete; an unfinished current week neither adds to nor breaks the run. Weeks without sessions do not count.
 */
export function weeksOnTrack(sessions: HomeSession[], today: string, planStart: string | null) {
 const first = planStart ? weekStart(planStart) : sessions.length ? weekStart(sessions.map(item => item.date).sort()[0]) : weekStart(today);
 const current = weekStart(today);
 const state = (week: string): 'on' | 'off' | 'none' => {
  const rows = sessions.filter(item => weekStart(item.date) === week);
  return !rows.length ? 'none' : rows.every(item => item.done) ? 'on' : 'off';
 };
 let count = 0, cursor = state(current) === 'on' ? current : addDays(current, -7);
 while (cursor >= first && state(cursor) === 'on') { count++; cursor = addDays(cursor, -7); }
 const total = Math.max(1, Math.round(daysBetween(first, current) / 7) + 1);
 const shown = Math.min(6, total);
 const dots = Array.from({ length: shown }, (_, index) => { const week = addDays(current, -7 * (shown - 1 - index)); return { on: state(week) === 'on', now: week === current }; });
 return { count, week: total, dots };
}

/** The latest things the person finished, newest first. */
export function recentWins(sessions: HomeSession[], milestones: PlanMilestone[], limit = 3) {
 const wins: { at: string; text: string }[] = sessions.filter(item => item.done && item.completedAt).map(item => ({ at: item.completedAt!, text: `Finished “${item.title}”` }));
 for (const milestone of milestones) for (const checkpoint of milestone.checkpoints ?? []) if (checkpoint.reached_at) wins.push({ at: checkpoint.reached_at, text: `Reached “${checkpoint.title}”` });
 return wins.sort((a, b) => b.at.localeCompare(a.at)).slice(0, limit);
}

/** The first checkpoint not yet reached, with the sessions done in its milestone. */
export function nextCheckpoint(milestones: PlanMilestone[], sessions: HomeSession[], today: string) {
 const rows = milestones.flatMap(milestone => (milestone.checkpoints ?? []).filter(checkpoint => !checkpoint.reached_at).map(checkpoint => ({ milestone, checkpoint })))
  .sort((a, b) => a.checkpoint.date.localeCompare(b.checkpoint.date));
 const found = rows.find(row => row.checkpoint.date >= today) ?? rows[0];
 if (!found) return null;
 const members = sessions.filter(item => item.milestoneKey === found.milestone.key);
 return { title: found.checkpoint.title, date: found.checkpoint.date, days: daysBetween(today, found.checkpoint.date), milestone: found.milestone, total: members.length, done: members.filter(item => item.done).length };
}

export type TimelineMilestone = { id: string; title: string; start: string; end: string; days: number; minutes: number; checkpoints: boolean[]; done: number; total: number; started: boolean; startsIn: number };
/** Milestones in order with their span, and the buffer between the last one and the target date. */
export function timeline(milestones: PlanMilestone[], sessions: HomeSession[], today: string, target: string | null) {
 const rows: TimelineMilestone[] = [...milestones].sort((a, b) => a.projected_start.localeCompare(b.projected_start)).map(item => {
  const members = sessions.filter(session => session.milestoneKey === item.key);
  return { id: item.id, title: item.title, start: item.projected_start, end: item.projected_end, days: Math.max(1, daysBetween(item.projected_start, item.projected_end) + 1), minutes: item.estimated_minutes,
   checkpoints: (item.checkpoints ?? []).map(checkpoint => Boolean(checkpoint.reached_at)), done: members.filter(session => session.done).length, total: members.length, started: item.projected_start <= today, startsIn: daysBetween(today, item.projected_start) };
 });
 const lastEnd = rows.length ? rows[rows.length - 1].end : null;
 const buffer = lastEnd && target && target > lastEnd ? daysBetween(lastEnd, target) : 0;
 const current = rows.find(row => row.start <= today && today <= row.end) ?? rows.find(row => row.start > today) ?? rows[rows.length - 1] ?? null;
 return { rows, buffer, current: current?.id ?? null };
}

/** Month labels spread evenly from today to the target date. */
export function monthTicks(from: string, to: string, count = 5) {
 const span = daysBetween(from, to);
 return Array.from({ length: count }, (_, index) => monthName(addDays(from, Math.round(span * index / (count - 1)))));
}

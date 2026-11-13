import { addDays, weekDates, weekStart } from './roadmap-calendar';
import type { PlanMilestone, PlannedRoadmap, Planner, PlannerConfig, Session } from './types';

/** Display arithmetic for the roadmap views. The roadmap service owns the schedule and validates every saved time. */

export const toMinutes = (clock: string) => { const [hour, minute] = clock.split(':').map(Number); return hour * 60 + minute; };
export const toClock = (minutes: number) => { const value = Math.min(Math.max(minutes, 0), 1439); return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`; };
/** "1h 30m", the compact length used on to-do rows and charts. */
export const shortLength = (minutes: number) => { const hours = Math.floor(minutes / 60), rest = Math.round(minutes % 60); return hours && rest ? `${hours}h ${rest}m` : hours ? `${hours}h` : `${rest}m`; };
export const timeRange = (session: Pick<Session, 'start_time' | 'duration_minutes'>) => session.start_time ? `${session.start_time}–${toClock(toMinutes(session.start_time) + session.duration_minutes)}` : 'Anytime';
export const isDone = (session: Session) => session.status === 'completed';
export const weekdayIndex = (day: string) => (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
const sum = (items: Session[]) => items.reduce((total, item) => total + item.duration_minutes, 0);
export const minutesOf = sum;

/** The to-do rows for a plan. Older responses without them are rebuilt from the saved sessions. */
export function planSessions(planner: Planner, plan: PlannedRoadmap, preview: boolean, today: string): Session[] {
 const rows = preview ? planner.candidate_sessions : planner.active_sessions;
 if (rows) return rows;
 return plan.assignments.map(item => {
  const milestone = plan.milestones.find(entry => entry.key === item.milestone_key);
  const fallback = item.gap_id ? [item.gap_id] : milestone?.gap_ids || [];
  const ids = item.gap_ids?.length ? item.gap_ids : item.skill_gap_ids ?? (fallback.length === 1 ? fallback : []);
  const notes = plan.editable_tasks?.find(task => task.id === item.task_id)?.notes ?? null;
  return { id: item.id, task_id: item.task_id || item.id, title: item.title || item.task, instructions: item.task, completion_criterion: item.completion_criterion, date: item.date, start_time: item.start_time, duration_minutes: item.duration_minutes,
   status: item.status, completed_at: item.completed_at, missed: item.status !== 'completed' && item.date < today, origin: 'generated' as const, kind: item.kind, milestone_key: item.milestone_key,
   skills: plan.gaps.filter(gap => ids.includes(gap.id)).map(gap => ({ name: gap.name, gap_id: gap.id })), notes };
 });
}

/** Open tasks by start time with anytime last; ticked tasks move to the bottom. */
export const listOrder = (a: Session, b: Session) => Number(isDone(a)) - Number(isDone(b)) || (a.start_time ?? '99:99').localeCompare(b.start_time ?? '99:99') || a.title.localeCompare(b.title);
export const onDay = (sessions: Session[], day: string) => sessions.filter(item => item.date === day);

/** Busy labels: timed tasks merged when the gap between them is 30 minutes or less. */
export function busyRanges(sessions: Session[]) {
 const timed = sessions.filter(item => item.start_time).map(item => [toMinutes(item.start_time!), toMinutes(item.start_time!) + item.duration_minutes]).sort((a, b) => a[0] - b[0]);
 const merged: number[][] = [];
 for (const [start, end] of timed) { const last = merged[merged.length - 1]; if (last && start - last[1] <= 30) last[1] = Math.max(last[1], end); else merged.push([start, end]); }
 return merged.map(([start, end]) => `${toClock(start)}–${end >= 1440 ? '24:00' : toClock(end)}`);
}

/** The user's study blocks on a weekday, merged, as minute spans. Backup blocks count only when enabled. */
export function studyBlocks(config: PlannerConfig, day: string) {
 const spans = config.blocks.filter(block => block.day === weekdayIndex(day) && (block.kind === 'preferred' || config.use_backup)).map(block => [toMinutes(block.start_time), toMinutes(block.start_time) + block.duration_minutes]).sort((a, b) => a[0] - b[0]);
 const merged: number[][] = [];
 for (const [start, end] of spans) { const last = merged[merged.length - 1]; if (last && start <= last[1]) last[1] = Math.max(last[1], end); else merged.push([start, end]); }
 return merged;
}
export const blockLabel = (blocks: number[][]) => blocks.map(([start, end]) => `${toClock(start)}–${end >= 1440 ? '24:00' : toClock(end)}`).join(', ');

/** The next free start on a day for the task form: inside a study block first, then straight after the last one. */
export function nextFree(config: PlannerConfig, day: string, others: Session[], minutes: number, from = 0) {
 const busy = others.filter(item => item.start_time).map(item => [toMinutes(item.start_time!), toMinutes(item.start_time!) + item.duration_minutes]);
 const free = (start: number) => start + minutes <= 1440 && !busy.some(([low, high]) => start < high && start + minutes > low);
 const blocks = studyBlocks(config, day);
 for (const [low, high] of blocks) for (let start = Math.max(Math.ceil(low / 15) * 15, Math.ceil(from / 15) * 15); start + minutes <= high; start += 15) if (free(start)) return toClock(start);
 const after = blocks.length ? blocks[blocks.length - 1][1] : 19 * 60;
 for (let start = Math.max(Math.ceil(after / 15) * 15, Math.ceil(from / 15) * 15); start + minutes <= 1440; start += 15) if (free(start)) return toClock(start);
 return null;
}
export const clashWith = (others: Session[], start: string | null, minutes: number) => start ? others.find(item => item.start_time && toMinutes(item.start_time) < toMinutes(start) + minutes && toMinutes(item.start_time) + item.duration_minutes > toMinutes(start)) : undefined;

/** Timed tasks on the 24-hour track, stacked into rows when they overlap. */
export function timelineLanes(sessions: Session[]) {
 const timed = sessions.filter(item => item.start_time).map(item => ({ session: item, start: toMinutes(item.start_time!), end: Math.min(toMinutes(item.start_time!) + item.duration_minutes, 1440) })).sort((a, b) => a.start - b.start);
 const ends: number[] = [];
 const items = timed.map(item => { let lane = ends.findIndex(end => end <= item.start); if (lane < 0) { lane = ends.length; ends.push(0); } ends[lane] = item.end; return { ...item, lane }; });
 return { items, lanes: Math.max(ends.length, 1) };
}
/** Dock-style magnification: the hovered hour widens to 2.4×, its neighbours to 1.6× and the next ones to 1.2×. */
export function hourWidths(base: number, hovered: number | null) {
 const widths = Array.from({ length: 24 }, (_, hour) => { if (hovered === null) return base; const distance = Math.abs(hour - hovered); return base * (distance === 0 ? 2.4 : distance === 1 ? 1.6 : distance === 2 ? 1.2 : 1); });
 const edges = [0]; widths.forEach((width, index) => edges.push(edges[index] + width));
 const x = (minute: number) => { const hour = Math.min(Math.floor(minute / 60), 23); return edges[hour] + (minute - hour * 60) / 60 * widths[hour]; };
 return { widths, edges, x, total: edges[24] };
}

/** Where the week stands: tasks done, tasks due by the end of today, and hours against the weekly goal. */
export function weekSummary(sessions: Session[], day: string, today: string, goal: number) {
 const dates = weekDates(day), items = sessions.filter(item => dates.includes(item.date));
 const done = items.filter(isDone), due = items.filter(item => item.date <= today);
 const doneMinutes = sum(done), planned = sum(items);
 const scheduled = Math.min(Math.max(planned, doneMinutes), goal || planned);
 return { dates, items, done: done.length, total: items.length, due: due.length, behind: Math.max(due.length - due.filter(isDone).length, 0), doneMinutes, planned, goal,
  scheduledLeft: Math.max(scheduled - doneMinutes, 0), gap: Math.max(goal - Math.max(planned, doneMinutes), 0), toGo: Math.max(goal - doneMinutes, 0) };
}

export const orderedMilestones = (plan: PlannedRoadmap) => [...plan.milestones].sort((a, b) => a.projected_end.localeCompare(b.projected_end) || a.projected_start.localeCompare(b.projected_start));
/** The milestone being worked on: the first one whose outcome has not been shown. */
export function currentMilestone(plan: PlannedRoadmap) {
 const list = orderedMilestones(plan); const index = list.findIndex(item => !item.outcome.demonstrated);
 return { list, index: index < 0 ? list.length - 1 : index, current: list.length ? list[index < 0 ? list.length - 1 : index] : null, allReached: list.length > 0 && index < 0 };
}
export function nextCheckpoint(plan: PlannedRoadmap) {
 const open = orderedMilestones(plan).flatMap(milestone => (milestone.checkpoints || []).filter(item => !item.reached_at).map(checkpoint => ({ milestone, checkpoint })));
 return open.sort((a, b) => a.checkpoint.date.localeCompare(b.checkpoint.date))[0] || null;
}
export const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86400000);
export const inDays = (today: string, day: string) => { const count = daysBetween(today, day); return count === 0 ? 'Today' : count === 1 ? 'Tomorrow' : count > 1 ? `In ${count} days` : count === -1 ? '1 day ago' : `${-count} days ago`; };
export function milestoneProgress(milestone: PlanMilestone, sessions: Session[], today: string) {
 const members = sessions.filter(item => item.milestone_key === milestone.key), done = members.filter(isDone);
 const doneMinutes = sum(done);
 return { total: members.length, done: done.length, expected: members.filter(item => item.date <= today).length, doneMinutes, totalMinutes: doneMinutes + milestone.estimated_minutes,
  percent: milestone.outcome.demonstrated ? 100 : doneMinutes + milestone.estimated_minutes ? Math.round(doneMinutes / (doneMinutes + milestone.estimated_minutes) * 100) : 0 };
}

/** Sessions done of sessions planned for each skill, most-planned first. */
export function skillCounts(sessions: Session[]) {
 const rows = new Map<string, { name: string; done: number; total: number; minutes: number }>();
 for (const item of sessions) for (const skill of item.skills) {
  const row = rows.get(skill.name) || { name: skill.name, done: 0, total: 0, minutes: 0 };
  row.total += 1; if (isDone(item)) { row.done += 1; row.minutes += item.duration_minutes / item.skills.length; }
  rows.set(skill.name, row);
 }
 return [...rows.values()].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
}

export type Bar = { key: string; label: string; done: number; planned: number; when: 'past' | 'now' | 'ahead' };
/** Chart rows for one week by day or the whole plan by week, counting tasks or minutes. Task bars by day are running totals. */
export function progressBars(sessions: Session[], today: string, measure: 'tasks' | 'hours', group: 'day' | 'week', planStart: string, planEnd: string): Bar[] {
 const value = (items: Session[]) => measure === 'tasks' ? items.length : sum(items);
 if (group === 'day') {
  let done = 0, planned = 0;
  return weekDates(today).map(day => {
   const items = onDay(sessions, day);
   if (measure === 'tasks') { done += items.filter(isDone).length; planned += items.length; return { key: day, label: day, done, planned, when: day < today ? 'past' as const : day === today ? 'now' as const : 'ahead' as const }; }
   return { key: day, label: day, done: value(items.filter(isDone)), planned: value(items), when: day < today ? 'past' as const : day === today ? 'now' as const : 'ahead' as const };
  });
 }
 const bars: Bar[] = []; const current = weekStart(today);
 const first = weekStart(planStart < today ? planStart : today); const last = weekStart(planEnd > today ? planEnd : today);
 // Five weeks around today keep the chart readable on any plan length.
 const from = [first, addDays(current, -14)].sort()[1], to = [last, addDays(from, 28)].sort()[0];
 for (let monday = from; monday <= to; monday = addDays(monday, 7)) {
  const items = sessions.filter(item => item.date >= monday && item.date <= addDays(monday, 6));
  bars.push({ key: monday, label: monday, done: value(items.filter(isDone)), planned: value(items), when: monday < current ? 'past' : monday === current ? 'now' : 'ahead' });
 }
 return bars;
}

/** Consecutive study days with something ticked, ending today or yesterday. Days with nothing planned don't break it. */
export function studyStreak(sessions: Session[], today: string) {
 const first = sessions.map(item => item.date).sort()[0];
 if (!first) return 0;
 let streak = 0;
 for (let day = today; day >= first; day = addDays(day, -1)) {
  const items = onDay(sessions, day);
  if (!items.length) continue;
  if (items.some(isDone)) streak += 1; else if (day !== today) break;
 }
 return streak;
}
/** Average minutes done a week over up to the last three finished weeks of the plan, or this week so far. */
export function recentPace(sessions: Session[], today: string, planStart: string) {
 const current = weekStart(today); const weeks: number[] = [];
 for (let monday = addDays(current, -7); monday >= weekStart(planStart) && weeks.length < 3; monday = addDays(monday, -7)) weeks.push(sum(sessions.filter(item => isDone(item) && item.date >= monday && item.date <= addDays(monday, 6))));
 if (!weeks.length) return { minutes: sum(sessions.filter(item => isDone(item) && item.date >= current && item.date <= today)), weeks: 0 };
 return { minutes: Math.round(weeks.reduce((a, b) => a + b, 0) / weeks.length), weeks: weeks.length };
}

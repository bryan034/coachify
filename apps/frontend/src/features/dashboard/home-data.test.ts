import { describe, expect, it } from 'vitest';
import { daysBetween, homeSessions, monthTicks, nextCheckpoint, nextTasks, recentWins, timeline, weekDays, weekStart, weeksOnTrack, type HomeSession } from './home-data';
import type { Planner, PlanMilestone } from '@/features/roadmap/types';

const session = (id: string, date: string, done = false, extra: Partial<HomeSession> = {}): HomeSession => ({ id, taskId: `t-${id}`, title: `Task ${id}`, instructions: '', criterion: '', date, startTime: '19:00', minutes: 30, done, completedAt: done ? `${date}T20:00:00Z` : null, milestoneKey: 'm1', skills: [], ...extra });
const milestone = (key: string, start: string, end: string, checkpoints: { title: string; date: string; reached?: boolean }[] = []) => ({ id: `id-${key}`, key, title: `Milestone ${key}`, estimated_minutes: 3000, projected_start: start, projected_end: end, checkpoints: checkpoints.map((item, index) => ({ key: `c${index}`, title: item.title, date: item.date, reached_at: item.reached ? `${item.date}T10:00:00Z` : null })) }) as unknown as PlanMilestone;

describe('dates', () => {
 it('finds the Monday of a week and the days between dates', () => {
  expect(weekStart('2026-11-15')).toBe('2026-11-09');
  expect(weekStart('2026-11-09')).toBe('2026-11-09');
  expect(daysBetween('2026-11-15', '2027-10-14')).toBe(333);
 });
 it('spreads month labels from today to the target', () => {
  expect(monthTicks('2026-11-15', '2027-10-14')).toEqual(['Nov', 'Feb', 'May', 'Jul', 'Oct']);
 });
});

describe('next steps and this week', () => {
 it('names the earliest unfinished session, then the one after it, and none when everything is done', () => {
  const all = [session('c', '2026-11-26'), session('a', '2026-11-24', true), session('b', '2026-11-25'), session('late', '2026-11-20')];
  expect(nextTasks(all).next?.id).toBe('late');
  expect(nextTasks(all).after?.id).toBe('b');
  expect(nextTasks([session('a', '2026-11-24', true)])).toEqual({ next: null, after: null });
 });
 it('marks each day of the current week as none, planned or done', () => {
  const days = weekDays([session('a', '2026-11-09', true), session('b', '2026-11-11'), session('c', '2026-11-11', true)], '2026-11-15');
  expect(days.map(day => day.letter).join('')).toBe('MTWTFSS');
  expect(days.map(day => day.state)).toEqual(['done', 'none', 'planned', 'none', 'none', 'none', 'none']);
  expect(days[6]).toMatchObject({ date: '2026-11-15', today: true });
 });
});

describe('weeks on track', () => {
 const start = '2026-10-19';
 it('counts consecutive weeks in which every session was finished', () => {
  const sessions = [session('a', '2026-10-19', true), session('b', '2026-10-26', true), session('c', '2026-11-02', false), session('d', '2026-11-09', true), session('e', '2026-11-10', true)];
  expect(weeksOnTrack(sessions, '2026-11-12', start).count).toBe(1);
  expect(weeksOnTrack(sessions.map(item => item.id === 'c' ? { ...item, done: true } : item), '2026-11-12', start).count).toBe(4);
 });
 it('does not let an unfinished current week break the run, and starts at zero', () => {
  const sessions = [session('a', '2026-11-02', true), session('b', '2026-11-09', false)];
  expect(weeksOnTrack(sessions, '2026-11-10', '2026-11-02').count).toBe(1);
  expect(weeksOnTrack([session('a', '2026-11-24')], '2026-11-15', '2026-11-24').count).toBe(0);
 });
 it('shows at most six weeks, the current one last and marked now', () => {
  const result = weeksOnTrack([session('a', '2026-11-24', true)], '2026-12-30', '2026-11-24');
  expect(result.dots).toHaveLength(6);
  expect(result.dots.at(-1)).toEqual({ on: false, now: true });
 });
});

describe('wins, checkpoints and the timeline', () => {
 it('lists the latest finished sessions and reached checkpoints first', () => {
  const wins = recentWins([session('a', '2026-11-24', true), session('b', '2026-11-25', true), session('c', '2026-11-26')], [milestone('m1', '2026-11-24', '2026-11-29', [{ title: 'Flow recorded', date: '2026-11-26', reached: true }])]);
  expect(wins.map(win => win.text)).toEqual(['Reached “Flow recorded”', 'Finished “Task b”', 'Finished “Task a”']);
 });
 it('finds the next checkpoint not yet reached with its milestone’s progress', () => {
  const plan = [milestone('m1', '2026-11-24', '2026-11-29', [{ title: 'Done one', date: '2026-11-25', reached: true }, { title: 'Flow recorded', date: '2026-11-26' }])];
  const found = nextCheckpoint(plan, [session('a', '2026-11-24', true), session('b', '2026-11-25')], '2026-11-15');
  expect(found).toMatchObject({ title: 'Flow recorded', days: 11, total: 2, done: 1 });
  expect(nextCheckpoint([milestone('m1', '2026-11-24', '2026-11-29')], [], '2026-11-15')).toBeNull();
 });
 it('lays milestones out by length with the buffer before the target date and names the current one', () => {
  const rows = [milestone('m1', '2026-11-24', '2026-11-29'), milestone('m2', '2026-11-30', '2027-05-30')];
  const result = timeline(rows, [session('a', '2026-11-24', true)], '2026-11-15', '2027-06-17');
  expect(result.rows.map(row => row.days)).toEqual([6, 182]);
  expect(result.buffer).toBe(18);
  expect(result.current).toBe('id-m1');
  expect(result.rows[0]).toMatchObject({ started: false, startsIn: 9, done: 1, total: 1 });
 });
 it('reads sessions from the task view, or from assignments when the service sent none', () => {
  const plan = { gaps: [{ id: 'g1', name: 'SQL' }], milestones: [], assignments: [{ id: 'x', task: 'Write joins', title: null, completion_criterion: 'It runs', date: '2026-11-24', start_time: '19:00', duration_minutes: 30, status: 'completed', completed_at: '2026-11-24T20:00:00Z', milestone_key: 'm1', gap_id: 'g1' }] };
  const fromAssignments = homeSessions({ active: plan } as unknown as Planner);
  expect(fromAssignments[0]).toMatchObject({ title: 'Write joins', done: true, skills: ['SQL'] });
  const fromTasks = homeSessions({ active: plan, active_sessions: [{ id: 's', task_id: 't', title: 'Join practice', instructions: 'Do it', completion_criterion: 'Done', date: '2026-11-24', start_time: null, duration_minutes: 20, status: 'scheduled', milestone_key: 'm1', skills: [{ name: 'SQL' }] }] } as unknown as Planner);
  expect(fromTasks[0]).toMatchObject({ id: 's', taskId: 't', done: false, startTime: null, skills: ['SQL'] });
  expect(homeSessions(null)).toEqual([]);
 });
});

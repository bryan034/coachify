import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { ActiveView, PlannedRoadmap, Proposal, Workspace } from './types';
import { activeView, config, legacyRoadmap, planner, review, roadmap, task, workspace } from '../../../tests/fixtures/roadmap-workspace';

const session = vi.hoisted(() => ({ account: { id: 'owner-one' }, token: 'synthetic-token' }));
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => session }));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: api, RoadmapError: class extends Error { constructor(message: string, public status: number, public code: string) { super(message); } } }));
const { RoadmapError } = await import('@/lib/api/roadmap');

const active = (plan: PlannedRoadmap = roadmap(), view: Partial<ActiveView> = {}, extra = {}) => workspace({ planner: planner({ active: plan, active_review: review(plan), active_view: activeView(plan, view), ...extra }) });
function serve(state: Workspace, handlers: Record<string, (body: never) => unknown> = {}) {
 api.mockImplementation(async (path: string, _token: string, body: never) => {
  const route = path.split('?')[0];
  if (handlers[route]) return handlers[route](body);
  return state;
 });
}
const calls = (path: string) => api.mock.calls.filter(call => call[0] === path);
beforeEach(() => { api.mockReset(); });
const name = 'Write one tested Python endpoint.';

it('orders the page from header to secondary details', async () => {
 serve(active()); const { container } = render(<RoadmapPlanner />);
 await screen.findByText('Your active roadmap');
 const order = [...container.querySelectorAll('.active-roadmap > *')].map(node => node.className);
 expect(order).toEqual(['active-header', 'today', 'coach-panel', 'weekly-roadmap', 'backlog-section', 'secondary-details']);
 const header = container.querySelector('.active-header') as HTMLElement;
 for (const text of ['Target date', 'Projected finish', 'Current week', 'Status', 'Roadmap progress', 'Insufficient data']) expect(within(header).getByText(text)).toBeVisible();
 expect(within(header).getByRole('progressbar', { name: 'Roadmap progress' })).toHaveAttribute('aria-valuenow', '0');
});

it('shows the target boundary, outlines for later weeks and task detail for the current week', async () => {
 serve(active()); render(<RoadmapPlanner />);
 const weekly = await screen.findByRole('region', { name: 'Weekly roadmap' });
 expect(within(weekly).getByText('Polish the API')).toBeInTheDocument();
 expect(within(weekly).getByText(/Expected output: A demo/)).toBeInTheDocument();
 expect(within(weekly).getByText(/Target date: Sun, 27 Jan 2030/)).toBeInTheDocument();
 expect(within(weekly).getAllByRole('button', { name: /^Add task to the week of/ })).toHaveLength(3);
 expect(within(weekly).getAllByRole('button', { name: /^Pause the week of/ })).toHaveLength(3);
});

it('moves a task, explains a validation failure and confirms a time outside study blocks', async () => {
 const failing = [new RoadmapError('Another task already occupies that time. Choose another placement.', 409, 'slot_occupied'), new RoadmapError('That time is outside your enabled study blocks. Place it there anyway?', 409, 'outside_study_blocks')];
 const state = active();
 serve(state, { '/planner/tasks/move': (body: { confirm_outside_blocks: boolean }) => { if (!body.confirm_outside_blocks) throw failing.shift(); return state; } });
 render(<RoadmapPlanner />);
 const today = await screen.findByRole('region', { name: 'Today' });
 fireEvent.click(within(today).getByRole('button', { name: `Move ${name}` }));
 const form = within(today).getByRole('form', { name: `Move ${name}` });
 fireEvent.change(within(form).getByLabelText('Date'), { target: { value: '2030-01-14' } });
 fireEvent.click(within(form).getByRole('button', { name: 'Save time' }));
 expect(await within(form).findByRole('alert')).toHaveTextContent('Another task already occupies that time');
 expect(screen.queryByText('Reload saved work')).not.toBeInTheDocument();
 fireEvent.click(within(form).getByRole('button', { name: 'Save time' }));
 await within(form).findByText(/outside your enabled study blocks/);
 fireEvent.click(within(form).getByRole('button', { name: 'Place it there anyway' }));
 await waitFor(() => expect(calls('/planner/tasks/move').at(-1)![2]).toMatchObject({ task_id: 'a1', date: '2030-01-14', start_time: '19:00', confirm_outside_blocks: true }));
});

it('offers skip, pin and an optional note without proof', async () => {
 const state = active();
 serve(state, { '/planner/tasks/skip': () => state, '/planner/tasks/update': () => state }); render(<RoadmapPlanner />);
 const today = await screen.findByRole('region', { name: 'Today' });
 fireEvent.click(within(today).getByRole('button', { name: `Pin ${name}` }));
 await waitFor(() => expect(calls('/planner/tasks/update')[0][2]).toMatchObject({ task_id: 'a1', pinned: true }));
 await waitFor(() => expect(within(today).getByRole('button', { name: `Note on ${name}` })).toBeEnabled());
 fireEvent.click(within(today).getByRole('button', { name: `Note on ${name}` }));
 fireEvent.change(within(today).getByRole('textbox', { name: 'Note (optional)' }), { target: { value: 'Ask a mentor.' } });
 fireEvent.click(within(today).getByRole('button', { name: 'Save note' }));
 await waitFor(() => expect(calls('/planner/tasks/update')[1][2]).toMatchObject({ note: 'Ask a mentor.' }));
 await waitFor(() => expect(within(today).getByRole('button', { name: `Skip ${name}` })).toBeEnabled());
 fireEvent.click(within(today).getByRole('button', { name: `Skip ${name}` }));
 await waitFor(() => expect(calls('/planner/tasks/skip')[0][2]).toMatchObject({ task_id: 'a1' }));
});

it('adds a custom task with no placement to Backlog and shows skipped tasks with a return action', async () => {
 const plan = roadmap({ assignments: [task(), task({ id: 'c1', key: 'c1', origin: 'custom', kind: 'custom', status: 'backlog', date: null, start_time: null, task: 'Mock interview', milestone_key: null, backlog_reason: 'No time chosen yet.', completion_criterion: null }), task({ id: 's1', key: 's1', status: 'skipped', task: 'Skipped work' })] });
 const state = active(plan);
 serve(state, { '/planner/tasks/custom': () => state, '/planner/tasks/restore': () => state }); render(<RoadmapPlanner />);
 const weekly = await screen.findByRole('region', { name: 'Weekly roadmap' });
 fireEvent.click(within(weekly).getByRole('button', { name: 'Add task to the week of Mon, 14 Jan 2030' }));
 const form = within(weekly).getByRole('form', { name: /Add a task to the week of/ });
 fireEvent.change(within(form).getByLabelText('Title'), { target: { value: 'Coffee chat' } });
 fireEvent.click(within(form).getByRole('checkbox', { name: 'Count in scheduled hours' }));
 fireEvent.click(within(form).getByRole('button', { name: 'Add task' }));
 await waitFor(() => expect(calls('/planner/tasks/custom')[0][2]).toMatchObject({ title: 'Coffee chat', week_start: '2030-01-14', date: null, start_time: null, count_hours: false }));
 const backlog = await screen.findByRole('region', { name: 'Backlog' });
 expect(within(backlog).getByText(/No time chosen yet/)).toBeVisible();
 expect(within(backlog).getByRole('button', { name: 'Place Mock interview' })).toBeInTheDocument();
 fireEvent.click(within(backlog).getByRole('button', { name: 'Return Skipped work to Backlog' }));
 await waitFor(() => expect(calls('/planner/tasks/restore')[0][2]).toMatchObject({ task_id: 's1' }));
});

it('separates Backlog from deferred scope, which needs a preview', async () => {
 const state = active();
 serve(state, { '/planner/proposals/scope': () => state }); render(<RoadmapPlanner />);
 const deferred = await screen.findByRole('group', { name: 'Deferred scope' });
 expect(within(deferred).getByText('Advanced Python')).toBeVisible();
 fireEvent.click(within(deferred).getByRole('button', { name: 'Preview bringing Advanced Python into the roadmap' }));
 await waitFor(() => expect(calls('/planner/proposals/scope')[0][2]).toMatchObject({ deferred_id: 'deferred-adv' }));
});

it('shows an automatic move with Undo, and action-needed tasks in the coach panel', async () => {
 const plan = roadmap({ assignments: [task({ date: '2030-01-14', start_time: '20:00', week_start: '2030-01-14', auto_moves: 1 }), task({ id: 'p1', key: 'p1', pinned: true, task: 'Pinned work', action_needed: { reason: 'missed_pinned', message: '“Pinned work” was pinned and missed. Choose what to do.', occurrence: '2030-01-08' } })],
  events: [{ id: 'auto:a1', type: 'auto_move', at: '2030-01-10T00:00:00+00:00', task_id: 'a1', message: 'Moved to Monday 20:00', undo: {}, undone: false }] });
 const state = active(plan);
 serve(state, { '/planner/events/undo': () => { throw new RoadmapError('This task changed after it moved, so the move can’t be undone. Choose a new time for it instead.', 409, 'undo_conflict'); } }); render(<RoadmapPlanner />);
 const coach = await screen.findByRole('region', { name: 'Coach' });
 expect(within(coach).getByText('Moved to Monday 20:00', { exact: false })).toBeVisible();
 expect(within(coach).getByText(/was pinned and missed/)).toBeVisible();
 fireEvent.click(within(coach).getByRole('button', { name: 'Undo: Moved to Monday 20:00' }));
 expect(await within(coach).findByRole('alert')).toHaveTextContent(/can’t be undone.*You can place it with Move/);
 expect(calls('/planner/events/undo')[0][2]).toMatchObject({ event_id: 'auto:a1' });
});

const checkin = { week_start: '2030-01-07', status: 'open' as const, opens_at: '2030-01-11T18:00', expires_at: '2030-01-14T19:00', recap: { planned_minutes: 120, completed_minutes: 30, remaining_minutes: 60, due_minutes: 90, completed_due_minutes: 30, moved: ['Moved to Monday 20:00'], skipped: ['Skipped work'], suggest_less: true }, answers: null, next_week: '2030-01-14', next_week_target_minutes: 240 };

it('walks through the check-in, suggests Less and saves answers before asking for a proposal', async () => {
 const state = active(roadmap(), { checkin }); const order: string[] = [];
 serve(state, { '/planner/checkins/answer': () => { order.push('answer'); return state; }, '/planner/checkins/propose': () => { order.push('propose'); return { version: 1, operation: { id: 'x', status: 'succeeded', stage: 'complete' } }; } });
 render(<RoadmapPlanner />);
 const panel = await screen.findByRole('region', { name: 'Weekly check-in' });
 expect(within(panel).getByText('Planned')).toBeVisible(); expect(within(panel).getByText('Still scheduled')).toBeVisible();
 expect(within(panel).getByText('Moved to Monday 20:00')).toBeVisible(); expect(within(panel).getByText('Skipped work')).toBeVisible();
 const submit = within(panel).getByRole('button', { name: 'Save and prepare a proposal' }); expect(submit).toBeDisabled();
 fireEvent.click(within(panel).getByRole('radio', { name: 'Busier than usual' }));
 fireEvent.click(within(panel).getByRole('radio', { name: 'The same' }));
 expect(within(panel).getByRole('status')).toHaveTextContent('You might choose Less');
 fireEvent.change(within(panel).getByRole('textbox', { name: /Anything to add/ }), { target: { value: 'Exams.' } });
 fireEvent.click(submit);
 await waitFor(() => expect(order).toEqual(['answer', 'propose']));
 expect(calls('/planner/checkins/answer')[0][2]).toMatchObject({ week_start: '2030-01-07', week_feel: 'busier', next_week: 'same', note: 'Exams.' });
});

it('offers retry with saved answers when a proposal could not be prepared', async () => {
 const retry = { expected_version: 1, mutation_id: 'failed', week_start: '2030-01-07' };
 const state = active(roadmap(), { checkin: { ...checkin, status: 'answered', answers: { week_feel: 'freer', next_week: 'less', note: 'Saved.' } } }, { retry_checkin: retry });
 serve(state, { '/planner/checkins/propose': () => ({ version: 2, operation: null }) }); render(<RoadmapPlanner />);
 const panel = await screen.findByRole('region', { name: 'Weekly check-in' });
 expect(within(panel).getByRole('radio', { name: 'Freer' })).toBeChecked();
 expect(within(panel).getByRole('textbox', { name: /Anything to add/ })).toHaveValue('Saved.');
 fireEvent.click(within(panel).getByRole('button', { name: 'Retry proposal' }));
 await waitFor(() => expect(calls('/planner/checkins/propose')[0][2]).toEqual(retry));
});

const proposal = (overrides: Partial<Proposal> = {}): Proposal => ({ id: 'p1', kind: 'pause', base_revision: 0, created_at: '2030-01-09', message: null, week_start: '2030-01-14', effect: { summary: 'Pause the week of 2030-01-14.', finish_before: '2030-02-17', finish_after: '2030-02-24', target_before: '2030-01-27', target_after: '2030-01-27', capacity_before_minutes: 552, capacity_after_minutes: 312, tasks_moved: ['Add validation.'], tasks_backlogged: [], tasks_added: [], tasks_removed: [], decisions: [{ task_id: 'c1', title: 'Mentor call', date: '2030-01-16', start_time: '19:00', origin: 'custom' }, { task_id: 'c2', title: 'Other call', date: '2030-01-17', start_time: '19:00', origin: 'custom' }], warnings: [], week_start: '2030-01-14', workload_before_minutes: null, workload_after_minutes: null, uses_buffer: false, add_block_suggested: false }, ...overrides });

it('previews a pause with the finish effect and asks about pinned and custom tasks', async () => {
 const state = active(roadmap(), {}, { proposal: proposal() });
 serve(state, { '/planner/proposals/accept': () => active() }); render(<RoadmapPlanner />);
 const panel = await screen.findByRole('region', { name: 'Pause the week of 2030-01-14.' });
 expect(within(panel).getByText(/Preview: nothing changes until you accept/)).toBeVisible();
 expect(within(panel).getByText('Sun, 24 Feb 2030 (was Sun, 17 Feb 2030)')).toBeVisible();
 expect(within(panel).getByText('Add validation.')).toBeVisible();
 fireEvent.click(within(panel).getAllByRole('radio', { name: 'Move it to Backlog to place myself' })[1]);
 fireEvent.click(within(panel).getByRole('button', { name: 'Accept changes' }));
 await waitFor(() => expect(calls('/planner/proposals/accept')[0][2]).toMatchObject({ proposal_id: 'p1', keep_task_ids: ['c1'] }));
});

it('shows buffer use, block offers and stale blocks on a check-in proposal, and can return to the answers', async () => {
 const state = active(roadmap(), { checkin: { ...checkin, status: 'proposed', answers: { week_feel: 'as_expected', next_week: 'more', note: null } } }, { proposal: proposal({ kind: 'checkin', message: 'Added a harder task.', effect: { ...proposal().effect, decisions: [], workload_before_minutes: 240, workload_after_minutes: 300, uses_buffer: true, add_block_suggested: true } }), proposal_blockers: [{ code: 'proposal_stale', message: 'Your roadmap changed after this preview was prepared. Prepare a fresh preview.' }] });
 serve(state); render(<RoadmapPlanner />);
 const panel = await screen.findByRole('region', { name: 'Pause the week of 2030-01-14.' });
 expect(within(panel).getByText(/reserved buffer/)).toBeVisible();
 expect(within(panel).getByText(/Add a study block/)).toBeVisible();
 expect(within(panel).getByText('5 h (was 4 h)')).toBeVisible();
 expect(within(panel).getByRole('button', { name: 'Accept changes' })).toBeDisabled();
 expect(screen.queryByRole('region', { name: 'Weekly check-in' })).not.toBeInTheDocument();
 fireEvent.click(within(panel).getByRole('button', { name: 'Adjust answers' }));
 expect(await screen.findByRole('region', { name: 'Weekly check-in' })).toBeVisible();
 expect(screen.getByRole('radio', { name: 'More' })).toBeChecked();
});

it('labels pace forecasts, shows lateness and offers previews for each response', async () => {
 const state = active(roadmap(), { pace: { status: 'behind', completed_minutes: 60, expected_minutes: 180, behind_minutes: 120, recent: { status: 'available', weeks_used: 4, weekly_minutes: 90, finish_date: '2030-03-20', weeks_late: 8 } } });
 serve(state, { '/planner/proposals/pace': () => state }); render(<RoadmapPlanner />);
 const pace = await screen.findByRole('region', { name: 'Recent pace' });
 expect(within(pace).getByText('At this pace you’ll finish 8 weeks late.')).toBeVisible();
 expect(within(pace).getByText(/Recent-pace forecast/)).toBeVisible();
 expect(screen.getByText('Behind by 2 h')).toBeVisible();
 fireEvent.click(within(pace).getByRole('button', { name: 'Cut scope' }));
 await waitFor(() => expect(calls('/planner/proposals/pace')[0][2]).toMatchObject({ action: 'cut_scope' }));
 await waitFor(() => expect(within(pace).getByRole('button', { name: 'Add hours' })).toBeEnabled());
 fireEvent.click(within(pace).getByRole('button', { name: 'Add hours' }));
 fireEvent.click(within(pace).getByRole('button', { name: 'Preview' }));
 await waitFor(() => expect(calls('/planner/proposals/pace')[1][2]).toMatchObject({ action: 'add_hours', extra_minutes: 60 }));
});

it('reports insufficient and zero pace plainly', async () => {
 serve(active()); const view = render(<RoadmapPlanner />);
 expect(within(await screen.findByRole('region', { name: 'Recent pace' })).getByText('Insufficient data.')).toBeVisible();
 view.unmount();
 serve(active(roadmap(), { pace: { status: 'behind', completed_minutes: 0, expected_minutes: 60, behind_minutes: 60, recent: { status: 'no_estimate', weeks_used: 2, weekly_minutes: 0, finish_date: null, weeks_late: null } } })); render(<RoadmapPlanner />);
 expect(await screen.findByText(/No finish estimate is available at your current pace/)).toBeVisible();
});

it('shows planning state and retry for rolling detail', async () => {
 const state = active(roadmap(), { rolling: { status: 'failed', weeks: ['2030-01-14'], error: 'Provider down.', retry_after: null } });
 serve(state, { '/planner/rolling': () => ({ version: 3, operation: null }) }); render(<RoadmapPlanner />);
 expect(await screen.findByText(/Your next tasks couldn’t be planned: Provider down/)).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Retry planning' }));
 await waitFor(() => expect(calls('/planner/rolling')).toHaveLength(1));
});

it('asks about unfinished tasks when completing a milestone', async () => {
 const state = active();
 serve(state, { '/planner/milestones/complete': () => state }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Mark Build a Python API complete' }));
 fireEvent.click(screen.getByRole('button', { name: 'Remove them from scope' }));
 await waitFor(() => expect(calls('/planner/milestones/complete')[0][2]).toMatchObject({ milestone_id: 'm1', completed: true, unfinished: 'remove' }));
});

it('Edit plan previews changes and never generates or saves settings directly', async () => {
 const plan = roadmap(); const state = active(plan);
 serve(state, { '/planner/runway': () => state.planner.runway, '/planner/proposals/edit': () => active(plan, {}, { proposal: proposal({ kind: 'edit' }) }) }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Edit plan' }));
 fireEvent.change(await screen.findByLabelText('Weekly budget in hours'), { target: { value: '6' } });
 expect(screen.queryByRole('button', { name: 'Save settings' })).not.toBeInTheDocument();
 await waitFor(() => expect(screen.getByRole('button', { name: 'Preview changes' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }));
 await waitFor(() => expect(calls('/planner/proposals/edit')[0][2].config.weekly_minutes).toBe(360));
 expect(await screen.findByText(/Preview: nothing changes until you accept/)).toBeVisible();
 expect(calls('/planner/config')).toHaveLength(0); expect(calls('/planner/generate')).toHaveLength(0);
});

it('Start new roadmap opens the planner pre-filled and starts from today', async () => {
 const plan = roadmap(); const state = active(plan); state.planner.config = config({ start_date: '2030-01-01', weekly_minutes: 420 }); state.planner.runway = { ...state.planner.runway };
 serve(state, { '/planner/runway': () => state.planner.runway }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Start new roadmap' }));
 expect(await screen.findByLabelText('Weekly budget in hours')).toHaveValue(7);
 expect(screen.getByLabelText('Start date')).toHaveValue('2030-01-09');
 expect(screen.getByRole('button', { name: 'Generate new roadmap' })).toBeInTheDocument();
});

it('lists past roadmaps and reads one as read-only', async () => {
 const state = active(roadmap(), {}, { archived: [{ id: 'arch1', schema_version: 'roadmap-v3', role: 'Data analyst', summary: 'Earlier route.', start_date: '2029-10-01', target_date: '2029-12-01', archived_at: '2030-01-01', completed_minutes: 300, planned_minutes: 600, tasks_completed: 5, tasks_total: 9, milestones_completed: 1, milestones_total: 3 }] });
 serve(state, { '/history/arch1': () => roadmap({ summary: 'Earlier route.' }) }); render(<RoadmapPlanner />);
 const past = await screen.findByRole('region', { name: 'Past roadmaps' });
 expect(within(past).getByText(/5 of 9 tasks · 1 of 3 milestones/)).toBeInTheDocument();
 fireEvent.click(within(past).getByRole('button', { name: 'View past roadmap: Data analyst' }));
 const details = await within(past).findByRole('region', { name: 'Past roadmap details' });
 expect(within(details).getByText('Read-only. Nothing here can change.')).toBeInTheDocument();
 expect(within(details).queryByRole('button', { name: /^Complete/ })).not.toBeInTheDocument();
});

it('keeps an older roadmap-v2 plan viewable and prompts for a new roadmap', async () => {
 const plan = legacyRoadmap();
 serve(workspace({ planner: planner({ active: plan, active_review: review(plan), active_view: null }) }), { '/planner/runway': () => workspace().planner.runway }); render(<RoadmapPlanner />);
 expect(await screen.findByText('Earlier roadmap: read-only')).toBeVisible();
 expect(screen.getByText('An older timed session.')).toBeVisible();
 expect(screen.getByText('Older deferred work')).toBeVisible();
 expect(screen.queryByRole('button', { name: /^Complete/ })).not.toBeInTheDocument();
 expect(screen.queryByRole('button', { name: 'Accept plan' })).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Start new roadmap' }));
 expect(await screen.findByRole('button', { name: 'Generate new roadmap' })).toBeInTheDocument();
});

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { MonthPreview, Outline, Workspace } from './types';
import { planner, review, roadmap, workspace } from '../../../tests/fixtures/roadmap-workspace';

const session = vi.hoisted(() => ({ account: { id: 'owner-one' }, token: 'synthetic-token' }));
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => session }));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: api, RoadmapError: class extends Error { status = 503; } }));

function outline(): Outline {
 const plan = roadmap();
 return { id: 'outline-1', revision: 1, summary: plan.summary, gaps: plan.gaps, milestones: plan.milestones,
  routine_rules: [], deadline_outcome: plan.deadline_outcome, beyond_deadline: plan.beyond_deadline,
  exclusions: plan.exclusions, config: plan.config };
}
const month: MonthPreview = { id: 'month-1', month: '2030-01', start_date: '2030-01-09', end_exclusive: '2030-01-28', time_zone: 'Asia/Singapore', tasks: [
 { id: 'task-1', title: 'Build one API endpoint', instructions: 'Implement and test the endpoint.', completion_outcome: 'Endpoint test passes.', milestone_key: 'm1', schedule: [{ date: '2030-01-09', start_time: '19:00', duration_minutes: 60 }] }
] };
const calls = (path: string) => api.mock.calls.filter(call => call[0] === path);
function serve(initial: Workspace) {
 let state = initial;
 api.mockImplementation((path: string, _token: string, body: Record<string, unknown>) => {
  if (!path || path.startsWith('/workspace')) return Promise.resolve(state);
  if (path === '/planner/outlines/generate') {
   state = { ...state, version: state.version + 1, planner: { ...state.planner, outline_candidate: outline() } };
   return Promise.resolve({ version: state.version, operation: null });
  }
  if (path === '/planner/outlines/outline-1') {
   const edited = body.outline as { milestones: Outline['milestones']; routine_rules: Outline['routine_rules'] };
   state = { ...state, version: state.version + 1, planner: { ...state.planner,
    outline_candidate: { ...state.planner.outline_candidate!, id: 'outline-2', revision: 2, milestones: edited.milestones, routine_rules: edited.routine_rules } } };
   return Promise.resolve(state);
  }
  if (path === '/planner/outlines/outline-2/accept') {
   state = { ...state, version: state.version + 1, planner: { ...state.planner, outline_active: state.planner.outline_candidate, outline_candidate: null } };
   return Promise.resolve(state);
  }
  if (path === '/planner/months/generate') {
   const candidate = body.revision ? { ...month, id: 'month-revision', replaces_block_id: 'accepted-block', replaced_task_ids: ['old-1', 'old-2'] } : month;
   state = { ...state, version: state.version + 1, planner: { ...state.planner, month_candidate: candidate } };
   return Promise.resolve({ version: state.version, operation: null });
  }
  if (path === '/planner/months/month-revision/discard') {
   state = { ...state, version: state.version + 1, planner: { ...state.planner, month_candidate: null } };
   return Promise.resolve(state);
  }
  if (path === '/planner/months/month-revision/accept') {
   state = { ...state, version: state.version + 1, planner: { ...state.planner, month_candidate: null, month_blocks: [{ id: 'month-revision', month: '2030-01' }] } };
   return Promise.resolve(state);
  }
  if (path === '/planner/months/month-1/accept') {
   state = { ...state, version: state.version + 1, planner: { ...state.planner, month_candidate: null, month_blocks: [{ id: 'month-1', month: '2030-01', needs_review: true }] } };
   return Promise.resolve(state);
  }
  return Promise.resolve(state);
 });
}
beforeEach(() => api.mockReset());

it('only generates an outline after the user requests it, then edits and accepts the preview', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('tab', { name: 'Starting point' }));
 fireEvent.click(screen.getByRole('tab', { name: 'Planner' }));
 expect(calls('/planner/outlines/generate')).toHaveLength(0);
 expect(calls('/planner/months/generate')).toHaveLength(0);
 expect(calls('/planner/roll-forward')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Generate roadmap' }));
 await screen.findByRole('heading', { name: 'Review your milestone outline' });
 expect(calls('/planner/outlines/generate')[0][2]).toMatchObject({ expected_version: 0, allow_partial_assessment: false });
 expect(screen.queryByRole('button', { name: 'Generate month preview' })).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Edit outline' }));
 const milestone = screen.getByRole('group', { name: 'Milestone 1' });
 fireEvent.change(within(milestone).getByLabelText('Outcome'), { target: { value: 'Demonstrate a tested endpoint.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Add routine' }));
 const routine = screen.getByRole('group', { name: 'Routine 1' });
 fireEvent.change(within(routine).getByLabelText('Activity'), { target: { value: 'Solve one problem' } });
 fireEvent.change(within(routine).getByLabelText('Difficulty'), { target: { value: 'medium' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save outline changes' }));
 await waitFor(() => expect(calls('/planner/outlines/outline-1')).toHaveLength(1));
 expect(calls('/planner/outlines/outline-1')[0][4]).toEqual({ method: 'PATCH' });
 expect(calls('/planner/outlines/outline-1')[0][2]).toMatchObject({ expected_version: 1, outline: { milestones: [{ demonstrable_outcome: 'Demonstrate a tested endpoint.' }], routine_rules: [{ activity: 'Solve one problem', difficulty: 'medium' }] } });
 await waitFor(() => expect(screen.getByRole('button', { name: 'Accept outline' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Accept outline' }));
 await screen.findByRole('heading', { name: 'Your milestone outline' });
 expect(calls('/planner/outlines/outline-2/accept')[0][2]).toMatchObject({ expected_version: 2 });
 expect(calls('/planner/months/generate')).toHaveLength(0);
});

it('generates a selected month explicitly, displays the preview and accepts it separately', async () => {
 serve(workspace({ planner: planner({ outline_active: outline() }) }));
 const view = render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Your milestone outline' });
 expect(calls('/planner/months/generate')).toHaveLength(0);
 expect(calls('/planner/roll-forward')).toHaveLength(0);
 fireEvent.change(screen.getByLabelText('Month'), { target: { value: '2030-01' } });
 fireEvent.click(screen.getByRole('button', { name: 'Generate month preview' }));
 await screen.findByRole('heading', { name: 'Preview for 2030-01' });
 expect(calls('/planner/months/generate')[0][2]).toMatchObject({ month: '2030-01', expected_version: 0 });
 expect(screen.getByText('Build one API endpoint')).toBeVisible();
 expect(screen.getByText('Implement and test the endpoint.')).toBeVisible();
 expect(calls('/planner/months/month-1/accept')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Accept month' }));
 await screen.findByText('2030-01 accepted · outline changed; review needed');
 expect(calls('/planner/months/month-1/accept')[0][2]).toMatchObject({ expected_version: 1 });
 expect(screen.queryByRole('heading', { name: 'Preview for 2030-01' })).not.toBeInTheDocument();
 view.unmount();
 render(<RoadmapPlanner />);
 await screen.findByText('2030-01 accepted · outline changed; review needed');
 expect(calls('/planner/months/generate')).toHaveLength(1);
 expect(calls('/planner/roll-forward')).toHaveLength(0);
});

it('revises an accepted month only on request and can discard the preview', async () => {
 const active = roadmap();
 serve(workspace({ version: 7, planner: planner({ outline_active: outline(), active, active_review: review(active), month_blocks: [{ id: 'accepted-block', month: '2030-01', needs_review: true }] }) }));
 render(<RoadmapPlanner />);
 await screen.findByText('2030-01 accepted · outline changed; review needed');
 expect(calls('/planner/months/generate')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Revise 2030-01' }));
 await screen.findByRole('heading', { name: 'Preview for 2030-01' });
 expect(calls('/planner/months/generate')[0][2]).toMatchObject({ month: '2030-01', revision: true, expected_version: 7, mutation_id: expect.any(String) });
 expect(screen.getByText(/revision replaces 2 untouched future tasks/)).toBeVisible();
 expect(screen.getByText(/Completed, started, edited, removed and note-bearing work remains saved/)).toBeVisible();
 expect(screen.getByRole('button', { name: 'Generate month preview' })).toBeDisabled();
 expect(screen.getByRole('button', { name: 'Revise 2030-01' })).toBeDisabled();
 expect(calls('/planner/months/month-revision/accept')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Discard preview' }));
 await waitFor(() => expect(screen.queryByRole('heading', { name: 'Preview for 2030-01' })).not.toBeInTheDocument());
 expect(calls('/planner/months/month-revision/discard')[0][2]).toMatchObject({ expected_version: 8, mutation_id: expect.any(String) });
 expect(screen.getByText('2030-01 accepted · outline changed; review needed')).toBeVisible();
 expect(screen.getByText('Your active roadmap')).toBeVisible();
 expect(calls('/planner/months/month-revision/accept')).toHaveLength(0);
});

it('accepts a revised month only after the replacement preview is reviewed', async () => {
 const active = roadmap();
 serve(workspace({ version: 4, planner: planner({ outline_active: outline(), active, active_review: review(active), month_blocks: [{ id: 'accepted-block', month: '2030-01' }] }) }));
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Revise 2030-01' }));
 await screen.findByRole('heading', { name: 'Preview for 2030-01' });
 expect(calls('/planner/months/month-revision/accept')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Accept month' }));
 await waitFor(() => expect(calls('/planner/months/month-revision/accept')[0][2]).toMatchObject({ expected_version: 5, mutation_id: expect.any(String) }));
 await waitFor(() => expect(screen.queryByRole('heading', { name: 'Preview for 2030-01' })).not.toBeInTheDocument());
 expect(screen.getByText('2030-01 accepted')).toBeVisible();
});

it('exposes task creation and editing for the active roadmap, not a plan preview', async () => {
 const task = { id: 'editable-1', title: 'Practice arrays', instructions: 'Solve a problem.', completion_outcome: 'Save the solution.', estimated_minutes: 30, milestone_key: 'm1', status: 'not_started' as const, schedule: [] };
 const active = roadmap({ editable_tasks: [task] });
 serve(workspace({ version: 3, planner: planner({ active, active_review: review(active) }) }));
 const view = render(<RoadmapPlanner />);
 const editor = await screen.findByRole('region', { name: 'Edit tasks' });
 expect(within(editor).getByText('Practice arrays')).toBeVisible();
 fireEvent.click(within(editor).getByRole('button', { name: 'Edit Practice arrays' }));
 fireEvent.change(within(editor).getByLabelText('Instructions'), { target: { value: 'Practice one array problem.' } });
 fireEvent.click(within(editor).getByRole('button', { name: 'Save task' }));
 await waitFor(() => expect(calls('/planner/tasks/edit')[0][2]).toMatchObject({ expected_version: 3, mutation_id: expect.any(String), task_id: 'editable-1', changes: { instructions: 'Practice one array problem.' } }));
 fireEvent.click(within(editor).getByRole('button', { name: 'Add task' }));
 fireEvent.change(within(editor).getByLabelText('Title'), { target: { value: 'Review graphs' } });
 fireEvent.change(within(editor).getByLabelText('Instructions'), { target: { value: 'Review traversal.' } });
 fireEvent.change(within(editor).getByLabelText('Completion outcome'), { target: { value: 'Write a traversal.' } });
 fireEvent.click(within(editor).getByRole('button', { name: 'Save task' }));
 await waitFor(() => expect(calls('/planner/tasks/add')[0][2]).toMatchObject({ expected_version: 3, mutation_id: expect.any(String), task: { title: 'Review graphs', schedule: [] } }));
 view.unmount();
 const candidate = roadmap({ id: 'preview' });
 serve(workspace({ planner: planner({ active, active_review: review(active), candidate, candidate_review: review(candidate) }) }));
 render(<RoadmapPlanner />);
 await screen.findByText('Preview: not active until you accept it');
 expect(screen.queryByRole('region', { name: 'Edit tasks' })).not.toBeInTheDocument();
});

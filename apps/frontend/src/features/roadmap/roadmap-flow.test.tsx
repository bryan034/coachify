import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { PlannedRoadmap, Workspace } from './types';
import { blankPlanner, blockedRunway, config, planner, review, roadmap, runway, workspace } from '../../../tests/fixtures/roadmap-workspace';

const session = vi.hoisted(() => ({ account: { id: 'owner-one' }, token: 'synthetic-token' }));
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => session }));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: api, RoadmapError: class extends Error { status = 503; } }));

function serve(state: Workspace, handlers: Record<string, (body: never) => unknown> = {}) {
 api.mockImplementation((path: string, _token: string, body: never) => {
  const route = path.split('?')[0];
  if (handlers[route]) return Promise.resolve(handlers[route](body));
  if (route === '/planner/runway') return Promise.resolve(runway());
  return Promise.resolve(state);
 });
}
const calls = (path: string) => api.mock.calls.filter(call => call[0] === path);
const withCandidate = (plan: PlannedRoadmap = roadmap(), overrides = {}) => workspace({ planner: planner({ candidate: plan, candidate_review: review(plan), ...overrides }) });
const withActive = (plan: PlannedRoadmap = roadmap(), overrides = {}) => workspace({ planner: planner({ active: plan, active_review: review(plan), ...overrides }) });
const openHelper = async () => fireEvent.click(await screen.findByRole('button', { name: /(Start|Continue with) chat helper/ }));
beforeEach(() => { api.mockReset(); });

it('asks for the device time zone so unsaved settings use local dates', async () => {
 serve(workspace()); render(<RoadmapPlanner />); await screen.findByRole('heading', { name: 'Your runway' });
 expect(api.mock.calls[0][0]).toMatch(/^\/workspace\?time_zone=/);
});

it('shows the goal and skills that will be used before any generation', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const heading = await screen.findByRole('heading', { name: 'What elo will use' });
 const section = heading.closest('section')!;
 expect(within(section).getByText('Backend developer')).toBeVisible();
 expect(within(section).getByText(/1 skill, 1 experience/)).toBeVisible();
 expect(within(section).getByText('Git')).toBeInTheDocument();
 expect(calls('/planner/generate')).toHaveLength(0);
});

it('explains why generation is disabled when dates or study time are missing', async () => {
 serve(workspace({ planner: blankPlanner() })); render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Before you can generate' });
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
 for (const reason of ['Choose a target date or a duration.', 'Set a weekly study budget above zero.', 'Add at least one recurring study block.']) expect(screen.getByText(reason)).toBeInTheDocument();
});

it('disables generation when the career goal or CV is missing', async () => {
 const state = workspace(); state.context.ready = false; state.context.issues = [{ source: 'career', message: 'Extract and review a Career goal first.', href: '/career-goal' }];
 serve(state); render(<RoadmapPlanner />); await screen.findByRole('heading', { name: 'Before you can generate' });
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
 expect(screen.getByRole('link', { name: 'Open Career Goal' })).toHaveAttribute('href', '/career-goal');
});

it('keeps target date and duration synchronised through the backend resolution', async () => {
 serve(workspace(), { '/planner/runway': (body: { config: { duration: unknown; target_date: string } }) => body.config.duration
  ? runway({ resolved: { today: '2030-01-09', start_date: '2030-01-09', target_date: '2030-03-06', matched_duration: { value: 8, unit: 'weeks' } } })
  : runway({ resolved: { today: '2030-01-09', start_date: '2030-01-09', target_date: body.config.target_date, matched_duration: body.config.target_date === '2030-02-06' ? { value: 4, unit: 'weeks' } : null } }) });
 render(<RoadmapPlanner />);
 fireEvent.change(await screen.findByRole('spinbutton', { name: 'Duration length' }), { target: { value: '8' } });
 await waitFor(() => expect(screen.getByLabelText('Target date')).toHaveValue('2030-03-06'));
 expect(screen.getByText(/Wed, 6 Mar 2030/)).toBeInTheDocument();
 expect(calls('/planner/runway').at(-1)![2].config).toMatchObject({ duration: { value: 8, unit: 'weeks' }, target_date: null });
 fireEvent.change(screen.getByLabelText('Target date'), { target: { value: '2030-02-06' } });
 await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'Duration length' })).toHaveValue(4));
 expect(calls('/planner/runway').at(-1)![2].config).toMatchObject({ duration: null, target_date: '2030-02-06' });
 fireEvent.change(screen.getByLabelText('Target date'), { target: { value: '2030-02-07' } });
 await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'Duration length' })).toHaveValue(null));
});

it('shows calculated runway with the extra capacity from backup blocks', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const runwaySection = await screen.findByRole('region', { name: 'Your runway' });
 expect(within(runwaySection).getByText('2 weeks, 5 days')).toBeVisible();
 expect(within(runwaySection).getAllByText('11.5 h')).toHaveLength(2);
 expect(within(runwaySection).getByText('+2 h (not enabled)')).toBeVisible();
 expect(within(runwaySection).getByText(/first week is partial/)).toBeVisible();
});

it('edits recurring blocks and saves settings before generating', async () => {
 const order: string[] = []; const state = workspace();
 const generated = { version: 2, operation: { id: 'g', status: 'pending', stage: 'preparing' } };
 serve(state, { '/planner/config': () => { order.push('config'); return { ...state, version: 1 }; }, '/planner/generate': () => { order.push('generate'); return generated; } });
 render(<RoadmapPlanner />);
 await screen.findByRole('button', { name: 'Add study block' });
 fireEvent.click(screen.getByRole('button', { name: 'Add study block' }));
 fireEvent.change(screen.getByRole('combobox', { name: 'Block 4 type' }), { target: { value: 'backup' } });
 await waitFor(() => expect(calls('/planner/runway').length).toBeGreaterThan(0));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Generate roadmap' }));
 await waitFor(() => expect(order).toEqual(['config', 'generate']));
 expect(calls('/planner/config')[0][2].config.blocks.at(-1)).toEqual({ day: 0, start_time: '19:00', duration_minutes: 60, kind: 'backup' });
 expect(calls('/planner/generate')[0][2].expected_version).toBe(1);
});

it('opens on the fixed planner sections, with chat only behind a button', async () => {
 serve(workspace({ planner: blankPlanner() })); render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Your runway' });
 for (const section of [/^Timeline/, /^Study time/, /^Blackout days and times/, /^Learning focus/]) expect(screen.getByRole('group', { name: section })).toBeVisible();
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
 expect(screen.queryByRole('tab', { name: 'Chat' })).not.toBeInTheDocument();
 expect(screen.getByLabelText('Target date')).toBeEnabled();
 expect(calls('/messages')).toHaveLength(0);
});

it('the chat helper starts on the first missing detail and lists what is still required', async () => {
 serve(workspace({ planner: blankPlanner() })); render(<RoadmapPlanner />);
 await openHelper();
 const helper = await screen.findByRole('region', { name: 'Chat helper' });
 expect(within(helper).getByRole('heading', { name: 'When would you like to be ready?' })).toBeVisible();
 expect(within(helper).getByText('target date or duration, weekly study budget, recurring study blocks')).toBeVisible();
 expect(screen.getByRole('textbox', { name: 'Answer here' })).toHaveFocus();
 fireEvent.click(within(helper).getByRole('button', { name: 'I want to be ready in 8 weeks.' }));
 expect(screen.getByRole('textbox', { name: 'Answer here' })).toHaveValue('I want to be ready in 8 weeks.');
 expect(calls('/messages')).toHaveLength(0);
});

it('the helper moves to the next question and says when the required details are done', async () => {
 const partly = blankPlanner(); partly.runway = { ...partly.runway, issues: partly.runway.issues.filter(issue => issue.code !== 'missing_target') };
 serve(workspace({ planner: partly })); const first = render(<RoadmapPlanner />);
 await openHelper(); expect(await screen.findByRole('heading', { name: 'How many hours can you study each week?' })).toBeVisible();
 first.unmount();
 serve(workspace()); render(<RoadmapPlanner />); await openHelper();
 expect(await screen.findByText(/All required details are filled in/)).toBeVisible();
});

it('closing the helper keeps the unsent answer and the planner, and Escape closes it too', async () => {
 serve(workspace()); render(<RoadmapPlanner />); await openHelper();
 fireEvent.change(await screen.findByRole('textbox', { name: 'Answer here' }), { target: { value: 'Keep this.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Close chat helper' }));
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
 expect(screen.getByRole('heading', { name: 'Your runway' })).toBeVisible();
 await openHelper(); expect(screen.getByRole('textbox', { name: 'Answer here' })).toHaveValue('Keep this.');
 fireEvent.keyDown(screen.getByRole('textbox', { name: 'Answer here' }), { key: 'Escape' });
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
});

it('opens the helper when a saved message failed, so it can be retried', async () => {
 const state = workspace({ operation: { id: 'm', status: 'failed', stage: 'failed', error: { code: 'model', detail: 'The helper could not answer.' } }, retry_request: { expected_version: 0, mutation_id: 'm', message: 'Hello', allow_partial_assessment: false } });
 serve(state); render(<RoadmapPlanner />);
 expect(await screen.findByRole('button', { name: 'Retry saved message' })).toBeVisible();
});

it('builds a weekly blackout time slot and sends it for the runway', async () => {
 serve(workspace({ planner: planner({ config: config({ blackouts: [] }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Add blackout' }));
 const rule = screen.getByRole('group', { name: 'Blackout 1' });
 expect(within(rule).getByText('Every week on Wed, all day, from 9 Jan 2030')).toBeVisible();
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 on Friday' }));
 fireEvent.change(within(rule).getByRole('spinbutton', { name: 'Blackout 1 interval' }), { target: { value: '2' } });
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 all day' }));
 fireEvent.change(within(rule).getByLabelText('Blackout 1 start time'), { target: { value: '12:00' } });
 fireEvent.change(within(rule).getByLabelText('Blackout 1 end date'), { target: { value: '2030-01-27' } });
 expect(within(rule).getByText('Every 2 weeks on Wed, Fri, 12:00–20:00, from 9 Jan 2030 until 27 Jan 2030')).toBeVisible();
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([{ frequency: 'weekly', start_date: '2030-01-09', end_date: '2030-01-27', interval: 2, weekdays: [2, 4], start_time: '12:00', end_time: '20:00' }]));
});

it('offers daily, monthly and one-day blackouts, keeping only the fields each one uses', async () => {
 serve(workspace({ planner: planner({ config: config({ blackouts: [] }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Add blackout' }));
 const rule = screen.getByRole('group', { name: 'Blackout 1' });
 const repeats = within(rule).getByRole('combobox', { name: 'Blackout 1 repeats' });
 fireEvent.change(repeats, { target: { value: 'monthly' } });
 fireEvent.change(within(rule).getByLabelText('Blackout 1 start date'), { target: { value: '2030-01-31' } });
 expect(within(rule).getByText('Every month on day 31 or the month’s last day, all day, from 31 Jan 2030')).toBeVisible();
 expect(within(rule).queryByRole('checkbox', { name: 'Blackout 1 on Monday' })).not.toBeInTheDocument();
 fireEvent.change(repeats, { target: { value: 'daily' } });
 expect(within(rule).getByText('Every day, all day, from 31 Jan 2030')).toBeVisible();
 fireEvent.change(within(rule).getByLabelText('Blackout 1 end date'), { target: { value: '2030-02-02' } });
 fireEvent.change(repeats, { target: { value: 'once' } });
 expect(within(rule).getByText('31 Jan 2030, all day')).toBeVisible();
 expect(within(rule).queryByLabelText('Blackout 1 end date')).not.toBeInTheDocument();
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([{ frequency: 'once', start_date: '2030-01-31', end_date: null, interval: 1, weekdays: [], start_time: null, end_time: null }]));
 fireEvent.click(within(rule).getByRole('button', { name: 'Remove blackout 1' }));
 expect(screen.queryByRole('group', { name: 'Blackout 1' })).not.toBeInTheDocument();
});

it('shows the backend explanation for a blackout that cannot apply and blocks generation', async () => {
 serve(workspace(), { '/planner/runway': () => runway({ can_generate: false, issues: [{ code: 'blackout_invalid', message: 'Blackout 1 must end after it starts on the same day.' }] }) });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('checkbox', { name: 'Blackout 1 all day' }));
 expect(await screen.findByText('Blackout 1 must end after it starts on the same day.')).toBeVisible();
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
});

it('saves unsaved settings before a chat message so the adviser uses the local time zone', async () => {
 const state = workspace({ planner: planner({ config_saved: false }) });
 serve(state, { '/planner/config': () => ({ ...state, version: 1 }), '/messages': () => ({ version: 2, operation: null }) });
 render(<RoadmapPlanner />); await openHelper();
 fireEvent.change(await screen.findByRole('textbox', { name: 'Answer here' }), { target: { value: 'Five hours a week.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
 await waitFor(() => expect(calls('/messages')).toHaveLength(1));
 expect(calls('/planner/config')).toHaveLength(1);
 expect(calls('/messages')[0][2].expected_version).toBe(1);
});

it('reports a backend validation problem and blocks generation', async () => {
 serve(workspace(), { '/planner/runway': () => { throw new Error('Check the supplied values and field limits.'); } });
 api.mockImplementation((path: string) => path === '/planner/runway' ? Promise.reject(new Error('Check the supplied values and field limits.')) : Promise.resolve(workspace()));
 render(<RoadmapPlanner />);
 fireEvent.change(await screen.findByLabelText('Preferred session in minutes'), { target: { value: '5' } });
 await screen.findAllByText('Check the supplied values and field limits.');
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
});

it('shows generation stages, then opens the review', async () => {
 const running = workspace({ operation: { id: 'g', status: 'running', stage: 'writing' } });
 const finished = withCandidate();
 api.mockImplementation((path: string) => path === '/progress' ? Promise.resolve({ version: 3, operation: { id: 'g', status: 'succeeded', stage: 'complete' } }) : Promise.resolve(api.mock.calls.length > 2 ? finished : running));
 render(<RoadmapPlanner />);
 await screen.findByText('Writing your roadmap');
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
 await screen.findByRole('button', { name: 'Accept plan' }, { timeout: 3000 });
});

it('reviews a plan: next assignment, remaining time, timeline, outcome and remaining gaps', async () => {
 serve(withCandidate()); render(<RoadmapPlanner />);
 await screen.findByText('Preview: not active until you accept it');
 const now = screen.getByRole('region', { name: 'Where you are now' });
 expect(within(now).getByText(/Wed, 9 Jan 2030, 19:00–20:00/)).toBeVisible();
 expect(within(now).getByText('2 weeks, 5 days')).toBeVisible();
 expect(within(now).getByText('11.5 h of usable study time')).toBeVisible();
 const timeline = screen.getByRole('region', { name: 'Milestone timeline' });
 expect(within(timeline).getByText('Sun, 27 Jan 2030')).toBeVisible();
 expect(within(timeline).getByText(/projected Wed, 9 Jan 2030 to Sun, 20 Jan 2030/)).toBeVisible();
 expect(within(timeline).getByText('Show this: A small API you can walk through.')).toBeVisible();
 expect(screen.getByText('By your target you can show a basic API, but not advanced Python.')).toBeVisible();
 expect(screen.getByRole('heading', { name: 'Beyond your deadline' })).toBeVisible();
 expect(screen.getByText('Advanced Python')).toBeVisible();
 expect(screen.getByText('Stated in your goal')).toBeVisible();
 expect(screen.getByText('Inferred requirement')).toBeVisible();
 expect(screen.getByRole('heading', { name: 'Confirmed gaps' })).toBeVisible();
 expect(screen.getByRole('heading', { name: 'Unknown skills' })).toBeVisible();
 expect(within(screen.getByRole('region', { name: 'Gaps this plan works on' })).getByText('Work authorisation')).toBeVisible();
 expect(screen.getByRole('button', { name: 'Accept plan' })).toBeEnabled();
});

it('returns to configuration without losing the preview and can go back', async () => {
 serve(withCandidate()); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Back to configuration' }));
 await screen.findByRole('heading', { name: 'Your runway' });
 expect(calls('/planner/discard')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Return to roadmap' }));
 await screen.findByRole('button', { name: 'Accept plan' });
});

it('draws the route with a numbered stop per milestone, today and reached outcomes', async () => {
 const base = roadmap().milestones[0];
 const plan = roadmap({ milestones: [{ ...base, id: 'm2', key: 'm2', title: 'Second', projected_end: '2030-01-24' }, { ...base, outcome: { demonstrated: true, note: 'Shown.' } }] });
 const state = withActive(plan); state.planner.active_review = { ...review(plan), remaining: runway({ resolved: { today: '2030-01-18', start_date: '2030-01-18', target_date: '2030-01-27', matched_duration: null } }) };
 serve(state); const { container } = render(<RoadmapPlanner />);
 await screen.findByText('Your active roadmap');
 const route = container.querySelector('.route-map')!;
 expect(route).toHaveAttribute('aria-hidden', 'true');
 expect(within(route as HTMLElement).getByText('Today')).toBeInTheDocument();
 const stops = [...route.querySelectorAll('.route-stop')];
 expect(stops.map(stop => [stop.textContent, stop.classList.contains('reached')])).toEqual([['1', true], ['2', false]]);
 expect(stops[0].getAttribute('title')).toMatch(/Build a Python API.*Sun, 20 Jan 2030/);
 expect(route.querySelector('.route-walked')).toBeInTheDocument();
});

it('accepts a preview and explains when it cannot be accepted', async () => {
 const accepted = withActive();
 serve(withCandidate(), { '/planner/accept': () => accepted }); const view = render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Accept plan' }));
 await screen.findByText('Your active roadmap'); expect(calls('/planner/accept')).toHaveLength(1);
 view.unmount(); api.mockReset();
 serve(withCandidate(roadmap(), { candidate_blockers: [{ code: 'settings_changed', message: 'Your settings changed after this preview was prepared. Generate a fresh plan.' }] })); render(<RoadmapPlanner />);
 await screen.findByText('Your settings changed after this preview was prepared. Generate a fresh plan.');
 expect(screen.getByRole('button', { name: 'Accept plan' })).toBeDisabled();
});

it('completes a session with evidence, separately from proficiency', async () => {
 const plan = roadmap(); const done = roadmap({ assignments: [{ ...plan.assignments[0], status: 'completed', completed_at: '2030-01-09T12:00:00+00:00', evidence_note: 'Test passed.' }] });
 serve(withActive(plan), { '/planner/assignments/status': () => withActive(done) }); render(<RoadmapPlanner />);
 await screen.findByText('Your active roadmap');
 fireEvent.click(screen.getByText('Mark session complete'));
 fireEvent.change(screen.getByRole('textbox', { name: 'What did you produce? (optional)' }), { target: { value: 'Test passed.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Complete session' }));
 await screen.findByRole('heading', { name: 'Completed sessions' });
 expect(calls('/planner/assignments/status')[0][2]).toMatchObject({ assignment_id: 'a1', status: 'completed', evidence_note: 'Test passed.' });
 expect(screen.getByText('These record what you did. They don’t change your assessed skills.')).toBeVisible();
 expect(screen.getByText('Your note: Test passed.')).toBeVisible();
 expect(screen.getByText('Outcome not yet demonstrated.', { exact: false })).toBeVisible();
 expect(screen.getByText(/Finishing sessions records progress, not proficiency/)).toBeVisible();
});

it('records a demonstrated outcome with a note', async () => {
 serve(withActive(), { '/planner/milestones/outcome': () => withActive() }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Record how you demonstrated it' }));
 expect(screen.getByRole('button', { name: 'Save outcome' })).toBeDisabled();
 fireEvent.change(screen.getByRole('textbox', { name: /How did you demonstrate/ }), { target: { value: 'Showed a mentor.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save outcome' }));
 await waitFor(() => expect(calls('/planner/milestones/outcome')[0][2]).toMatchObject({ milestone_id: 'm1', demonstrated: true, note: 'Showed a mentor.' }));
});

it('asks experience questions and offers to regenerate once answered', async () => {
 const answered = withCandidate(roadmap(), { confirmations: { docker: { answer: 'no_experience' } }, signals: [{ kind: 'evidence', message: 'You answered experience questions after this plan was prepared.' }] });
 serve(withCandidate(), { '/planner/confirmations': () => answered, '/planner/generate': () => ({ version: 3, operation: null }) }); render(<RoadmapPlanner />);
 fireEvent.click(within(await screen.findByRole('group', { name: 'Have you run a service in Docker?' })).getByRole('radio', { name: 'No' }));
 await screen.findByRole('button', { name: 'Regenerate' });
 expect(calls('/planner/confirmations')[0][2]).toMatchObject({ gap_id: 'docker', answer: 'no_experience' });
 fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }));
 await waitFor(() => expect(calls('/planner/generate')).toHaveLength(1));
});

it('shows what a revision changes, keeps completed work and applies only on accept', async () => {
 const active = roadmap({ id: 'old', assignments: [{ ...roadmap().assignments[0], status: 'completed', completed_at: 'x', evidence_note: 'Done.' }] });
 const revised = roadmap({ id: 'new', base_active_id: 'old', assignments: [active.assignments[0], { ...roadmap().assignments[0], id: 'a2', key: 'a2', date: '2030-01-10', start_time: '18:00', task: 'Add input validation.' }], changes: { completed_preserved: 1, assignments_added: ['Add input validation.'], assignments_moved: [], assignments_removed: [], milestones_added: [], milestones_moved: ['Build a Python API'], milestones_removed: [] } });
 serve(workspace({ planner: planner({ active, active_review: review(active), candidate: revised, candidate_review: review(revised) }) }), { '/planner/discard': () => withActive(active) });
 render(<RoadmapPlanner />);
 const changes = await screen.findByRole('region', { name: 'What this preview changes' });
 expect(within(changes).getByText('1 completed session stays exactly as recorded.')).toBeVisible();
 expect(within(changes).getByText('Add input validation.')).toBeVisible();
 expect(within(changes).getByText('Build a Python API')).toBeVisible();
 expect(screen.getByRole('heading', { name: 'Completed sessions' })).toBeVisible();
 expect(screen.queryByRole('button', { name: 'Reopen session' })).not.toBeInTheDocument();
 expect(screen.queryByText('Mark session complete')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Discard preview' }));
 await screen.findByText('Your active roadmap');
 expect(calls('/planner/accept')).toHaveLength(0);
});

it('offers an updated preview when settings, progress or evidence change', async () => {
 serve(withActive(roadmap(), { signals: [{ kind: 'settings', message: 'Your study settings changed since this roadmap was accepted.' }] }), { '/planner/generate': () => ({ version: 3, operation: null }) });
 render(<RoadmapPlanner />);
 await screen.findByText('Your study settings changed since this roadmap was accepted.');
 fireEvent.click(screen.getByRole('button', { name: 'Preview updated roadmap' }));
 await waitFor(() => expect(calls('/planner/generate')).toHaveLength(1));
});

it('keeps the plan and offers an exact retry when generation fails', async () => {
 const retry = { expected_version: 2, mutation_id: 'failed-one', allow_partial_assessment: false };
 const state = withActive(roadmap(), { retry_generate: retry }); state.operation = { id: 'failed-one', status: 'failed', stage: 'failed', error: { code: 'plan_validation', detail: 'We could not produce a plan that fits your schedule after 3 attempts. Your last valid plan is unchanged.' } };
 serve(state, { '/planner/generate': () => ({ version: 3, operation: null }) }); render(<RoadmapPlanner />);
 await screen.findByText(/Your last valid plan is unchanged/);
 expect(screen.getByText('Your active roadmap')).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
 await waitFor(() => expect(calls('/planner/generate')[0][2]).toEqual(retry));
});

it('opens the chat helper from a button for edits on the roadmap page', async () => {
 serve(withActive(), { '/messages': () => ({ version: 2, operation: null }) }); render(<RoadmapPlanner />);
 await openHelper();
 expect(screen.queryByRole('tab', { name: 'Chat' })).not.toBeInTheDocument();
 expect(screen.getByText('Your active roadmap')).toBeVisible();
 const box = screen.getByRole('textbox', { name: 'Ask for a change' });
 expect(box).toBeVisible(); expect(screen.getByText('Changes appear as a preview first.')).toBeVisible();
 fireEvent.change(box, { target: { value: 'Move Wednesday to Thursday.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
 await waitFor(() => expect(calls('/messages')[0][2]).toMatchObject({ message: 'Move Wednesday to Thursday.' }));
});

it('requires the research choice before the helper can prepare a plan change', async () => {
 const state = withActive(); state.context.research_coverage = 'unavailable';
 serve(state); render(<RoadmapPlanner />); await openHelper();
 fireEvent.change(screen.getByRole('textbox', { name: 'Ask for a change' }), { target: { value: 'Move it.' } });
 expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
 fireEvent.click(screen.getByRole('checkbox', { name: /Continue with available evidence/ }));
 expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
});

it('a new preview from chat opens on the roadmap tab', async () => {
 let state = withActive();
 api.mockImplementation((path: string) => path === '/messages' ? Promise.resolve({ version: 2, operation: null }) : Promise.resolve(state));
 render(<RoadmapPlanner />);
 await openHelper();
 fireEvent.change(screen.getByRole('textbox', { name: 'Ask for a change' }), { target: { value: 'Move it.' } });
 const preview = roadmap({ id: 'preview', base_active_id: 'plan1' }); state = workspace({ planner: planner({ active: roadmap(), active_review: review(), candidate: preview, candidate_review: review(preview) }) });
 await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
 await screen.findByText('Preview: not active until you accept it');
 expect(screen.getByRole('tab', { name: 'Roadmap' })).toHaveAttribute('aria-selected', 'true');
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
});

it('keeps an older untimed plan readable and separate', async () => {
 const state = workspace(); state.active = { id: 'old', tasks: [{ id: 't', title: 'Older activity', status: 'completed' }] } as never;
 serve(state); render(<RoadmapPlanner />);
 expect(await screen.findByText('Earlier plan without session times')).toBeInTheDocument();
 expect(screen.getByText('Older activity · completed')).toBeInTheDocument();
});

it('offers a saved zero-hour period as a blackout and notes reduced periods', async () => {
 const state = workspace(); state.context.planning_defaults.availability_periods = [{ start_date: '2030-01-14', end_date: '2030-01-15', weekly_hours: 0 }, { start_date: '2030-01-21', end_date: '2030-01-22', weekly_hours: 3 }];
 serve(state); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Add as blackout' }));
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([...config().blackouts, { frequency: 'daily', start_date: '2030-01-14', end_date: '2030-01-15', interval: 1, weekdays: [], start_time: null, end_time: null }]));
 expect(screen.getByText(/You saved 3 hours a week/)).toBeInTheDocument();
});

it('offers switching to the device time zone', async () => {
 const state = workspace({ planner: planner({ config: config({ time_zone: 'Asia/Tokyo' }) }) });
 const zone = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => ({ resolvedOptions: () => ({ timeZone: 'Asia/Singapore' }) }) as never);
 serve(state); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Use Asia/Singapore' }));
 zone.mockRestore();
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.time_zone).toBe('Asia/Singapore'));
});

it('a blocked runway disables generation on saved settings too', async () => {
 serve(workspace({ planner: planner({ runway: blockedRunway() }) })); render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Before you can generate' });
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
});

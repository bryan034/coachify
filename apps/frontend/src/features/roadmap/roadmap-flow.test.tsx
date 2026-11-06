import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { PlannedRoadmap, Workspace, PlannerConfig } from './types';
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
  if (route === '/planner/config') return Promise.resolve({ ...state, version: state.version + 1, planner: { ...state.planner, config: (body as { config: PlannerConfig }).config, config_saved: true } });
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
 expect(within(section).queryByText('Git')).not.toBeInTheDocument();
 fireEvent.click(within(section).getByRole('button', { name: /1 skill, 1 experience/ }));
 expect(within(section).getByText('Git')).toBeVisible();
 expect(calls('/planner/generate')).toHaveLength(0);
});

it('closes a What elo will use panel with Escape, returning focus, and with a click elsewhere', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const section = (await screen.findByRole('heading', { name: 'What elo will use' })).closest('section')!;
 const menu = within(section).getByRole('button', { name: /1 skill, 1 experience/ });
 fireEvent.click(menu);
 expect(menu).toHaveAttribute('aria-expanded', 'true');
 fireEvent.keyDown(document, { key: 'Escape' });
 expect(within(section).queryByText('Git')).not.toBeInTheDocument();
 expect(menu).toHaveFocus();
 fireEvent.click(menu);
 fireEvent.pointerDown(within(section).getByText('Git'));
 expect(within(section).getByText('Git')).toBeVisible();
 fireEvent.pointerDown(document.body);
 expect(within(section).queryByText('Git')).not.toBeInTheDocument();
 expect(menu).toHaveAttribute('aria-expanded', 'false');
});

it('shows each study block with its start and end, and the end time sets its length', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const chip = await screen.findByRole('button', { name: /Edit Monday block: 19:00–21:00/ });
 expect(within(chip).getByText('19:00–21:00')).toBeVisible();
 fireEvent.click(chip);
 fireEvent.change(screen.getByLabelText('Block 1 end time'), { target: { value: '22:30' } });
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blocks[0].duration_minutes).toBe(210));
 expect(await screen.findByRole('button', { name: /Edit Monday block: 19:00–22:30/ })).toBeVisible();
 fireEvent.change(screen.getByLabelText('Block 1 end time'), { target: { value: '19:05' } });
 expect(screen.getByText('Use 15 minutes to 8 hours')).toBeVisible();
 expect(screen.getByLabelText('Block 1 minutes')).toHaveValue(210);
});

it('saves planner changes without being asked, keeping edits made during the save', async () => {
 const state = workspace();
 let finish: (value: unknown) => void = () => {};
 serve(state, { '/planner/config': () => new Promise(resolve => { finish = resolve; }) });
 render(<RoadmapPlanner />);
 const session = await screen.findByLabelText('Preferred session in minutes');
 fireEvent.change(session, { target: { value: '45' } });
 await waitFor(() => expect(calls('/planner/config')).toHaveLength(1), { timeout: 3000 });
 expect(calls('/planner/config')[0][2].config.preferred_session_minutes).toBe(45);
 expect(session).toBeEnabled();
 fireEvent.change(session, { target: { value: '50' } });
 finish({ ...state, version: state.version + 1, planner: { ...state.planner, config: calls('/planner/config')[0][2].config } });
 await waitFor(() => expect(calls('/planner/config')).toHaveLength(2), { timeout: 3000 });
 expect(session).toHaveValue(50);
 expect(calls('/planner/config')[1][2].config.preferred_session_minutes).toBe(50);
 expect(calls('/planner/config')[1][2].expected_version).toBe(state.version + 1);
 finish({ ...state, version: state.version + 2, planner: { ...state.planner, config: calls('/planner/config')[1][2].config } });
 expect(await screen.findByText('All changes saved')).toBeVisible();
});

it('offers Save settings when saving automatically fails, and keeps the change', async () => {
 serve(workspace(), { '/planner/config': () => Promise.reject(new Error('Synthetic failure')) });
 render(<RoadmapPlanner />);
 const session = await screen.findByLabelText('Preferred session in minutes');
 fireEvent.change(session, { target: { value: '45' } });
 expect(await screen.findByRole('button', { name: 'Save settings' }, { timeout: 3000 })).toBeVisible();
 expect(session).toHaveValue(45);
});

it('sends unsaved changes as the page closes', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 fireEvent.change(await screen.findByLabelText('Preferred session in minutes'), { target: { value: '45' } });
 fireEvent(window, new Event('pagehide'));
 const sent = calls('/planner/config').at(-1)!;
 expect(sent[2].config.preferred_session_minutes).toBe(45);
 expect(sent[4]).toEqual({ keepalive: true });
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
 expect(within(screen.getByRole('region', { name: 'Your runway' })).getByText('Target · Wed, 6 Mar 2030')).toBeVisible();
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

function wideScreen() { vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('min-width') })); }
afterEach(() => { vi.unstubAllGlobals(); });

it('lays every planner detail along the road, without calling the model', async () => {
 serve(workspace({ planner: blankPlanner() })); render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Your runway' });
 for (const stop of ['Start', 'Finish', 'Weekly study time', 'Session length', 'Recurring study blocks', 'Backup blocks', 'Learning focus']) expect(screen.getByRole('group', { name: stop })).toBeVisible();
 expect(screen.getByText(/I’ll start on/)).toBeVisible();
 expect(screen.getByLabelText('Target date')).toBeEnabled();
 expect(calls('/messages')).toHaveLength(0);
});

it('moves along the road as each required detail is filled, ending at Generate', async () => {
 const missingBudget = planner({ config: config({ weekly_minutes: null }), runway: runway({ can_generate: false, issues: [{ code: 'no_budget', message: 'Set a weekly study budget above zero.' }] }) });
 serve(workspace({ planner: blankPlanner() })); const first = render(<RoadmapPlanner />);
 const current = () => document.querySelector('.road-stop[aria-current="step"] fieldset');
 await screen.findByRole('heading', { name: 'Your runway' });
 expect(current()).toHaveAccessibleName('Finish');
 expect(document.querySelectorAll('.road-bend.travelled')).toHaveLength(1);
 first.unmount();
 serve(workspace({ planner: missingBudget })); const second = render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Your runway' });
 expect(current()).toHaveAccessibleName('Weekly study time');
 expect(document.querySelectorAll('.road-bend.travelled')).toHaveLength(2);
 second.unmount();
 serve(workspace()); render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Your runway' });
 expect(current()).toBeNull();
 expect(document.querySelectorAll('.road-bend.travelled')).toHaveLength(7);
 const road = document.querySelector('.plan-road') as HTMLElement;
 expect(within(road).getByRole('button', { name: 'Generate roadmap' }).closest('li')).toHaveClass('road-end', 'passed');
});

it('says how long a target date is when it is not a whole duration, and can still be edited', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const finish = await screen.findByRole('group', { name: 'Finish' });
 expect(within(finish).getByText('2 weeks, 5 days')).toBeVisible();
 expect(within(finish).getByRole('spinbutton', { name: 'Duration length' })).toHaveValue(null);
 fireEvent.change(within(finish).getByRole('spinbutton', { name: 'Duration length' }), { target: { value: '3' } });
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config).toMatchObject({ duration: { value: 3, unit: 'weeks' }, target_date: null }));
});

it('writes settings into the sentence and flags a start date in the past', async () => {
 serve(workspace({ planner: planner({ runway: runway({ can_generate: false, issues: [{ code: 'start_in_past', message: 'Choose a start date of today or later.' }] }) }) })); render(<RoadmapPlanner />);
 const start = await screen.findByRole('group', { name: 'Start' });
 expect(within(start).getByText('9 Jan 2030')).toBeVisible();
 expect(start.querySelector('.token')).toHaveClass('warn');
 expect(screen.getByRole('spinbutton', { name: 'Weekly budget in hours' })).toHaveValue(5);
 fireEvent.click(screen.getByRole('checkbox', { name: 'Allow backup blocks when preferred time runs out' }));
 expect(within(screen.getByRole('group', { name: 'Backup blocks' })).getByText('allowed')).toBeVisible();
});

it('chooses a learning focus from the sentence and adds a study block from the week', async () => {
 serve(workspace({ planner: planner({ config: config({ learning_focus: [], learning_notes: '' }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Choose learning focus' }));
 fireEvent.click(screen.getByRole('checkbox', { name: 'Certification' }));
 expect(within(screen.getByRole('group', { name: 'Learning focus' })).getByRole('button', { name: 'Choose learning focus' })).toHaveTextContent('Certification');
 fireEvent.click(screen.getByRole('button', { name: 'Add study block on Tuesday' }));
 expect(screen.getByRole('combobox', { name: 'Block 4 day' })).toHaveValue('1');
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.learning_focus).toEqual(['certification']));
 fireEvent.click(screen.getByRole('button', { name: 'Done' }));
 expect(screen.queryByRole('combobox', { name: 'Block 4 day' })).not.toBeInTheDocument();
});

it('docks the chat helper beside the planner on wide screens without taking focus, and respects closing it', async () => {
 wideScreen(); serve(workspace({ planner: blankPlanner() })); render(<RoadmapPlanner />);
 const helper = await screen.findByRole('region', { name: 'Chat helper' });
 expect(within(helper).getByRole('textbox', { name: 'Answer here' })).not.toHaveFocus();
 fireEvent.click(screen.getByRole('button', { name: 'Close chat helper' }));
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
 await openHelper();
 expect(screen.getByRole('textbox', { name: 'Answer here' })).toHaveFocus();
});

it('closes the docked helper when the screen narrows, so it never covers the page, and restores it when wide', async () => {
 const listeners: (() => void)[] = []; const media = { matches: true, addEventListener: (_: string, listener: () => void) => listeners.push(listener), removeEventListener: () => {} };
 vi.stubGlobal('matchMedia', () => media); serve(workspace({ planner: blankPlanner() })); render(<RoadmapPlanner />);
 await screen.findByRole('region', { name: 'Chat helper' });
 media.matches = false; act(() => listeners.forEach(listener => listener()));
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
 media.matches = true; act(() => listeners.forEach(listener => listener()));
 expect(screen.getByRole('region', { name: 'Chat helper' })).toBeVisible();
 media.matches = false; act(() => listeners.forEach(listener => listener()));
 await openHelper();
 expect(screen.getByRole('region', { name: 'Chat helper' })).toBeVisible();
 expect(screen.getByRole('textbox', { name: 'Answer here' })).toHaveFocus();
});

it('keeps the helper closed on the generated roadmap until asked for', async () => {
 wideScreen(); serve(withActive()); render(<RoadmapPlanner />);
 await screen.findByText('Your active roadmap');
 expect(screen.queryByRole('region', { name: 'Chat helper' })).not.toBeInTheDocument();
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

it('adds blocked times to the week as their own blocks and sends them for the runway', async () => {
 serve(workspace({ planner: planner({ config: config({ blackouts: [] }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Add Blockout Times' }));
 const rule = screen.getByRole('group', { name: 'Blackout 1' });
 expect(within(rule).getByText('Every week on Mon, 18:00–20:00, from 9 Jan 2030')).toBeVisible();
 const week = document.querySelector('.block-week') as HTMLElement;
 const monday = within(week).getByRole('button', { name: /Edit blocked time on Monday/ });
 expect(monday).toHaveClass('blocked');
 expect(within(monday).getByText('18:00–20:00')).toBeVisible();
 expect(within(monday).getByText('Blocked')).toBeVisible();
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 on Monday' }));
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 on Wednesday' }));
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 on Friday' }));
 expect(within(week).getByRole('button', { name: /Edit blocked time on Friday/ })).toBeVisible();
 fireEvent.change(within(rule).getByRole('spinbutton', { name: 'Blackout 1 interval' }), { target: { value: '2' } });
 fireEvent.change(within(rule).getByLabelText('Blackout 1 start time'), { target: { value: '12:00' } });
 fireEvent.change(within(rule).getByLabelText('Blackout 1 end date'), { target: { value: '2030-01-27' } });
 expect(within(rule).getByText('Every 2 weeks on Wed, Fri, 12:00–20:00, from 9 Jan 2030 until 27 Jan 2030')).toBeVisible();
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([{ frequency: 'weekly', start_date: '2030-01-09', end_date: '2030-01-27', interval: 2, weekdays: [2, 4], start_time: '12:00', end_time: '20:00' }]));
});

it('offers daily, monthly and one-day blocked times, keeping only the fields each one uses', async () => {
 serve(workspace({ planner: planner({ config: config({ blackouts: [] }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Add Blockout Times' }));
 const rule = screen.getByRole('group', { name: 'Blackout 1' });
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 all day' }));
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
 expect(document.querySelector('.block-others .blocked')).toHaveTextContent('31 Jan 2030');
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([{ frequency: 'once', start_date: '2030-01-31', end_date: null, interval: 1, weekdays: [], start_time: null, end_time: null }]));
 fireEvent.click(within(rule).getByRole('button', { name: 'Remove blackout 1' }));
 expect(screen.queryByRole('group', { name: 'Blackout 1' })).not.toBeInTheDocument();
});

it('shows the backend explanation for a blackout that cannot apply and blocks generation', async () => {
 serve(workspace(), { '/planner/runway': () => runway({ can_generate: false, issues: [{ code: 'blackout_invalid', message: 'Blackout 1 must end after it starts on the same day.' }] }) });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: /Edit blocked time: 12 Jan 2030/ }));
 fireEvent.click(screen.getByRole('checkbox', { name: 'Blackout 1 all day' }));
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
 expect(now).toHaveTextContent('Wed, 9 Jan 2030, 19:00–20:00');
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

it('stays in configuration when saving settings returns the same preview', async () => {
 const state = withCandidate();
 serve(state, { '/planner/config': () => ({ ...state, version: state.version + 1 }) });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Back to configuration' }));
 fireEvent.change(await screen.findByLabelText('Preferred session in minutes'), { target: { value: '45' } });
 await waitFor(() => expect(calls('/planner/config')).toHaveLength(1), { timeout: 3000 });
 expect(await screen.findByText('All changes saved')).toBeVisible();
 expect(screen.queryByRole('button', { name: 'Save settings' })).not.toBeInTheDocument();
 expect(screen.getByRole('heading', { name: 'Your runway' })).toBeVisible();
 expect(calls('/planner/discard')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Return to roadmap' }));
 expect(await screen.findByRole('button', { name: 'Accept plan' })).toBeVisible();
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

const taskName = 'Mark complete: Write one tested Python endpoint.';
const completed = (note: string | null) => { const plan = roadmap(); return roadmap({ assignments: [{ ...plan.assignments[0], status: 'completed', completed_at: '2030-01-09T12:00:00+00:00', evidence_note: note }] }); };

it('ticks a session off the to-do list, then adds what was produced, separately from proficiency', async () => {
 const replies = [withActive(completed(null)), withActive(completed('Test passed.'))];
 serve(withActive(), { '/planner/assignments/status': () => replies.shift() }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('checkbox', { name: taskName }));
 await waitFor(() => expect(screen.getByRole('checkbox', { name: taskName })).toBeChecked());
 expect(calls('/planner/assignments/status')[0][2]).toMatchObject({ assignment_id: 'a1', status: 'completed', evidence_note: null });
 expect(screen.getByText('Ticking a session records what you did. It doesn’t change your assessed skills.')).toBeVisible();
 fireEvent.click(screen.getByText('Add what you produced'));
 expect(screen.getByRole('button', { name: 'Save note' })).toBeDisabled();
 fireEvent.change(screen.getByRole('textbox', { name: 'What did you produce? (optional)' }), { target: { value: 'Test passed.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
 await screen.findByText('Your note: Test passed.');
 expect(calls('/planner/assignments/status')[1][2]).toMatchObject({ assignment_id: 'a1', status: 'completed', evidence_note: 'Test passed.' });
 expect(screen.getByText('Outcome not yet demonstrated.', { exact: false })).toBeVisible();
 expect(screen.getByText(/Finishing sessions records progress, not proficiency/)).toBeVisible();
});

it('shows a tick at once and undoes it when saving fails', async () => {
 let fail: (reason: Error) => void = () => {};
 serve(withActive(), { '/planner/assignments/status': () => new Promise((_, reject) => { fail = reject; }) }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('checkbox', { name: taskName }));
 expect(screen.getByRole('checkbox', { name: taskName })).toBeChecked();
 await act(async () => { fail(new Error('Your plan could not be saved.')); });
 expect(await screen.findByRole('alert')).toHaveTextContent('Your plan could not be saved.');
 expect(screen.getByRole('checkbox', { name: taskName })).not.toBeChecked();
});

it('reopens a ticked session', async () => {
 serve(withActive(completed('Done.')), { '/planner/assignments/status': () => withActive() }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('checkbox', { name: taskName }));
 await waitFor(() => expect(calls('/planner/assignments/status')[0][2]).toMatchObject({ assignment_id: 'a1', status: 'scheduled' }));
 await waitFor(() => expect(screen.getByRole('checkbox', { name: taskName })).not.toBeChecked());
});

const toDoPlan = () => { const base = roadmap(); const session = base.assignments[0]; return roadmap({ assignments: [session, { ...session, id: 'a2', key: 'a2', date: '2030-01-11', start_time: '18:00', task: 'Add input validation.' }, { ...session, id: 'a3', key: 'a3', date: '2030-01-08', start_time: '18:00', task: 'Read the framework guide.', status: 'completed', completed_at: 'x', evidence_note: 'Notes taken.' }] }); };

it('leads with this week as a to-do list, with each session showing its skill', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 const list = await screen.findByRole('region', { name: 'To-do list' });
 expect(within(list).getByRole('heading', { name: 'This week' })).toBeVisible();
 expect(within(list).getByRole('button', { name: 'Weekly' })).toHaveAttribute('aria-pressed', 'true');
 expect(within(list).getByText('1 of 3 sessions done, 2 h left')).toBeVisible();
 expect(within(list).getAllByRole('checkbox').map(box => box.getAttribute('aria-label'))).toEqual(['Mark complete: Read the framework guide.', taskName, 'Mark complete: Add input validation.']);
 expect(within(list).getAllByText('Python')).toHaveLength(3);
 expect(within(list).getByText('Next')).toBeVisible();
});

it('switches to one day at a time and can pick another day', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 const list = await screen.findByRole('region', { name: 'To-do list' });
 fireEvent.click(within(list).getByRole('button', { name: 'Daily' }));
 expect(within(list).getByRole('heading', { name: 'Today' })).toBeVisible();
 expect(within(list).getAllByRole('checkbox')).toHaveLength(1);
 fireEvent.click(within(list).getByRole('button', { name: 'Thu, 10 Jan 2030, 0 sessions' }));
 expect(within(list).getByText('Nothing is planned for Thu, 10 Jan 2030.')).toBeVisible();
 fireEvent.click(within(list).getByRole('button', { name: 'Next day' }));
 expect(within(list).getByText('Add input validation.')).toBeVisible();
});

it('shows the month as a calendar of week summaries that open the week', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 const list = await screen.findByRole('region', { name: 'To-do list' });
 fireEvent.click(within(list).getByRole('button', { name: 'Monthly' }));
 expect(within(list).getByRole('heading', { name: 'January 2030' })).toBeVisible();
 expect(within(list).queryByRole('checkbox')).toBeNull();
 const weeks = within(list).getAllByRole('button', { name: /^Open week of/ });
 expect(weeks).toHaveLength(5);
 expect(weeks[1]).toHaveAccessibleName(expect.stringContaining('Open week of 7 Jan 2030. 3 sessions, 1 done'));
 expect(weeks[1]).toHaveAccessibleName(expect.stringContaining('Build a Python API'));
 expect(weeks[2]).toHaveAccessibleName(expect.stringContaining('Sessions not planned yet'));
 const bars = weeks[1].querySelectorAll('.month-bar');
 expect(bars).toHaveLength(1);
 expect((bars[0] as HTMLElement).style.gridColumn).toBe('3 / 8');
 fireEvent.click(weeks[2]);
 expect(within(list).getByRole('heading', { name: 'Week of 14 Jan' })).toBeVisible();
 expect(within(list).getByText(/Sessions for this week aren’t planned yet/)).toBeVisible();
 expect(within(list).getByText('Build a Python API')).toBeVisible();
});

it('stops the to-do list moving past the plan and offers a way back to today', async () => {
 serve(withActive()); render(<RoadmapPlanner />);
 const list = await screen.findByRole('region', { name: 'To-do list' });
 expect(within(list).getByRole('button', { name: 'Previous week' })).toBeDisabled();
 expect(within(list).queryByRole('button', { name: 'Today' })).toBeNull();
 for (let step = 0; step < 2; step++) fireEvent.click(within(list).getByRole('button', { name: 'Next week' }));
 expect(within(list).getByRole('heading', { name: 'Week of 21 Jan' })).toBeVisible();
 expect(within(list).getByRole('button', { name: 'Next week' })).toBeDisabled();
 fireEvent.click(within(list).getByRole('button', { name: 'Today' }));
 expect(within(list).getByRole('heading', { name: 'This week' })).toBeVisible();
});

it('shows each skill the plan builds with its sessions', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 const skills = await screen.findByRole('region', { name: 'Skills this plan builds' });
 expect(within(skills).getByText('Python')).toBeVisible();
});

it('does not let a preview be ticked off', async () => {
 serve(withCandidate()); render(<RoadmapPlanner />);
 const list = await screen.findByRole('region', { name: 'To-do list' });
 expect(within(list).queryByRole('checkbox')).toBeNull();
 expect(within(list).getByText('Accept this plan to start ticking off sessions.')).toBeVisible();
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
 expect(screen.getByText('Your note: Done.')).toBeVisible();
 expect(screen.queryByRole('checkbox', { name: /Mark complete/ })).not.toBeInTheDocument();
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

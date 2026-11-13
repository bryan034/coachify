import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { PlannedRoadmap, Workspace, PlannerConfig } from './types';
import { blankPlanner, blockedRunway, config, planner, review, roadmap, runway, workspace } from '../../../tests/fixtures/roadmap-workspace';

const session = vi.hoisted(() => ({ account: { id: 'owner-one' }, token: 'synthetic-token' }));
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => session }));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: api, RoadmapError: class extends Error { status = 503; } }));
// The planner shows the Skills Profile's own counts, not its evidence list (which repeats a skill per source).
const evaluationApi = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api/assessment', async original => ({ ...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: evaluationApi }));
const evaluationStatus = { freshness: 'current', processing: 'idle', completeness: 'complete', evaluated_at: '2030-01-09T00:00:00Z', reasons: [] } as const;
beforeEach(() => evaluationApi.mockImplementation(async path => path === '/context' ? { ready: true, model_available: true, cv_reviewed: true, input_hash: 'hash1' } : { version: 0, stale: false, ready: true, result: null, operation: null, issues: [], evaluation: evaluationStatus }));
const profileSkills = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api/workspace-summary', async importOriginal => ({ ...await importOriginal<typeof import('@/lib/api/workspace-summary')>(), loadSkills: profileSkills }));
beforeEach(() => profileSkills.mockResolvedValue({ total: 1, experiences: 1, groups: [{ name: 'Technical coding', count: 1, skills: ['Git'] }] }));

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
const openHelper = async () => { await screen.findByRole('heading', { name: 'Roadmap' }); if (!screen.queryByRole('button', { name: /(Start|Continue with) chat helper/ })) { const settings = await screen.findByRole('button', { name: /Plan settings/ }); fireEvent.click(settings); } fireEvent.click(await screen.findByRole('button', { name: /(Start|Continue with) chat helper/ })); };
beforeEach(() => { api.mockReset(); window.history.replaceState({}, '', '/roadmap'); });

it('asks for the device time zone so unsaved settings use local dates', async () => {
 serve(workspace()); render(<RoadmapPlanner />); await screen.findByRole('heading', { name: 'Your runway' });
 expect(api.mock.calls[0][0]).toMatch(/^\/workspace\?time_zone=/);
});

it('shows the goal and skills that will be used before any generation', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const heading = await screen.findByRole('heading', { name: 'What elo will use' });
 const section = heading.closest('section')!;
 expect(within(section).getByText('Backend developer')).toBeVisible();
 expect(await within(section).findByText(/1 skill, 1 experience/)).toBeVisible();
 expect(within(section).queryByText('Git')).not.toBeInTheDocument();
 fireEvent.click(within(section).getByRole('button', { name: /1 skill, 1 experience/ }));
 expect(within(section).getByText('Git')).toBeVisible();
 expect(calls('/planner/generate')).toHaveLength(0);
});

it('counts skills the same way as the Skills Profile, not once per evidence source', async () => {
 profileSkills.mockResolvedValue({ total: 34, experiences: 15, groups: [{ name: 'Technical coding', count: 1, skills: ['Python'] }] });
 serve(workspace()); render(<RoadmapPlanner />);
 const section = (await screen.findByRole('heading', { name: 'What elo will use' })).closest('section')!;
 expect(await within(section).findByRole('button', { name: 'Skills profile · 34 skills, 15 experiences' })).toBeVisible();
});

it('closes a What elo will use panel with Escape, returning focus, and with a click elsewhere', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const section = (await screen.findByRole('heading', { name: 'What elo will use' })).closest('section')!;
 const menu = await within(section).findByRole('button', { name: /1 skill, 1 experience/ });
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

it('hides generation and links to the missing CV or Career goal', async () => {
 const state = workspace(); state.context.ready = false; state.context.issues = [{ source: 'career', message: 'Extract and review a Career goal first.', href: '/career-goal' }];
 serve(state); render(<RoadmapPlanner />); await screen.findByRole('heading', { name: 'Finish these first' });
 expect(screen.queryByRole('button', { name: 'Generate roadmap' })).toBeNull();
 expect(screen.getByRole('link', { name: 'Open Career Goal' })).toHaveAttribute('href', '/career-goal');
});

it('sets the runway from the finish date and shows its length as display-only text', async () => {
 serve(workspace(), { '/planner/runway': (body: { config: { target_date: string } }) => runway({ resolved: { today: '2030-01-09', start_date: '2030-01-09', target_date: body.config.target_date, matched_duration: null }, calendar: { days: 168, weeks: 24, extra_days: 0, label: '24 weeks', partial_first_week: false } }) });
 render(<RoadmapPlanner />);
 const finish = await screen.findByRole('group', { name: 'Finish' });
 expect(within(finish).queryByRole('spinbutton')).toBeNull();
 fireEvent.change(screen.getByLabelText('Target date'), { target: { value: '2030-06-26' } });
 await waitFor(() => expect(calls('/planner/runway').at(-1)![2].config).toMatchObject({ duration: null, target_date: '2030-06-26' }));
 await waitFor(() => expect(within(finish).getByLabelText('Duration')).toHaveTextContent('24 weeks (5 months + 2 weeks)'));
});

it('shows calculated runway with the extra capacity from backup blocks', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const runwaySection = await screen.findByRole('region', { name: 'Your runway' });
 expect(within(runwaySection).getByText('2 weeks, 5 days')).toBeVisible();
 expect(within(runwaySection).getAllByText('11 hours 30 minutes')).toHaveLength(2);
 expect(within(runwaySection).getByText('+2 hours (not enabled)')).toBeVisible();
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

it('says how long a target date is when it is not a whole number of weeks', async () => {
 serve(workspace()); render(<RoadmapPlanner />);
 const finish = await screen.findByRole('group', { name: 'Finish' });
 expect(within(finish).getByLabelText('Duration')).toHaveTextContent('2 weeks, 5 days');
 expect(within(finish).queryByRole('spinbutton', { name: 'Duration length' })).toBeNull();
});

it('writes settings into the sentence and flags a start date in the past', async () => {
 serve(workspace({ planner: planner({ runway: runway({ can_generate: false, issues: [{ code: 'start_in_past', message: 'Choose a start date of today or later.' }] }) }) })); render(<RoadmapPlanner />);
 const start = await screen.findByRole('group', { name: 'Start' });
 expect(within(start).getByText('Wed, 9 Jan 2030')).toBeVisible();
 expect(start.querySelector('.token')).toHaveClass('warn');
 expect(screen.getByRole('spinbutton', { name: 'Weekly budget in hours' })).toHaveValue(5);
 fireEvent.click(screen.getByRole('checkbox', { name: 'Allow backup blocks when preferred time runs out' }));
 expect(within(screen.getByRole('group', { name: 'Backup blocks' })).getByText('allowed')).toBeVisible();
});

it('offers learning focus themes from the Skills Profile and adds a study block from the week', async () => {
 serve(workspace({ planner: planner({ config: config({ learning_focus: [], learning_notes: '' }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Choose learning focus' }));
 expect(screen.queryByRole('checkbox', { name: 'Certification' })).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('checkbox', { name: 'Tools' }));
 expect(within(screen.getByRole('group', { name: 'Learning focus' })).getByRole('button', { name: 'Choose learning focus' })).toHaveTextContent('Tools');
 fireEvent.click(screen.getByRole('button', { name: 'Add study block on Tuesday' }));
 expect(screen.getByRole('combobox', { name: 'Block 4 day' })).toHaveValue('1');
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.learning_topics).toEqual(['Tools']));
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
 await screen.findByRole('navigation', { name: 'Roadmap views' });
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
 fireEvent.click(await screen.findByRole('button', { name: 'Add blocked-out time' }));
 const rule = screen.getByRole('group', { name: 'Blackout 1' });
 expect(within(rule).getByText('Every week on Mon, 18:00–20:00, from Wed, 9 Jan 2030')).toBeVisible();
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
 expect(within(rule).getByText('Every 2 weeks on Wed, Fri, 12:00–20:00, from Wed, 9 Jan 2030 until Sun, 27 Jan 2030')).toBeVisible();
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([{ frequency: 'weekly', start_date: '2030-01-09', end_date: '2030-01-27', interval: 2, weekdays: [2, 4], start_time: '12:00', end_time: '20:00' }]));
});

it('offers daily, monthly and one-day blocked times, keeping only the fields each one uses', async () => {
 serve(workspace({ planner: planner({ config: config({ blackouts: [] }) }) })); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Add blocked-out time' }));
 const rule = screen.getByRole('group', { name: 'Blackout 1' });
 fireEvent.click(within(rule).getByRole('checkbox', { name: 'Blackout 1 all day' }));
 const repeats = within(rule).getByRole('combobox', { name: 'Blackout 1 repeats' });
 fireEvent.change(repeats, { target: { value: 'monthly' } });
 fireEvent.change(within(rule).getByLabelText('Blackout 1 start date'), { target: { value: '2030-01-31' } });
 expect(within(rule).getByText('Every month on day 31 or the month’s last day, all day, from Thu, 31 Jan 2030')).toBeVisible();
 expect(within(rule).queryByRole('checkbox', { name: 'Blackout 1 on Monday' })).not.toBeInTheDocument();
 fireEvent.change(repeats, { target: { value: 'daily' } });
 expect(within(rule).getByText('Every day, all day, from Thu, 31 Jan 2030')).toBeVisible();
 fireEvent.change(within(rule).getByLabelText('Blackout 1 end date'), { target: { value: '2030-02-02' } });
 fireEvent.change(repeats, { target: { value: 'once' } });
 expect(within(rule).getByText('Thu, 31 Jan 2030, all day')).toBeVisible();
 expect(within(rule).queryByLabelText('Blackout 1 end date')).not.toBeInTheDocument();
 expect(document.querySelector('.block-others .blocked')).toHaveTextContent('Thu, 31 Jan 2030');
 await waitFor(() => expect(calls('/planner/runway').at(-1)?.[2].config.blackouts).toEqual([{ frequency: 'once', start_date: '2030-01-31', end_date: null, interval: 1, weekdays: [], start_time: null, end_time: null }]));
 fireEvent.click(within(rule).getByRole('button', { name: 'Remove blackout 1' }));
 expect(screen.queryByRole('group', { name: 'Blackout 1' })).not.toBeInTheDocument();
});

it('shows the backend explanation for a blackout that cannot apply and blocks generation', async () => {
 serve(workspace(), { '/planner/runway': () => runway({ can_generate: false, issues: [{ code: 'blackout_invalid', message: 'Blackout 1 must end after it starts on the same day.' }] }) });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: /Edit blocked time: Sat, 12 Jan 2030/ }));
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

it('reviews the first scheduled week, milestone summary and experience questions', async () => {
 serve(withCandidate()); render(<RoadmapPlanner />);
 const preview = await screen.findByRole('region', { name: 'Plan preview' });
 expect(within(preview).getByRole('button', { name: 'Accept plan' })).toBeEnabled();
 expect(screen.getByRole('region', { name: 'Your first week' })).toHaveTextContent('Write one tested Python endpoint.');
 expect(screen.getByRole('complementary', { name: 'Milestones in this plan' })).toHaveTextContent('Build a Python API');
 expect(screen.getByText('By your target you can show a basic API, but not advanced Python.')).toBeVisible();
 expect(screen.getByRole('group', { name: 'Have you run a service in Docker?' })).toBeVisible();
});

it('returns to configuration without losing the preview and can go back', async () => {
 serve(withCandidate()); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Back to settings' }));
 await screen.findByRole('heading', { name: 'Your runway' });
 expect(calls('/planner/discard')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Return to roadmap' }));
 await screen.findByRole('button', { name: 'Accept plan' });
});

it('stays in configuration when saving settings returns the same preview', async () => {
 const state = withCandidate();
 serve(state, { '/planner/config': () => ({ ...state, version: state.version + 1 }) });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Back to settings' }));
 fireEvent.change(await screen.findByLabelText('Preferred session in minutes'), { target: { value: '45' } });
 await waitFor(() => expect(calls('/planner/config')).toHaveLength(1), { timeout: 3000 });
 expect(await screen.findByText('All changes saved')).toBeVisible();
 expect(screen.queryByRole('button', { name: 'Save settings' })).not.toBeInTheDocument();
 expect(screen.getByRole('heading', { name: 'Your runway' })).toBeVisible();
 expect(calls('/planner/discard')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Return to roadmap' }));
 expect(await screen.findByRole('button', { name: 'Accept plan' })).toBeVisible();
});

it('shows reached milestone stops and the route to the goal', async () => {
 const base = roadmap().milestones[0];
 const plan = roadmap({ milestones: [{ ...base, outcome: { demonstrated: true, note: 'Shown.' } }, { ...base, id: 'm2', key: 'm2', title: 'Second' }] });
 serve(withActive(plan)); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Milestones' }));
 const route = screen.getByRole('region', { name: 'Your route to Backend developer' });
 expect(route).toHaveTextContent('1 of 2 milestones reached');
 expect(route.querySelectorAll('.stop')).toHaveLength(3);
 expect(route.querySelectorAll('.rv-stop.reached')).toHaveLength(2);
});

it('accepts a preview and explains when it cannot be accepted', async () => {
 const accepted = withActive();
 serve(withCandidate(), { '/planner/accept': () => accepted }); const view = render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Accept plan' }));
 await screen.findByRole('navigation', { name: 'Roadmap views' }); expect(calls('/planner/accept')).toHaveLength(1);
 view.unmount(); api.mockReset();
 serve(withCandidate(roadmap(), { candidate_blockers: [{ code: 'settings_changed', message: 'Your settings changed after this preview was prepared. Generate a fresh plan.' }] })); render(<RoadmapPlanner />);
 await screen.findByText('Your settings changed after this preview was prepared. Generate a fresh plan.');
 expect(screen.getByRole('button', { name: 'Accept plan' })).toBeDisabled();
});

const taskName = 'Mark done: Write one tested Python endpoint.';
const completed = (note: string | null) => { const plan = roadmap(); return roadmap({ assignments: [{ ...plan.assignments[0], status: 'completed', completed_at: '2030-01-09T12:00:00+00:00', evidence_note: note }] }); };

it('ticks a session off the to-do list, then adds what was produced, separately from proficiency', async () => {
 serve(withActive(), { '/planner/tasks/status': () => withActive(completed(null)) }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: taskName }));
 await screen.findByRole('button', { name: 'Mark not done: Write one tested Python endpoint.' });
 expect(calls('/planner/tasks/status')[0][2]).toMatchObject({ task_id: 'a1', status: 'completed' });
 expect(screen.getByText('Ticking records what you did. It doesn’t change your assessed skills.')).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Write one tested Python endpoint.' }));
 expect(screen.getByRole('textbox', { name: 'Notes for Write one tested Python endpoint.' })).toBeVisible();
});

it('shows a tick at once and undoes it when saving fails', async () => {
 let fail: (reason: Error) => void = () => {};
 serve(withActive(), { '/planner/tasks/status': () => new Promise((_, reject) => { fail = reject; }) }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: taskName }));
 expect(screen.getByRole('button', { name: 'Mark not done: Write one tested Python endpoint.' })).toHaveAttribute('aria-pressed', 'true');
 await act(async () => { fail(new Error('Your plan could not be saved.')); });
 expect(await screen.findByRole('alert')).toHaveTextContent('Your plan could not be saved.');
 expect(screen.getByRole('button', { name: taskName })).not.toHaveAttribute('aria-pressed', 'true');
});

it('reopens a ticked session', async () => {
 serve(withActive(completed('Done.')), { '/planner/tasks/status': () => withActive() }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Mark not done: Write one tested Python endpoint.' }));
 await waitFor(() => expect(calls('/planner/tasks/status')[0][2]).toMatchObject({ task_id: 'a1', status: 'not_started' }));
 expect(await screen.findByRole('button', { name: taskName })).toHaveAttribute('aria-pressed', 'false');
});

const toDoPlan = () => { const base = roadmap(); const session = base.assignments[0]; return roadmap({ assignments: [session, { ...session, id: 'a2', key: 'a2', date: '2030-01-11', start_time: '18:00', task: 'Add input validation.' }, { ...session, id: 'a3', key: 'a3', date: '2030-01-08', start_time: '18:00', task: 'Read the framework guide.', status: 'completed', completed_at: 'x', evidence_note: 'Notes taken.' }] }); };

it('opens on Today and shows each session and skill in Week', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 await screen.findByRole('button', { name: taskName });
 fireEvent.click(screen.getByRole('button', { name: 'Week' }));
 const list = screen.getByRole('region', { name: /This week/ });
 expect(within(list).getByText('Write one tested Python endpoint.')).toBeVisible();
 expect(within(list).getByText('Add input validation.')).toBeVisible();
 expect(within(list).getAllByText('Python').length).toBeGreaterThan(1);
});

it('switches to one day at a time and can pick another day', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 await screen.findByRole('button', { name: taskName });
 fireEvent.click(screen.getByRole('button', { name: 'Next day' }));
 expect(screen.queryByRole('button', { name: taskName })).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Next day' }));
 expect(screen.getByRole('button', { name: 'Mark done: Add input validation.' })).toBeVisible();
 expect(window.location.search).toContain('date=2030-01-11');
});

it('opens a calendar day from Month in Today', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Month' }));
 expect(screen.getByRole('heading', { name: 'January 2030' })).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Open Fri, 11 Jan 2030 in Today' }));
 expect(screen.getByRole('button', { name: 'Mark done: Add input validation.' })).toBeVisible();
});

it('stops the to-do list moving past the plan and offers a way back to today', async () => {
 serve(withActive()); render(<RoadmapPlanner />);
 await screen.findByRole('button', { name: taskName });
 expect(screen.getByRole('button', { name: 'Previous day' })).toBeDisabled();
 fireEvent.click(screen.getByRole('button', { name: 'Week' }));
 expect(screen.getByRole('button', { name: 'Previous week' })).toBeDisabled();
 fireEvent.click(screen.getByRole('button', { name: 'Next week' }));
 fireEvent.click(screen.getByRole('button', { name: 'Next week' }));
 expect(screen.getByRole('button', { name: 'Next week' })).toBeDisabled();
 fireEvent.click(screen.getByRole('button', { name: 'Today' }));
 expect(screen.getByRole('button', { name: taskName })).toBeVisible();
});

it('shows each skill the plan builds with its sessions', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Milestones' }));
 expect(screen.getByRole('region', { name: 'Skills these build' })).toHaveTextContent('Python');
});

it('does not let a preview be ticked off', async () => {
 serve(withCandidate()); render(<RoadmapPlanner />);
 await screen.findByRole('region', { name: 'Your first week' });
 expect(screen.queryByRole('button', { name: /Mark done/ })).not.toBeInTheDocument();
 expect(screen.getByText('Accept the plan to start ticking these off.')).toBeVisible();
});

it('records a demonstrated outcome with a note', async () => {
 serve(withActive(), { '/planner/milestones/outcome': () => withActive() }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Milestones' }));
 fireEvent.click(screen.getByRole('button', { name: 'Record how you showed it' }));
 expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
 fireEvent.change(screen.getByRole('textbox', { name: /How did you show/ }), { target: { value: 'Showed a mentor.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save' }));
 await waitFor(() => expect(calls('/planner/milestones/outcome')[0][2]).toMatchObject({ milestone_id: 'm1', demonstrated: true, note: 'Showed a mentor.' }));
});

it('asks experience questions and offers to regenerate once answered', async () => {
 const answered = withCandidate(roadmap(), { confirmations: { docker: { answer: 'no_experience' } }, signals: [{ kind: 'evidence', message: 'You answered experience questions after this plan was prepared.' }] });
 serve(withCandidate(), { '/planner/confirmations': () => answered, '/planner/generate': () => ({ version: 3, operation: null }) }); render(<RoadmapPlanner />);
 fireEvent.click(within(await screen.findByRole('group', { name: 'Have you run a service in Docker?' })).getByRole('radio', { name: 'No' }));
 fireEvent.click(screen.getByRole('button', { name: 'Back to settings' }));
 await screen.findByRole('button', { name: 'Generate roadmap' });
 expect(calls('/planner/confirmations')[0][2]).toMatchObject({ gap_id: 'docker', answer: 'no_experience' });
 fireEvent.click(screen.getByRole('button', { name: 'Generate roadmap' }));
 await waitFor(() => expect(calls('/planner/generate')).toHaveLength(1));
});

it('shows what a revision changes, keeps completed work and applies only on accept', async () => {
 const active = completed('Done.');
 const revised = roadmap({ id: 'new', base_active_id: active.id, changes: { completed_preserved: 1, assignments_added: ['Add validation'], assignments_moved: [], assignments_removed: [], milestones_added: [], milestones_moved: [], milestones_removed: [] } });
 serve(workspace({ planner: planner({ active, active_review: review(active), candidate: revised, candidate_review: review(revised) }) }), { '/planner/discard': () => withActive(active) });
 render(<RoadmapPlanner />);
 await screen.findByText('What changes from your current plan');
 expect(screen.getByText('completed session stays as recorded')).toBeVisible();
 expect(screen.getByText('Add validation')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
 await screen.findByRole('navigation', { name: 'Roadmap views' });
 expect(calls('/planner/accept')).toHaveLength(0);
});

it('offers an updated preview when settings, progress or evidence change', async () => {
 serve(withActive(roadmap(), { signals: [{ kind: 'settings', message: 'Your study settings changed since this roadmap was accepted.' }] }), { '/planner/generate': () => ({ version: 3, operation: null }) });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: /Plan settings/ }));
 await screen.findByText('Your study settings changed since this roadmap was accepted.');
 fireEvent.click(screen.getByRole('button', { name: 'Preview updated roadmap' }));
 await waitFor(() => expect(calls('/planner/generate')).toHaveLength(1));
});

it.each(['CV', 'career goal'])('replaces source notices with a roadmap banner after the %s changes', async source => {
 const state = withActive(roadmap(), { signals: [{ kind: 'evidence', message: 'Your CV, skills or Career goal changed since this roadmap was prepared.' }] });
 state.context.input_hash = `${source}-changed`;
 const freshPlan = roadmap({ id: 'fresh-preview', assessment_hash: state.context.input_hash });
 const fresh = withCandidate(freshPlan, { active: state.planner.active });
 fresh.context.input_hash = state.context.input_hash;
 serve(state, { '/planner/generate': () => fresh });
 render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: /Plan settings/ }));
 expect(await screen.findByRole('heading', { name: 'Your roadmap is out of date' })).toBeVisible();
 expect(screen.queryByText('Your CV, skills or Career goal changed since this roadmap was prepared.')).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Preview updated roadmap' })).toBeEnabled();
 expect(calls('/planner/generate')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', { name: 'Regenerate roadmap' }));
 await screen.findByText('Preview · not active until you accept it');
 expect(calls('/planner/generate')).toHaveLength(1);
 expect(screen.queryByRole('heading', { name: 'Your roadmap is out of date' })).not.toBeInTheDocument();
 expect(calls('/planner/accept')).toHaveLength(0);
});

it('replaces an outdated preview source blocker while keeping acceptance blocked', async () => {
 const state = withCandidate(roadmap(), { candidate_blockers: [{ code: 'inputs_changed', message: 'Your CV or Career goal changed after this preview was prepared. Generate a fresh plan.' }] });
 state.context.input_hash = 'new-inputs';
 serve(state); render(<RoadmapPlanner />);
 expect(await screen.findByRole('button', { name: 'Regenerate roadmap' })).toBeEnabled();
 expect(screen.getByRole('button', { name: 'Accept plan' })).toBeDisabled();
 expect(screen.queryByText('Your CV or Career goal changed after this preview was prepared. Generate a fresh plan.')).not.toBeInTheDocument();
});

it('disables banner regeneration when the latest inputs are not ready', async () => {
 const state = withActive(); state.context = { ...state.context, input_hash: 'new-inputs', ready: false };
 serve(state); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: /Plan settings/ }));
 expect(await screen.findByRole('button', { name: 'Regenerate roadmap' })).toBeDisabled();
 expect(calls('/planner/generate')).toHaveLength(0);
});

it('keeps the outdated banner hidden for a current roadmap', async () => {
 const state = withActive(); state.context.input_hash = state.planner.active!.assessment_hash;
 serve(state); render(<RoadmapPlanner />);
 await screen.findByRole('navigation', { name: 'Roadmap views' });
 expect(screen.queryByRole('heading', { name: 'Your roadmap is out of date' })).not.toBeInTheDocument();
});

it('keeps the plan and offers an exact retry when generation fails', async () => {
 const retry = { expected_version: 2, mutation_id: 'failed-one', allow_partial_assessment: false };
 const state = withActive(roadmap(), { retry_generate: retry }); state.operation = { id: 'failed-one', status: 'failed', stage: 'failed', error: { code: 'plan_validation', detail: 'We could not produce a plan that fits your schedule after 3 attempts. Your last valid plan is unchanged.' } };
 serve(state, { '/planner/generate': () => ({ version: 3, operation: null }) }); render(<RoadmapPlanner />);
 await screen.findByText(/Your last valid plan is unchanged/);
 expect(screen.getByRole('heading', { name: 'Roadmap' })).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
 await waitFor(() => expect(calls('/planner/generate')[0][2]).toEqual(retry));
});

it('opens the chat helper through Plan settings to request edits', async () => {
 serve(withActive(), { '/messages': () => ({ version: 2, operation: null }) }); render(<RoadmapPlanner />);
 await openHelper();
 expect(screen.queryByRole('tab', { name: 'Chat' })).not.toBeInTheDocument();
 expect(screen.getByRole('heading', { name: 'Roadmap' })).toBeVisible();
 const box = screen.getByRole('textbox', { name: 'Ask for a change' });
 expect(box).toBeVisible(); expect(screen.getByText('Changes appear as a preview first.')).toBeVisible();
 fireEvent.change(box, { target: { value: 'Move Wednesday to Thursday.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
 await waitFor(() => expect(calls('/messages')[0][2]).toMatchObject({ message: 'Move Wednesday to Thursday.' }));
});

it('labels partial research in the settings helper while allowing a plan change', async () => {
 const state = withActive(); state.context.research_coverage = 'unavailable';
 serve(state); render(<RoadmapPlanner />); await openHelper();
 fireEvent.change(screen.getByRole('textbox', { name: 'Ask for a change' }), { target: { value: 'Move it.' } });
 expect(screen.getAllByText(/Using available evidence/).length).toBeGreaterThan(0);
 expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
});

it('a new preview from settings chat opens outside the active roadmap views', async () => {
 let state = withActive();
 api.mockImplementation((path: string) => path === '/messages' ? Promise.resolve({ version: 2, operation: null }) : Promise.resolve(state));
 render(<RoadmapPlanner />);
 await openHelper();
 fireEvent.change(screen.getByRole('textbox', { name: 'Ask for a change' }), { target: { value: 'Move it.' } });
 const preview = roadmap({ id: 'preview', base_active_id: 'plan1' }); state = workspace({ planner: planner({ active: roadmap(), active_review: review(), candidate: preview, candidate_review: review(preview) }) });
 await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
 await screen.findByText('Preview · not active until you accept it');
 expect(screen.queryByRole('tab')).not.toBeInTheDocument();
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


it('requires an explicit evaluation update before generating from outdated skills', async () => {
 const outdated = { ...evaluationStatus, freshness: 'outdated' as const, reasons: ['goal_changed'] };
 let running = false;
 evaluationApi.mockImplementation(async (path, _token, body) => {
  if (path === '/context') return { ready: true, model_available: true, cv_reviewed: true, input_hash: 'new' };
  if (body) { running = true; return {}; }
  return { version: 3, stale: true, result: null, ready: true, issues: [], operation: running ? { status: 'running' } : null,
   evaluation: { ...outdated, processing: running ? 'evaluating' : 'idle' } };
 });
 const state = workspace(); state.context.evaluation = outdated;
 serve(state); render(<RoadmapPlanner />);
 expect(await screen.findByText('Skill evaluation: Outdated')).toBeVisible();
 expect(screen.getByText('Your career goal changed.')).toBeVisible();
 expect(screen.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
 expect(evaluationApi.mock.calls.every(call => call[2] === undefined)).toBe(true);
 fireEvent.click(screen.getByRole('button', { name: 'Update evaluation' }));
 await waitFor(() => expect(evaluationApi.mock.calls.filter(call => call[0] === '' && call[2])).toHaveLength(1));
 expect(calls('/planner/generate')).toHaveLength(0);
 expect(await screen.findByText(/Skill evaluation: Outdated/)).toBeVisible();
});

it('adds an anytime task from Today with the saved workspace version', async () => {
 serve(withActive(), { '/planner/sessions/add': () => withActive() }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'New task' }));
 const form = screen.getByRole('group', { name: 'New task' });
 fireEvent.change(within(form).getByRole('textbox', { name: 'Task' }), { target: { value: 'Review API tests' } });
 fireEvent.change(within(form).getByRole('textbox', { name: 'Done when' }), { target: { value: 'All tests pass' } });
 fireEvent.click(within(form).getByRole('button', { name: 'Anytime' }));
 fireEvent.click(within(form).getByRole('button', { name: 'Add task' }));
 await waitFor(() => expect(calls('/planner/sessions/add')[0][2]).toMatchObject({ expected_version: 0, session: { title: 'Review API tests', completion_criterion: 'All tests pass', date: '2030-01-09', start_time: null, duration_minutes: 30 } }));
});

it('records a generated checkpoint without recording the milestone outcome', async () => {
 const base = roadmap();
 const plan = roadmap({ milestones: [{ ...base.milestones[0], checkpoints: [{ key: 'runs', title: 'The API runs locally', date: '2030-01-10', reached_at: null }] }] });
 serve(withActive(plan), { '/planner/milestones/checkpoint': () => withActive(plan) }); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Milestones' }));
 fireEvent.click(screen.getByRole('button', { name: 'Mark reached: The API runs locally' }));
 await waitFor(() => expect(calls('/planner/milestones/checkpoint')[0][2]).toMatchObject({ milestone_id: 'm1', checkpoint_key: 'runs', reached: true, expected_version: 0 }));
 expect(calls('/planner/milestones/outcome')).toHaveLength(0);
});

it('switches progress measures without making a model request', async () => {
 serve(withActive(toDoPlan())); render(<RoadmapPlanner />);
 fireEvent.click(await screen.findByRole('button', { name: 'Progress' }));
 expect(screen.getByRole('img', { name: /^Tasks by day this week:/ })).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Hours' }));
 fireEvent.click(screen.getByRole('button', { name: 'By week' }));
 expect(screen.getByRole('img', { name: /^Hours by week:/ })).toBeVisible();
 expect(calls('/planner/generate')).toHaveLength(0);
});

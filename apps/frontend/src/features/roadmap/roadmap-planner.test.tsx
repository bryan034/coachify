import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner, generationProgress } from './roadmap-planner';
import type { Workspace } from './types';
import { planner, review, roadmap, runway } from '../../../tests/fixtures/roadmap-workspace';
const session = vi.hoisted(() => ({ account: { id: 'owner-one' }, token: 'synthetic-token' }));
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => session }));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: api, RoadmapError: class extends Error { status = 503; } }));
vi.mock('@/lib/api/assessment', async original => ({ ...await original<typeof import('@/lib/api/assessment')>(),
 assessmentApi: vi.fn(async path => path === '/context' ? { ready: true, model_available: true, cv_reviewed: true } : {
  version: 0, stale: false, result: null, operation: null, ready: true, issues: [],
  evaluation: { freshness: 'current', processing: 'idle', completeness: 'complete', evaluated_at: null, reasons: [] },
 }) }));
function state(overrides: Partial<Workspace> = {}): Workspace { return { planner: planner(), version: 0, messages: [], operation: null, active: null, draft: null, assessment: null, stale: false,
 context: { ready: true, issues: [], model_available: true, research_coverage: 'no_findings', goal: { role: 'Developer', target_type: 'specific_job' }, cv: { id: 'cv-one', name: 'synthetic.docx' }, planning_defaults: { application_date: null, weekly_hours: 6, availability_periods: [] } }, ...overrides }; }
const openHelper = async () => fireEvent.click(await screen.findByRole('button', { name: /(Start|Continue with) chat helper/ }));
beforeEach(() => { api.mockReset(); session.account = { id: 'owner-one' }; session.token = 'synthetic-token'; });
it('shows why the workspace failed to load and recovers on retry', async () => {
 api.mockRejectedValueOnce(new Error('Your plan could not be loaded or saved. Retry to recover your saved work.')).mockResolvedValue(state());
 render(<RoadmapPlanner />);
 expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded');
 fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }));
 await screen.findByRole('button', { name: /(Start|Continue with) chat helper/ });
 expect(screen.queryByRole('alert')).toBeNull();
});
it('gates missing CV and goal without making model requests', async () => {
 const value = state(); value.context.ready = false; value.context.issues = [{ source: 'cv', message: 'Select an extracted CV.', href: '/cv' }]; api.mockResolvedValue(value);
 render(<RoadmapPlanner />); await screen.findByText('Select an extracted CV.');
 expect(screen.getByRole('link', { name: 'Open CV' })).toHaveAttribute('href', '/cv');
 expect(screen.getByText('Your Career goal is set.')).toBeInTheDocument();
 expect(screen.queryByRole('button', { name: /chat helper/ })).toBeNull(); expect(screen.queryByRole('button', { name: 'Generate roadmap' })).toBeNull(); expect(api).toHaveBeenCalledTimes(1);
});
it('sends the chat helper message on Enter but keeps Shift+Enter for a new line', async () => {
 api.mockImplementation((path: string) => path === '/messages' ? new Promise(() => {}) : Promise.resolve(state()));
 render(<RoadmapPlanner />); await openHelper(); const input = await screen.findByRole('textbox', { name: 'Answer here' });
 fireEvent.change(input, { target: { value: 'I have six hours a week.' } });
 fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
 expect(api.mock.calls.some(call => call[0] === '/messages')).toBe(false);
 fireEvent.keyDown(input, { key: 'Enter' });
 await waitFor(() => expect(api.mock.calls.find(call => call[0] === '/messages')?.[2]).toMatchObject({ message: 'I have six hours a week.' }));
});
it('retains the next draft during async advice and sends the exact chosen partial flag', async () => {
 let resolveSend: (value: unknown) => void = () => {};
 api.mockImplementation((path: string) => path === '/messages' ? new Promise(resolve => { resolveSend = resolve; }) : Promise.resolve(state()));
 render(<RoadmapPlanner />); await openHelper(); const input = await screen.findByRole('textbox', { name: 'Answer here' });
 fireEvent.change(input, { target: { value: 'I have six hours a week.' } }); fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
 await waitFor(() => expect(input).toHaveValue('')); fireEvent.change(input, { target: { value: 'Keep Saturday free.' } });
 await act(async () => resolveSend({ version: 1, operation: { id: 'saved', status: 'pending' } }));
 await waitFor(() => expect(input).toHaveValue('Keep Saturday free.'));
 expect(api.mock.calls.find(call => call[0] === '/messages')?.[2]).toMatchObject({ message: 'I have six hours a week.', allow_partial_assessment: true });
});
it('labels incomplete research without blocking generation', async () => {
 const value = state(); value.context.research_coverage = 'unavailable'; api.mockResolvedValue(value); render(<RoadmapPlanner />);
 const generate = await screen.findByRole('button', { name: 'Generate roadmap' });
 expect(generate).toBeEnabled(); expect(screen.getByText(/Using available evidence/)).toBeVisible();
 expect(screen.queryByRole('checkbox',{name:/Continue with available evidence/})).not.toBeInTheDocument();
 // Filling in the planner runs no comparison, so the helper needs no choice until a plan exists.
 await openHelper(); fireEvent.change(screen.getByRole('textbox', { name: 'Answer here' }), { target: { value: 'Help me plan.' } });
 expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
});
it('clears private conversation and ignores old responses on account switch', async () => {
 let oldResponse: (value: Workspace) => void = () => {};
 api.mockImplementationOnce(() => new Promise(resolve => { oldResponse = resolve; })).mockResolvedValue(state());
 const view = render(<RoadmapPlanner />); session.account = { id: 'owner-two' }; session.token = 'second-token'; view.rerender(<RoadmapPlanner />);
 await openHelper(); await screen.findByRole('heading', { name: 'Plan helper' });
 await act(async () => oldResponse(state({ messages: [{ id: 'private', role: 'user', content: 'Private old-owner plans', created_at: '2030-01-01' }] })));
 expect(screen.queryByText('Private old-owner plans')).not.toBeInTheDocument();
});
it('retries a lost-response message using its original mutation identity', async () => {
 let failed = true;
 api.mockImplementation((path: string) => path === '/messages' ? failed ? Promise.reject(new Error('Connection lost.')) : Promise.resolve({ version: 1, operation: null }) : Promise.resolve(state()));
 render(<RoadmapPlanner />); await openHelper(); fireEvent.change(await screen.findByRole('textbox', { name: 'Answer here' }), { target: { value: 'Plan my week.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Send message' })); await screen.findByText('Connection lost.');
 const original = api.mock.calls.find(call => call[0] === '/messages')![2]; failed = false;
 fireEvent.click(screen.getByRole('button', { name: 'Recover sent message' }));
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '/messages')).toHaveLength(2));
 expect(api.mock.calls.filter(call => call[0] === '/messages')[1][2]).toEqual(original);
});

it('has no Starting point tab or panel, before or after a roadmap exists', async () => {
 api.mockResolvedValue(state()); const first = render(<RoadmapPlanner />);
 await screen.findByRole('heading', { name: 'Roadmap' });
 expect(screen.queryByRole('tab')).not.toBeInTheDocument(); expect(screen.queryByText('Your starting point')).not.toBeInTheDocument();
 first.unmount();
 const value = state(); const plan = roadmap(); value.planner = planner({ active: plan, active_review: review(plan) });
 api.mockResolvedValue(value); render(<RoadmapPlanner />);
 await screen.findByRole('navigation', { name: 'Roadmap views' });
 expect(screen.queryByRole('tab', { name: 'Starting point' })).not.toBeInTheDocument();
});

it('shows a generation progress bar from the click and moves it with the reported stage', async () => {
 let finish: (value: unknown) => void = () => {};
 const value = state(); value.planner = planner({ runway: runway({ can_generate: true }) });
 api.mockImplementation((path: string) => path === '/generate' ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(value));
 render(<RoadmapPlanner />);
 const button = await screen.findByRole('button', { name: /^Generate roadmap/ });
 fireEvent.click(button);
 const bar = await screen.findByRole('progressbar', { name: 'Starting: saving your settings' });
 expect(bar).toHaveAttribute('aria-valuenow', String(generationProgress().percent));
 expect(generationProgress('assessing')).toMatchObject({ step: 1, percent: 30 });
 expect(generationProgress('writing')).toMatchObject({ step: 2, percent: 65 });
 expect(generationProgress('correcting')).toMatchObject({ step: 3, percent: 88 });
 expect(generationProgress('anything-else')).toMatchObject({ step: 0, percent: 8 });
 await act(async () => finish({ version: 1, operation: { id: 'op', status: 'running', stage: 'writing' } }));
});

it('distinguishes an unavailable source check from missing input and retains saved chat', async () => {
 const value = state({ messages: [{ id: 'saved', role: 'assistant', content: 'Your saved advice remains here.', created_at: '2030-01-01' }] });
 value.context.ready = false; value.context.availability = 'unavailable'; api.mockResolvedValue(value);
 render(<RoadmapPlanner />); await openHelper(); await screen.findByText('Your saved advice remains here.');
 expect(screen.getByRole('button', { name: 'Retry source check' })).toBeVisible();
 expect(screen.queryByText('Bring your starting point and direction')).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
});

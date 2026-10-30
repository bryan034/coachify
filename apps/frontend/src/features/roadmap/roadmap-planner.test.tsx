import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { Workspace } from './types';
const session = vi.hoisted(() => ({ account: { id: 'owner-one' }, token: 'synthetic-token' }));
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => session }));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: api, RoadmapError: class extends Error { status = 503; } }));
function state(overrides: Partial<Workspace> = {}): Workspace { return { version: 0, messages: [], operation: null, active: null, draft: null, assessment: null, stale: false,
 context: { ready: true, issues: [], model_available: true, research_coverage: 'no_findings', goal: { role: 'Developer', target_type: 'specific_job' }, cv: { id: 'cv-one', name: 'synthetic.docx' }, planning_defaults: { application_date: null, weekly_hours: 6, availability_periods: [] } }, ...overrides }; }
beforeEach(() => { api.mockReset(); session.account = { id: 'owner-one' }; session.token = 'synthetic-token'; });
it('gates missing CV and goal without making model requests', async () => {
 const value = state(); value.context.ready = false; value.context.issues = [{ source: 'cv', message: 'Select an extracted CV.', href: '/cv' }]; api.mockResolvedValue(value);
 render(<RoadmapPlanner />); await screen.findByText('Select an extracted CV.');
 expect(screen.getByRole('link', { name: 'Open CV' })).toHaveAttribute('href', '/cv');
 expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled(); expect(api).toHaveBeenCalledTimes(1);
});
it('retains the next draft during async advice and sends the exact chosen partial flag', async () => {
 let resolveSend: (value: unknown) => void = () => {};
 api.mockImplementation((path: string) => path === '/messages' ? new Promise(resolve => { resolveSend = resolve; }) : Promise.resolve(state()));
 render(<RoadmapPlanner />); const input = await screen.findByRole('textbox', { name: 'Talk through your plan' });
 fireEvent.change(input, { target: { value: 'I have six hours a week.' } }); fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
 await waitFor(() => expect(input).toHaveValue('')); fireEvent.change(input, { target: { value: 'Keep Saturday free.' } });
 await act(async () => resolveSend({ version: 1, operation: { id: 'saved', status: 'pending' } }));
 await waitFor(() => expect(input).toHaveValue('Keep Saturday free.'));
 expect(api.mock.calls.find(call => call[0] === '/messages')?.[2]).toMatchObject({ message: 'I have six hours a week.', allow_partial_assessment: false });
});
it('requires an explicit choice for incomplete interview research', async () => {
 const value = state(); value.context.research_coverage = 'unavailable'; api.mockResolvedValue(value); render(<RoadmapPlanner />);
 fireEvent.change(await screen.findByRole('textbox', { name: 'Talk through your plan' }), { target: { value: 'Help me plan.' } });
 expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
 fireEvent.click(screen.getByRole('checkbox', { name: /Continue with available evidence/ }));
 expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
});
it('clears private conversation and ignores old responses on account switch', async () => {
 let oldResponse: (value: Workspace) => void = () => {};
 api.mockImplementationOnce(() => new Promise(resolve => { oldResponse = resolve; })).mockResolvedValue(state());
 const view = render(<RoadmapPlanner />); session.account = { id: 'owner-two' }; session.token = 'second-token'; view.rerender(<RoadmapPlanner />);
 await screen.findByText('What would a manageable week look like?');
 await act(async () => oldResponse(state({ messages: [{ id: 'private', role: 'user', content: 'Private old-owner plans', created_at: '2030-01-01' }] })));
 expect(screen.queryByText('Private old-owner plans')).not.toBeInTheDocument();
});
it('retries a lost-response message using its original mutation identity', async () => {
 let failed = true;
 api.mockImplementation((path: string) => path === '/messages' ? failed ? Promise.reject(new Error('Connection lost.')) : Promise.resolve({ version: 1, operation: null }) : Promise.resolve(state()));
 render(<RoadmapPlanner />); fireEvent.change(await screen.findByRole('textbox', { name: 'Talk through your plan' }), { target: { value: 'Plan my week.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Send message' })); await screen.findByText('Connection lost.');
 const original = api.mock.calls.find(call => call[0] === '/messages')![2]; failed = false;
 fireEvent.click(screen.getByRole('button', { name: 'Recover sent message' }));
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '/messages')).toHaveLength(2));
 expect(api.mock.calls.filter(call => call[0] === '/messages')[1][2]).toEqual(original);
});

it('explains satisfied alternatives and preserves the original requirement wording', async () => {
 const value = state(); value.assessment = { id: 'a', input_hash: 'h', role: 'Developer', research_coverage: 'no_findings', priorities: [], interview_prep_gaps: [], constraints: [],
  groups: [{ id: 'languages', operator: 'any', requirement_refs: ['python', 'sql'], match_status: 'supported', known_shortfall_refs: [] }],
  job_skill_gaps: [{ ref: 'python', name: 'Python', match_status: 'supported', evidence: 'Python or SQL experience is accepted.', priority: 'required', components: [{ dimension: 'capability', status: 'supported', explanation: 'Personal project use.', evidence_refs: [] }] }, { ref: 'sql', name: 'SQL', match_status: 'uncertain', components: [] }] };
 api.mockResolvedValue(value); render(<RoadmapPlanner />); await screen.findByRole('tab', { name: 'Starting point' });
 fireEvent.click(screen.getByRole('tab', { name: 'Starting point' }));
 expect(screen.getByText('One supported permitted route satisfies this group. Unused alternatives are not mandatory work.')).toBeInTheDocument();
 expect(screen.getByText('Python or SQL experience is accepted.')).toBeInTheDocument();
});

it('distinguishes an unavailable source check from missing input and retains saved chat', async () => {
 const value = state({ messages: [{ id: 'saved', role: 'assistant', content: 'Your saved advice remains here.', created_at: '2030-01-01' }] });
 value.context.ready = false; value.context.availability = 'unavailable'; api.mockResolvedValue(value);
 render(<RoadmapPlanner />); await screen.findByText('Your saved advice remains here.');
 expect(screen.getByRole('button', { name: 'Retry source check' })).toBeVisible();
 expect(screen.queryByText('Bring your starting point and direction')).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
});

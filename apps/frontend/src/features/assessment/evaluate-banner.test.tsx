import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useComparison } from './comparison';
import { EvaluateBanner } from './evaluate-banner';
import { assessmentApi } from '@/lib/api/assessment';
vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: vi.fn()}));
const api = vi.mocked(assessmentApi);
const current = {version: 3, stale: false, result: null, operation: null, ready: true, issues: []};
const ready = {ready: true, model_available: true, cv_reviewed: true, research_pending: false, goal: {role: 'Synthetic Analyst'}};
function View({here = '/cv'}: {here?: '/cv' | '/career-goal'}) { const comparison = useComparison('synthetic'); return <EvaluateBanner comparison={comparison} here={here}/>; }
const serve = (context: object, value: object = {}) => api.mockImplementation(async path => path === '/context' ? {...ready, ...context} : path === '/operation' ? {retry_request: null} : {...current, ...value});
beforeEach(() => { vi.resetAllMocks(); serve({}); });

it('starts one versioned evaluation from the button and never on a read', async () => {
 render(<View/>);
 const button = await screen.findByRole('button', {name: 'Evaluate skills'});
 expect(screen.getByRole('heading', {name: 'Evaluate skills with career goal'})).toBeVisible();
 expect(screen.getByText(/which skills Synthetic Analyst needs that you already have/)).toBeVisible();
 expect(api.mock.calls.every(call => call[2] === undefined)).toBe(true);
 fireEvent.click(button);
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '')).toHaveLength(1));
 expect(api.mock.calls.find(call => call[0] === '')?.[2]).toMatchObject({expected_version: 3, allow_partial: true, mutation_id: expect.any(String)});
});
it('sends Skills Profile users to set a goal instead of offering the evaluation', async () => {
 serve({ready: false, goal: null, cv_reviewed: null, issues: [{source: 'career', message: 'Set a goal.', href: '/career-goal'}]}, {ready: false});
 render(<View/>);
 expect(await screen.findByRole('heading', {name: 'Set your Career Goal first'})).toBeVisible();
 expect(screen.getByRole('link', {name: 'Set career goal'})).toHaveAttribute('href', '/career-goal');
 expect(screen.queryByRole('button', {name: /Evaluate/})).not.toBeInTheDocument();
});
it('names the open step without a link when it belongs to the page already shown', async () => {
 serve({ready: false, cv_reviewed: null, issues: [{source: 'cv', message: 'Upload a CV.', href: '/cv'}]}, {ready: false});
 render(<View here="/cv"/>);
 expect(await screen.findByRole('heading', {name: 'Add your skills first'})).toBeVisible();
 expect(screen.queryByRole('link')).not.toBeInTheDocument();
 expect(screen.queryByRole('button', {name: /Evaluate/})).not.toBeInTheDocument();
});
it('waits for goal research before offering the evaluation', async () => {
 serve({research_pending: true});
 render(<View/>);
 expect(await screen.findByRole('heading', {name: 'elo is still researching your goal'})).toBeVisible();
 expect(screen.queryByRole('button', {name: /Evaluate/})).not.toBeInTheDocument();
});
it('shows progress while the evaluation runs and no second button', async () => {
 serve({}, {operation: {id: 'op', status: 'running', stage: 'assessed_8'}});
 render(<View/>);
 expect(await screen.findByRole('heading', {name: 'Evaluating your skills against Synthetic Analyst'})).toBeVisible();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('explains a failed evaluation and offers it again', async () => {
 serve({}, {operation: {id: 'op', status: 'failed', stage: 'assessed_0', error: {detail: 'Provider unavailable.', code: 'model_provider'}}});
 render(<View/>);
 expect(await screen.findByRole('button', {name: 'Evaluate again'})).toBeEnabled();
 expect(screen.getByRole('alert')).toBeVisible();
});
it('disappears once a current evaluation exists', async () => {
 serve({}, {result: {id: 'a', input_hash: 'h', job_skill_gaps: [], groups: []}});
 const view = render(<View/>);
 await waitFor(() => expect(api.mock.calls.some(call => call[0] === '/context')).toBe(true));
 await waitFor(() => expect(view.container).toBeEmptyDOMElement());
});

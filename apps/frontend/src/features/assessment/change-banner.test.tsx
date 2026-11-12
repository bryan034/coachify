import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ChangeBanner, describeChange } from './change-banner';
import { assessmentApi } from '@/lib/api/assessment';
import { roadmapApi } from '@/lib/api/roadmap';

const path = vi.hoisted(() => ({ current: '/jobs' }));
vi.mock('next/navigation', () => ({ usePathname: () => path.current }));
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => ({ token: 'synthetic' }) }));
vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: vi.fn()}));
vi.mock('@/lib/api/roadmap', () => ({ roadmapApi: vi.fn() }));
const api = vi.mocked(assessmentApi), roadmap = vi.mocked(roadmapApi);

const before = {cv_id: 'cv-old', goal_id: 'goal-1', goal_version: 2};
const result = {input_hash: 'old-hash', inputs: before, job_skill_gaps: [], groups: [], priorities: []};
const context = {ready: true, model_available: true, cv_reviewed: true, research_pending: false, input_hash: 'new-hash',
 goal: {role: 'Synthetic Analyst', target_type: 'specific_job'}, cv: {name: 'Synthetic CV v2'}, inputs: {...before, cv_id: 'cv-new'}};
function serve({ctx = {}, value = {}, plan = null as string | null} = {}) {
 api.mockImplementation(async path => path === '/context' ? {...context, ...ctx} : path === '/operation' ? {retry_request: null}
  : {version: 4, stale: true, result, operation: null, ready: true, issues: [], ...value});
 roadmap.mockResolvedValue({version: 1, active: plan ? {assessment_hash: plan} : null});
}
beforeEach(() => { vi.resetAllMocks(); path.current = '/jobs'; try { sessionStorage.clear(); } catch { /* jsdom */ } serve(); });

it('names what changed between the evaluated and current inputs', () => {
 expect(describeChange(before, {...before, cv_id: 'cv-new'})).toBe('cv');
 expect(describeChange(before, {...before, goal_version: 3})).toBe('goal');
 expect(describeChange(before, {...before, cv_id: null, goal_id: 'goal-2'})).toBe('cv_and_goal');
 expect(describeChange(before, before)).toBe('details');
});

it('announces a new active CV on any page and updates the evaluation only when asked', async () => {
 serve({plan: 'old-hash'});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('heading', {name: 'Your active CV changed'})).toBeVisible();
 expect(screen.getByText(/skill evaluation and roadmap still use your previous CV.*reflect Synthetic CV v2/)).toBeVisible();
 expect(screen.getByRole('link', {name: 'Update roadmap'})).toHaveAttribute('href', '/roadmap');
 expect(api.mock.calls.every(call => call[2] === undefined)).toBe(true);
 fireEvent.click(screen.getByRole('button', {name: 'Update evaluation'}));
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '')).toHaveLength(1));
 expect(api.mock.calls.find(call => call[0] === '')?.[2]).toMatchObject({expected_version: 4, allow_partial: true});
});

it('calls a changed specific job a job description change', async () => {
 serve({ctx: {inputs: {...before, goal_version: 3}}});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('heading', {name: 'Your job description changed'})).toBeVisible();
 expect(screen.queryByRole('link', {name: 'Update roadmap'})).not.toBeInTheDocument();
});

it('shows progress while the new evaluation runs', async () => {
 serve({value: {operation: {id: 'op', status: 'running'}}});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('heading', {name: 'Updating your skill evaluation'})).toBeVisible();
 expect(screen.queryByRole('button', {name: 'Update evaluation'})).not.toBeInTheDocument();
});

it.each(['/roadmap', '/roadmap/tasks/synthetic'])('leaves %s to the roadmap regeneration banner', async current => {
 path.current = current;
 serve({plan: 'old-hash'});
 const {container} = render(<ChangeBanner/>);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/context', 'synthetic', undefined, expect.anything()));
 expect(container).toBeEmptyDOMElement();
});

it('asks for the CV review before evaluating an unreviewed new CV', async () => {
 serve({ctx: {cv_reviewed: false}});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('link', {name: 'Review your CV'})).toHaveAttribute('href', '/cv');
 expect(screen.queryByRole('button', {name: 'Update evaluation'})).not.toBeInTheDocument();
});

it('points to the roadmap once the evaluation is current but the plan is not', async () => {
 serve({value: {stale: false, result: {...result, input_hash: 'new-hash'}}, plan: 'old-hash'});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('heading', {name: 'Your roadmap is out of date'})).toBeVisible();
 fireEvent.click(screen.getByRole('button', {name: 'Not now'}));
 expect(screen.queryByRole('heading', {name: 'Your roadmap is out of date'})).not.toBeInTheDocument();
});

it('stays hidden when everything is current or nothing was evaluated yet', async () => {
 serve({value: {stale: false, result: {...result, input_hash: 'new-hash'}}, plan: 'new-hash'});
 const { container, unmount } = render(<ChangeBanner/>);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/context', 'synthetic', undefined, expect.anything()));
 expect(container).toBeEmptyDOMElement();
 unmount();
 serve({value: {stale: false, result: null}});
 const second = render(<ChangeBanner/>);
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '/context').length).toBeGreaterThan(1));
 expect(second.container).toBeEmptyDOMElement();
});

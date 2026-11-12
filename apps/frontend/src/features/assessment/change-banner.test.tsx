import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ChangeBanner, describeChange, resetAutomaticEvaluations } from './change-banner';
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
beforeEach(() => { vi.resetAllMocks(); resetAutomaticEvaluations(); path.current = '/jobs'; try { sessionStorage.clear(); } catch { /* jsdom */ } serve(); });

it('names what changed between the evaluated and current inputs', () => {
 expect(describeChange(before, {...before, cv_id: 'cv-new'})).toBe('cv');
 expect(describeChange(before, {...before, goal_version: 3})).toBe('goal');
 expect(describeChange(before, {...before, cv_id: null, goal_id: 'goal-2'})).toBe('cv_and_goal');
 expect(describeChange(before, before)).toBe('details');
});

const started = () => api.mock.calls.filter(call => call[0] === '');

it.each(['/cv', '/career-goal'])('updates the evaluation on its own on %s after the CV or goal changed', async current => {
 path.current = current;
 render(<ChangeBanner/>);
 await waitFor(() => expect(started()).toHaveLength(1));
 expect(started()[0][2]).toMatchObject({expected_version: 4, allow_partial: true});
});

it('shows only the skill-gap progress banner while the update runs', async () => {
 path.current = '/career-goal';
 serve({value: {operation: {id: 'op', status: 'running'}}});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('heading', {name: 'Evaluating the skill gap between you and your career goal…'})).toBeVisible();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
 expect(started()).toHaveLength(0);
});

it('waits for the CV review to rate new skills before comparing them with the goal', async () => {
 path.current = '/cv';
 serve({ctx: {cv_reviewed: false}});
 const {container} = render(<ChangeBanner/>);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/context', 'synthetic', undefined, expect.anything()));
 expect(started()).toHaveLength(0);
 expect(container).toBeEmptyDOMElement();
});

it('waits for goal research before updating', async () => {
 path.current = '/career-goal';
 serve({ctx: {research_pending: true}});
 render(<ChangeBanner/>);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/context', 'synthetic', undefined, expect.anything()));
 expect(started()).toHaveLength(0);
});

it('does not retry a failed automatic update on its own, but offers to', async () => {
 path.current = '/cv';
 render(<ChangeBanner/>);
 await waitFor(() => expect(started()).toHaveLength(1));
 serve({value: {operation: {id: 'op', status: 'failed', error: {detail: 'Provider unavailable.', code: 'model_provider'}}}});
 window.dispatchEvent(new Event('elo:comparison-refresh'));
 expect(await screen.findByRole('heading', {name: 'Your skill gap couldn’t be updated'})).toBeVisible();
 expect(started()).toHaveLength(1);
 fireEvent.click(screen.getByRole('button', {name: 'Try again'}));
 await waitFor(() => expect(started()).toHaveLength(2));
});

it.each(['/jobs', '/roadmap', '/career-goal/chat'])('never starts an evaluation or shows a banner on %s', async current => {
 path.current = current;
 serve({plan: 'old-hash'});
 const {container} = render(<ChangeBanner/>);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/context', 'synthetic', undefined, expect.anything()));
 expect(container).toBeEmptyDOMElement();
 if (current !== '/career-goal/chat') expect(started()).toHaveLength(0);
});

it('tells Home the roadmap is out of date until it is regenerated or dismissed', async () => {
 path.current = '/dashboard';
 serve({value: {stale: false, result: {...result, input_hash: 'new-hash'}}, plan: 'old-hash'});
 render(<ChangeBanner/>);
 expect(await screen.findByRole('heading', {name: 'Your roadmap is out of date'})).toBeVisible();
 expect(screen.getByRole('link', {name: 'Update roadmap'})).toHaveAttribute('href', '/roadmap');
 expect(started()).toHaveLength(0);
 fireEvent.click(screen.getByRole('button', {name: 'Not now'}));
 expect(screen.queryByRole('heading', {name: 'Your roadmap is out of date'})).not.toBeInTheDocument();
});

it('stays hidden on Home when the roadmap is current or there is none', async () => {
 path.current = '/dashboard';
 serve({value: {stale: false, result: {...result, input_hash: 'new-hash'}}, plan: 'new-hash'});
 const { container, unmount } = render(<ChangeBanner/>);
 await waitFor(() => expect(api).toHaveBeenCalledWith('/context', 'synthetic', undefined, expect.anything()));
 expect(container).toBeEmptyDOMElement();
 unmount();
 serve();
 const second = render(<ChangeBanner/>);
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '/context').length).toBeGreaterThan(1));
 expect(second.container).toBeEmptyDOMElement();
});

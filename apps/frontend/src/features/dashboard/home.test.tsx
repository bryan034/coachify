import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { HomeDashboard, journeyStates } from './home';
import { ProfileProvider } from '@/features/profile/profile-provider';

const session = (id: string, date: string, status: 'scheduled' | 'completed', extra: object = {}) => ({ id, task_id: `task-${id}`, title: `Task ${id}`, instructions: `Do task ${id} carefully.`, completion_criterion: `${id} works`, date, start_time: '19:00', duration_minutes: 30, status, completed_at: status === 'completed' ? `${date}T20:00:00Z` : null, missed: false, origin: 'generated', milestone_key: 'm1', skills: [{ name: 'SQL' }], ...extra });
const milestones = [
 { id: 'id-m1', key: 'm1', title: 'Foundations', estimated_minutes: 600, projected_start: '2026-11-06', projected_end: '2026-11-29', checkpoints: [{ key: 'c1', title: 'Flow recorded', date: '2026-11-26', reached_at: null }] },
 { id: 'id-m2', key: 'm2', title: 'Workflow', estimated_minutes: 3000, projected_start: '2026-11-30', projected_end: '2027-04-30', checkpoints: [] },
];
const active = { id: 'plan', milestones, assignments: [], gaps: [], first_planning_week: '2026-11-02' };
const planner = (extra: object = {}) => ({ config: { target_date: '2027-05-04', preferred_session_minutes: 60 }, config_saved: true, runway: { can_generate: true, issues: [], resolved: { today: '2026-11-06', start_date: '2026-11-06', target_date: '2027-05-04', matched_duration: null }, calendar: { days: 179, weeks: 25, extra_days: 4, label: '', partial_first_week: false }, study: {}, weeks: [], first_planning_week: null }, inputs: {}, candidate: null, candidate_review: null, candidate_blockers: [], active: null, active_review: null, confirmations: {}, signals: [], ...extra });
const goal = (skills: object[]) => ({ goal: { _id: 'g', version: 1, target_type: 'career_exploration', role: 'Synthetic Analyst', field: 'Data', employment_type: 'internship', company: 'Example', location: null, seniority_level: null, job_url: null, skills, interests: [], preferences: [], readiness: 'ready', exploration_draft_id: null, exploration_draft_version: null }, selection_version: 1, dependent_results_need_review: false, skill_groups: {} });
const skills = [{ item_id: 'a', name: 'SQL', category: 'x', priority: 'required', origin: 'employer' }, { item_id: 'b', name: 'Testing', category: 'x', priority: 'required', origin: 'employer' }, { item_id: 'c', name: 'Excel', category: 'x', priority: 'preferred', origin: 'employer' }];
type Overrides = Record<string, unknown>;
const liveData = (url: string, o: Overrides = {}): any => {
 for (const [key, value] of Object.entries(o)) if (url.includes(key)) return value;
 if (url.endsWith('/auth/session')) return { id: 'synthetic', name: 'Synthetic Person', provider: 'local_test', onboarding_complete: true };
 if (url.endsWith('/auth-config')) return { mode: 'local_test' };
 if (url.endsWith('/school-categories')) return [];
 if (url.endsWith('/career/goals/current')) return goal(skills);
 if (url.includes('opportunity-research')) return { available: true, status: 'completed', categories: {}, sources: [], error_code: null };
 if (url.endsWith('/assessments/current')) return { version: 0, stale: false, ready: true, model_available: true, result: null, operation: null, issues: [] };
 if (url.includes('/assessments/')) return { version: 0, stale: false, ready: true, model_available: true, result: null, operation: null, issues: [] };
 if (url.endsWith('/profile/skills-profile')) return { version: 0, status: 'empty', saved_at: null, areas: {}, entries: [] };
 if (url.endsWith('/profile/capabilities')) return { version: 1, declarations: [{ id: 'd1', name: 'Python', description: 'Synthetic.', skill_id: 'python', provenance: 'user_declared', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }], limits: { name: 120, description: 2000 }, skill_groups: { Python: 'Technical coding' } };
 if (url.endsWith('/cv/skills')) return { cv_id:null, cv_version:null, profile_version:0, declarations_version:1,
  skills:[{key:'python',name:'Python',basis:'declared',sources:[]}], skill_groups:{Python:'Technical coding'}, skill_subgroups:{} };
 if (url.endsWith('/api/v1/cv')) return { cvs: [], selection: { cv_id: null, version: 0 } };
 if (url.includes('/roadmaps/workspace')) return { version: 4, messages: [], operation: null, active: null, draft: null, assessment: null, stale: false, context: { ready: true, issues: [], model_available: true }, planner: planner() };
 if (url.endsWith('/jobs/applications')) return { items: [] };
 return { version: 1, occupational_status: 'student', school_category: 'university', current_study_year: 3, education_review_required: false, education: { course: 'Synthetic Course' } };
};
const stub = (o: Overrides = {}, calls: { url: string; init?: RequestInit }[] = []) => vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => { calls.push({ url, init }); return new Response(JSON.stringify(liveData(url, o))); }));
const comparison = (statuses: Record<string, string>) => ({ version: 1, stale: false, ready: true, model_available: true, operation: null, issues: [], result: { groups: [], research_coverage: 'available', job_skill_gaps: Object.entries(statuses).map(([ref, match_status]) => ({ ref: `job:${ref}`, match_status })) } });
const withRoadmap = (sessions: object[]) => ({ '/roadmaps/workspace': { version: 4, messages: [], operation: null, active: null, draft: null, assessment: null, stale: false, context: { ready: true, issues: [], model_available: true }, planner: planner({ active, active_sessions: sessions, active_review: { next_assignment_id: null, missed_assignment_ids: [], remaining: {}, milestones: {} } }) } });
const skillsReady = { '/profile/skills-profile': { version: 1, status: 'saved', saved_at: null, areas: {}, entries: [{ id: 'e1', kind: 'work', title: 'Intern', fields: {}, skills: [] }] } };
afterEach(() => vi.unstubAllGlobals());

test('while set-up is unfinished the hero names the one open step and counts the steps done', async () => {
 stub();
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 expect(await screen.findByRole('heading', { level: 1, name: 'Welcome back, Synthetic.' })).toBeVisible();
 expect(await screen.findByText('3 of 4 steps done')).toBeVisible();
 expect(screen.getByText('Step 4 of 4', { selector: '.when' })).toBeVisible();
 expect(screen.getByRole('heading', { name: 'Compare your skills with your career goal' })).toBeVisible();
 expect(screen.getAllByRole('link', { name: 'Compare my skills' })[0]).toHaveAttribute('href', '/career-goal');
 expect(screen.getByText('Once your roadmap is accepted, your daily tasks will appear here.')).toBeVisible();
});

test('Goal match counts the saved comparison, lists the top skills to strengthen and links to the Skills Profile', async () => {
 stub({ ...skillsReady, '/assessments/current': comparison({ a: 'supported', b: 'confirmed_shortfall', c: 'partial' }) });
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 const match = await screen.findByRole('article', { name: /Goal match/ });
 expect(await within(match).findByText(/of 3 goal skills you already have/)).toBeVisible();
 expect(within(match).getByRole('img', { name: 'Have 1, partial 1, gap 1, unknown 0' })).toBeInTheDocument();
 expect(within(match).getByRole('link', { name: /Synthetic Analyst at Example/ })).toHaveAttribute('href', '/career-goal');
 const rows = within(match).getAllByRole('listitem');
 expect(rows.map(row => row.querySelector('.gname')!.textContent)).toEqual(['Testing', 'Excel']);
 expect(within(rows[0]).getByText('Essential')).toBeVisible();expect(within(rows[0]).getByText('Gap')).toBeVisible();expect(within(rows[1]).getByText('Partial')).toBeVisible();
 expect(within(match).getByText('Importance to the role')).toBeVisible();
 expect(within(match).getByRole('link', { name: 'View Skills Profile' })).toHaveAttribute('href', '/cv');
 expect(within(match).getByText(/Based on/)).toHaveTextContent('Based on 1 skill in your profile');
});

test('Goal match ranks required and preferred skills equally within the same gap status', async () => {
 const orderedSkills = [skills[2], skills[0], skills[1], { ...skills[0], item_id: 'd', name: 'Python' }];
 stub({ ...skillsReady, '/career/goals/current': goal(orderedSkills), '/assessments/current': comparison({
  a: 'confirmed_shortfall', b: 'confirmed_shortfall', c: 'confirmed_shortfall', d: 'confirmed_shortfall',
 }) });
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 const match = await screen.findByRole('article', { name: /Goal match/ });
 await within(match).findByRole('heading', { name: 'Top 3 to strengthen' });
 const rows = within(match).getAllByRole('listitem');
 expect(rows.map(row => row.querySelector('.gname')!.textContent)).toEqual(['Excel', 'SQL', 'Testing']);
 expect(within(match).getAllByText('Essential', { selector: '.ws-pill.ess' })).toHaveLength(3);
});

test('a failed service is reported where it belongs and never counted as done or as next', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/career/goals/current') ? new Response(JSON.stringify({ detail: 'Career service unavailable.' }), { status: 503 }) : new Response(JSON.stringify(liveData(url)))));
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 expect(await screen.findByRole('button', { name: 'Retry career goal' })).toBeVisible();
 expect(screen.queryByText(/steps done/)).not.toBeInTheDocument();
 expect(await screen.findByText(/Some of your information could not be loaded/)).toBeVisible();
});

test('journey states wait for every stop before naming the next one', () => {
 expect(journeyStates([true, 'loading', false])).toEqual(['done', 'checking', 'checking']);
 expect(journeyStates([true, 'error', false, false])).toEqual(['done', 'unavailable', 'next', 'later']);
 expect(journeyStates([true, true])).toEqual(['done', 'done']);
});

test('with a roadmap, Home shows the timeline, the next session, the week and the next checkpoint from the saved plan', async () => {
 stub({ ...skillsReady, ...withRoadmap([session('a', '2026-11-06', 'completed'), session('b', '2026-11-09', 'scheduled'), session('c', '2026-11-10', 'scheduled')]) });
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 expect(await screen.findByRole('heading', { name: 'Task b' })).toBeVisible();
 expect(screen.getByText('Foundations')).toBeVisible();expect(screen.getByText('Workflow')).toBeVisible();
 expect(screen.getByRole('img', { name: /Timeline of 2 milestones/ })).toBeInTheDocument();
 expect(screen.getByText(/After this:/)).toHaveTextContent('After this: Task c, 10 Nov, 19:00');
 const roadmap = screen.getByRole('article', { name: /Roadmap/ });
 expect(within(roadmap).getByText(/days to 4 May 2027/).parentElement).toHaveTextContent('179days to 4 May 2027');
 expect(within(roadmap).getByRole('progressbar', { name: 'Weeks into your roadmap' })).toHaveAttribute('aria-valuemax', '25');
 expect(within(roadmap).getByText('Flow recorded')).toBeVisible();
 expect(within(roadmap).getByText('1 of 3 sessions done')).toBeVisible();
 const progress = screen.getByRole('article', { name: /Your progress/ });
 expect(within(progress).getByText('Finished “Task a”')).toBeVisible();
});

test('Mark as done completes the next session through the Roadmap command and refreshes the plan', async () => {
 const calls: { url: string; init?: RequestInit }[] = [];
 stub({ ...skillsReady, '/planner/tasks/status': withRoadmap([])['/roadmaps/workspace'], ...withRoadmap([session('b', '2026-11-09', 'scheduled')]) }, calls);
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 fireEvent.click(await screen.findByRole('button', { name: 'Mark as done' }));
 await waitFor(() => expect(calls.some(call => call.url.endsWith('/roadmaps/planner/tasks/status'))).toBe(true));
 const body = JSON.parse(String(calls.find(call => call.url.endsWith('/planner/tasks/status'))!.init!.body));
 expect(body).toMatchObject({ expected_version: 4, task_id: 'task-b', status: 'completed', mutation_id: expect.any(String) });
 expect(await screen.findByText('Marked as done')).toBeVisible();
});

test('See details shows the task’s instructions and what done looks like', async () => {
 stub({ ...skillsReady, ...withRoadmap([session('b', '2026-11-09', 'scheduled')]) });
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 fireEvent.click(await screen.findByRole('button', { name: 'See details' }));
 expect(screen.getByText(/Do task b carefully\./)).toHaveTextContent('Done when: b works');
 fireEvent.click(screen.getByRole('button', { name: 'Hide details' }));
 expect(screen.queryByText(/Do task b carefully\./)).not.toBeInTheDocument();
});

test('completing the next session starts the following session with its details closed', async () => {
 const overrides = { ...skillsReady, ...withRoadmap([session('b', '2026-11-09', 'scheduled'), session('c', '2026-11-10', 'scheduled')]) };
 vi.stubGlobal('fetch', vi.fn(async (url: string) => {
  if (url.endsWith('/planner/tasks/status')) {
   overrides['/roadmaps/workspace'] = withRoadmap([session('b', '2026-11-09', 'completed'), session('c', '2026-11-10', 'scheduled')])['/roadmaps/workspace'];
   return new Response(JSON.stringify(overrides['/roadmaps/workspace']));
  }
  return new Response(JSON.stringify(liveData(url, overrides)));
 }));
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 fireEvent.click(await screen.findByRole('button', { name: 'See details' }));
 expect(screen.getByText(/Do task b carefully\./)).toBeVisible();
 fireEvent.click(screen.getByRole('button', { name: 'Mark as done' }));
 expect(await screen.findByRole('heading', { name: 'Task c' })).toBeVisible();
 expect(screen.getByRole('button', { name: 'See details' })).toHaveAttribute('aria-expanded', 'false');
 expect(screen.queryByText(/Do task [bc] carefully\./)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'See details' }));
 expect(screen.getByText(/Do task c carefully\./)).toHaveTextContent('Done when: c works');
});

test('with every planned task finished the hero says all caught up', async () => {
 stub({ ...skillsReady, ...withRoadmap([session('a', '2026-11-06', 'completed')]) });
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 expect(await screen.findByRole('heading', { name: 'You’ve finished the planned tasks' })).toBeVisible();
 expect(screen.getByRole('link', { name: 'Plan next steps' })).toHaveAttribute('href', '/roadmap');
 expect(screen.getByText('week on track')).toBeVisible();
});

test('Coming up lists saved-job deadlines and follow-ups in date order, and says so when there are none', async () => {
 const job = (id: string, extra: object) => ({ id, posting_id: id, version: 1, status: 'saved', posting_status: 'open', snapshot: { title: `Intern ${id}`, company: 'Synthetic Co', location: 'Singapore', job_type: 'internship', listing_url: 'https://example.test', apply_url: 'https://example.test' }, history: [], created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', ...extra });
 stub({ '/jobs/applications': { items: [job('b', { status: 'applied', follow_up_at: '2026-11-20' }), job('a', { deadline: '2026-11-10' }), job('c', { deadline: '2026-10-01' })] } });
 const view = render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 const upcoming = await screen.findByRole('article', { name: /Coming up/ });
 await within(upcoming).findByText('Application deadline');
 expect(within(upcoming).getAllByRole('listitem').map(item => item.querySelector('strong')!.textContent)).toEqual(['Application deadline', 'Follow up']);
 expect(upcoming).toHaveTextContent('Intern a · Synthetic Co · in 4 days');
 expect(upcoming).not.toHaveTextContent('Intern c');
 view.unmount();
 stub();
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 expect(await screen.findByText(/No deadlines or follow-ups yet/)).toBeVisible();
 expect(screen.getByRole('link', { name: 'Search jobs' })).toHaveAttribute('href', '/jobs');
});

test('the daily tip and practice question come from cited research and link to their source or interview practice', async () => {
 const finding = (id: string, field: string, value: string, source_ids: string[] = ['s1']) => ({ finding_id: id, field, value, confidence: 'high', evidence_type: 'candidate_reported', source_ids, scope: 'role', conflict_group: null, last_verified_at: '2026-11-01T00:00:00Z' });
 stub({ opportunity: { available: true, job_id: null, career_target_id: 'g', status: 'completed', error_code: null, sources: [{ source_id: 's1', platform: 'web', url: 'https://reviews.example.test/post', title: null }],
  categories: { internship_insights: { status: 'completed', missing_fields: [], warnings: [], error_code: null, findings: [finding('f1', 'mentorship', 'Mentor time can be limited, so bring specific questions and book your own check-ins.')] }, interview_intelligence: { status: 'completed', missing_fields: [], warnings: [], error_code: null, findings: [finding('f2', 'interview_questions', 'How would you decide between two urgent requests from different users?')] } } } });
 render(<ProfileProvider><HomeDashboard /></ProfileProvider>);
 expect(await screen.findByText(/Mentor time can be limited/)).toBeVisible();
 expect(screen.getByRole('link', { name: 'See source' })).toHaveAttribute('href', 'https://reviews.example.test/post');
 expect(screen.getByText(/Found by elo on reviews\.example\.test/)).toBeVisible();
 fireEvent.click(screen.getByRole('tab', { name: 'Practice question' }));
 expect(screen.getByText(/two urgent requests/)).toBeVisible();
 expect(screen.getByRole('link', { name: 'Practise this question' })).toHaveAttribute('href', '/career-goal/interview');
});

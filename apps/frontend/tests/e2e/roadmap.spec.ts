import { test, expect } from '@playwright/test';
import type { Workspace, Plan, Task } from '../../src/features/roadmap/types';
function initial(): Workspace { return { version: 0, messages: [], operation: null, active: null, draft: null, assessment: null, stale: false,
 context: { ready: true, issues: [], model_available: true, research_coverage: 'no_findings', goal: { role: 'Backend developer', target_type: 'specific_job', job_dates: [{ kind: 'job_start', text: '1 April 2030', date: '2030-04-01', evidence: 'Start date: 1 April 2030.' }] }, cv: { id: 'synthetic-cv', name: 'synthetic-cv.docx' }, planning_defaults: { weekly_hours: 6, application_date: null, availability_periods: [] } } }; }
function proposal(): Plan {
 const task: Task = { id: 'task1', title: 'Explain your API project decisions', instructions: 'Choose two decisions in your project. Explain the alternatives and why you chose your approach.', completion_outcome: 'Write a short explanation with two concrete trade-offs.', estimated_minutes: 120, rationale: 'Build on the Python and API experience you already declared.', requirement_refs: ['job:python'], prerequisites: [], milestone: 'Tell your project story', splittable: true, status: 'not_started' };
 const assessment = { id: 'assessment1', input_hash: 'source1', role: 'Backend developer', research_coverage: 'no_findings', job_skill_gaps: [{ ref: 'job:python', name: 'Explain project decisions', match_status: 'uncertain' as const, components: [{ dimension: 'independence', status: 'uncertain', explanation: 'Your project is described, but the decisions you personally made remain unclear.', evidence_refs: ['cv:project'] }] }], interview_prep_gaps: [], constraints: [], priorities: [], evidence: { 'cv:project': { name: 'Personal API project', text: 'I built a small API using Python.' } } };
 return { id: 'plan1', assessment_id: assessment.id, assessment_hash: assessment.input_hash, assessment, tasks: [task], preferences: { start_date: '2030-01-07', target_date: '2030-03-01', horizon_weeks: null, weekly_minutes: 360, days: [{ day: 0, minutes: 60 }, { day: 5, minutes: 300 }], max_session_minutes: 60, time_zone: 'Asia/Singapore', learning_preferences: 'Project-based learning', reduced_periods: [] }, exclusions: [], unaddressed_requirements: [], schedule: { status: 'feasible', issues: [], remainders: { task1: 0 }, allocations: [{ task_id: 'task1', date: '2030-01-07', minutes: 60, order: 0 }, { task_id: 'task1', date: '2030-01-12', minutes: 60, order: 1 }], milestones: [{ name: 'Tell your project story', task_ids: ['task1'], status: 'in_progress', target_date: '2030-01-12' }], remaining_minutes: 120, allocated_minutes: 120, available_minutes: 2400 } };
}
test('adviser chat, reviewed activation, edits, completion, reload and responsive plan', async ({ page }) => {
 await page.addInitScript(() => { localStorage.setItem('elo.access-epoch', '1'); sessionStorage.setItem('elo.session', JSON.stringify({ token: 'synthetic-session', epoch: '1' })); });
 await page.route('**/api/v1/profile**', route => { const path = new URL(route.request().url()).pathname;
  return route.fulfill({ json: path.endsWith('/auth-config') ? { mode: 'email', google_enabled: false } : path.endsWith('/auth/session') ? { id: 'synthetic-owner', name: 'Synthetic User', email_verified: true, provider: 'email' } : { version: 1, onboarding_complete: true, occupational_status: 'employed', education: {} } }); });
 let state = initial(), generation = 0;
 await page.route('**/api/v1/roadmaps/**', async route => {
  const path = new URL(route.request().url()).pathname;
  if (route.request().method() === 'GET') return route.fulfill({ json: state });
  const body = route.request().postDataJSON(); expect(body.expected_version).toBe(state.version); expect(body.mutation_id).toBeTruthy();
  if (path.endsWith('/messages')) {
   generation++; state = { ...state, version: state.version + 1, messages: [{ id: 'm1', role: 'user', content: body.message, created_at: '2030-01-01' }, { id: 'm2', role: 'assistant', content: 'You already have API experience. We could practise explaining two project decisions, keeping weekdays light. This is a proposal you can shape.', created_at: '2030-01-01' }], draft: proposal(), assessment: proposal().assessment, operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' } };
   return route.fulfill({ status: 202, json: { version: state.version, operation: state.operation } });
  }
  if (path.endsWith('/activate')) state = { ...state, version: state.version + 1, active: state.draft, draft: null };
  if (path.endsWith('/tasks/status')) { state.version++; state.active!.tasks[0].status = body.status; state.active!.schedule.remaining_minutes = body.status === 'completed' ? 0 : 120; state.active!.schedule.status = body.status === 'completed' ? 'no_work' : 'feasible'; state.active!.schedule.milestones[0].status = body.status === 'completed' ? 'completed' : 'in_progress'; }
  if (path.endsWith('/preferences')) { state.version++; state.draft = { ...state.active!, preferences: body.preferences }; }
  return route.fulfill({ json: state });
 });
 await page.goto('/roadmap');
 await expect(page.getByRole('heading', { name: 'Your career adviser' })).toBeVisible();
 await expect(page.getByText('Room for your next steps')).toBeVisible(); expect(generation).toBe(0);
 await page.getByRole('textbox', { name: 'Talk through your plan' }).fill('I have six hours a week. Keep weekdays light and use Saturday.');
 await page.getByRole('button', { name: 'Send message' }).click();
 await expect(page.getByRole('log')).toContainText('You already have API experience');
 await expect(page.getByRole('button', { name: 'Start this plan' })).toBeVisible();
 await page.getByRole('button', { name: 'Start this plan' }).click();
 await expect(page.getByText('Your active plan', { exact: true })).toBeVisible();
 await page.getByLabel('Focus date').fill('2030-01-07');
 await expect(page.getByLabel('Daily workload')).toContainText('Mon');
 await page.getByRole('tab', { name: 'Starting point' }).click();
 await page.locator('.assessment-view summary').click();
 await expect(page.getByText('I built a small API using Python.', { exact: false })).toBeVisible();
 await page.getByRole('tab', { name: 'Your plan', exact: true }).click();
 await page.locator('details.plan-task summary').click();
 await page.getByRole('button', { name: 'Mark complete' }).click();
 await expect(page.getByRole('button', { name: 'Reopen as not started' })).toBeVisible();
 await expect(page.getByLabel('Daily workload')).toContainText('No activities allocated in this period.');
 await page.reload(); await expect(page.getByText('Your active plan', { exact: true })).toBeVisible();
 await page.getByRole('button', { name: 'Adjust time and days' }).click();
 const dialog = page.getByRole('dialog'); await expect(dialog).toBeVisible(); await expect(page.getByLabel('Start preparing')).toBeFocused();
 await page.getByLabel('Weekly budget in hours').fill('7');
 await page.getByRole('button', { name: 'Preview schedule' }).click();
 await expect(page.getByRole('button', { name: 'Apply these changes' })).toBeVisible();
 await page.screenshot({ path: test.info().outputPath('roadmap-desktop.png'), fullPage: true });
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 await expect(page.getByRole('textbox', { name: 'Talk through your plan' })).toBeVisible();
 await page.screenshot({ path: test.info().outputPath('roadmap-mobile.png'), fullPage: true });
 expect(generation).toBe(1);
});

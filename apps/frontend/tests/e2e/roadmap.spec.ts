import { test, expect, type Page } from '@playwright/test';
import type { PlannedRoadmap, Workspace } from '../../src/features/roadmap/types';
import { blankPlanner, config, review, roadmap, runway, workspace } from '../fixtures/roadmap-workspace';

function initial(): Workspace { return workspace({ planner: { ...blankPlanner(), inputs: { goal: { role: 'Backend developer', target_type: 'specific_job', skills: [{ name: 'Python' }] }, cv: { id: 'synthetic-cv', name: 'synthetic-cv.docx' }, skills: [{ ref: 'cv:skill', name: 'Git', kind: 'skill', text: 'Used Git on a synthetic project.' }], experience: [{ ref: 'cv:project', name: 'Synthetic API project', kind: 'project', text: 'Built an API.' }], skill_groups: { Git: 'Tools' } } } }); }

async function signIn(page: Page) {
 await page.addInitScript(() => { localStorage.setItem('elo.access-epoch', '1'); sessionStorage.setItem('elo.session', JSON.stringify({ token: 'synthetic-session', epoch: '1' })); });
 await page.route('**/api/v1/profile**', route => { const path = new URL(route.request().url()).pathname;
  return route.fulfill({ json: path.endsWith('/auth-config') ? { mode: 'email', google_enabled: false } : path.endsWith('/auth/session') ? { id: 'synthetic-owner', name: 'Synthetic User', email_verified: true, provider: 'email' } : { version: 1, onboarding_complete: true, occupational_status: 'employed', education: {} } }); });
}
const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

test('chat helper fills the planner, then generate, review, accept, complete a session and revise with preview', async ({ page }) => {
 await signIn(page);
 let state = initial(), generations = 0, modelMessages = 0;
 const firstPlan: PlannedRoadmap = roadmap();
 const respond = (route: Parameters<Parameters<Page['route']>[1]>[0], body: unknown, status = 200) => route.fulfill({ status, json: body });
 await page.route('**/api/v1/roadmaps/**', async route => {
  const path = new URL(route.request().url()).pathname.replace('/api/v1/roadmaps', '');
  if (route.request().method() === 'GET') return respond(route, state);
  const body = route.request().postDataJSON();
  if (path === '/planner/runway') { const usesBackup = body.config.use_backup; return respond(route, runway({ study: { preferred_minutes: 690, backup_extra_minutes: 120, usable_minutes: usesBackup ? 810 : 690 } })); }
  expect(body.expected_version).toBe(state.version); expect(body.mutation_id).toBeTruthy();
  if (path === '/messages') {
   modelMessages++;
   state = { ...state, version: state.version + 1, messages: [...state.messages, { id: `u${modelMessages}`, role: 'user', content: body.message, created_at: '2030-01-09' }, { id: `r${modelMessages}`, role: 'assistant', content: 'I added those to the planner. Please review it, then press Generate.', created_at: '2030-01-09' }], operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' }, planner: { ...state.planner, config: config(), config_saved: true, runway: runway() } };
   return respond(route, { version: state.version, operation: state.operation }, 202);
  }
  if (path === '/planner/config') { state = { ...state, version: state.version + 1, planner: { ...state.planner, config: body.config, config_saved: true } }; return respond(route, state); }
  if (path === '/planner/generate') {
   generations++;
   const done = state.planner.active?.assignments.find(a => a.status === 'completed');
   const candidate = generations === 1 ? firstPlan : roadmap({ id: 'plan2', base_active_id: 'plan1', summary: 'Moved the next session to Thursday.', assignments: [...(done ? [done] : []), { ...firstPlan.assignments[0], id: 'a2', key: 'a2', date: '2030-01-10', start_time: '18:00', task: 'Add input validation to the endpoint.' }], changes: { completed_preserved: done ? 1 : 0, assignments_added: ['Add input validation to the endpoint.'], assignments_moved: [], assignments_removed: [], milestones_added: [], milestones_moved: [], milestones_removed: [] } });
   state = { ...state, version: state.version + 1, operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' }, assessment: candidate.assessment, planner: { ...state.planner, candidate, candidate_review: review(candidate) } };
   return respond(route, { version: state.version, operation: state.operation }, 202);
  }
  if (path === '/planner/accept') { const active = state.planner.candidate!; state = { ...state, version: state.version + 1, planner: { ...state.planner, active, active_review: review(active), candidate: null, candidate_review: null, signals: [] } }; return respond(route, state); }
  if (path === '/planner/assignments/status') {
   const active = { ...state.planner.active!, assignments: state.planner.active!.assignments.map(a => a.id === body.assignment_id ? { ...a, status: body.status, evidence_note: body.evidence_note, completed_at: '2030-01-09T12:00:00+00:00' } : a) };
   state = { ...state, version: state.version + 1, planner: { ...state.planner, active, active_review: { ...review(active), next_assignment_id: null }, signals: [{ kind: 'progress', message: 'You’ve completed 1 session(s) since this roadmap was prepared.' }] } };
   return respond(route, state);
  }
  return respond(route, state);
 });

 await page.goto('/roadmap');
 await expect(page.getByRole('heading', { name: 'What elo will use' })).toBeVisible();
 await expect(page.getByRole('heading', { name: 'Your chat helper' })).toHaveCount(0);
 const beside = async () => (await page.getByRole('region', { name: 'Your runway' }).boundingBox())!.x > (await page.locator('legend', { hasText: 'Timeline' }).boundingBox())!.x + 200;
 await page.setViewportSize({ width: 1920, height: 1080 });
 expect(await page.locator('.roadmap-main').evaluate(el => innerWidth - el.getBoundingClientRect().right)).toBeLessThanOrEqual(64);
 expect(await beside()).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-planner-wide.png'), fullPage: true });
 await page.setViewportSize({ width: 1280, height: 900 });
 expect(await beside()).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-planner.png'), fullPage: true });
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.setViewportSize({ width: 1280, height: 900 });
 await expect(page.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
 expect(generations).toBe(0);

 await page.getByRole('button', { name: 'Start chat helper' }).click();
 await expect(page.getByRole('heading', { name: 'When would you like to be ready?' })).toBeVisible();
 expect(await beside()).toBe(false);
 await expect(page.getByRole('button', { name: 'Send message' })).toBeInViewport({ ratio: 1 });
 await page.getByRole('textbox', { name: 'Answer here' }).fill('Five hours a week until 27 January, with Sunday as backup.');
 await page.getByRole('button', { name: 'Send message' }).click();
 await expect(page.getByRole('log')).toContainText('I added those to the planner');
 await expect(page.getByLabel('Target date')).toHaveValue('2030-01-27');
 await page.screenshot({ path: test.info().outputPath('roadmap-helper.png'), fullPage: false });
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-helper-mobile.png') });
 await page.getByRole('button', { name: 'Close chat helper' }).click();
 await page.getByRole('button', { name: 'Add blackout' }).click();
 const blackout = page.getByRole('group', { name: 'Blackout 2' });
 await blackout.getByLabel('Blackout 2 repeats').selectOption('monthly');
 await blackout.getByLabel('Blackout 2 all day').uncheck();
 await expect(blackout).toContainText('18:00–20:00');
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-blackout-mobile.png'), fullPage: true });
 await blackout.getByRole('button', { name: 'Remove blackout 2' }).click();
 await page.setViewportSize({ width: 1280, height: 900 });
 const runwaySection = page.getByRole('region', { name: 'Your runway' });
 await expect(runwaySection).toContainText('2 weeks, 5 days');
 await expect(runwaySection).toContainText('+2 h (not enabled)');
 await page.getByRole('checkbox', { name: 'Allow backup blocks when preferred time runs out' }).check();
 await expect(runwaySection).toContainText('13.5 h');
 await page.screenshot({ path: test.info().outputPath('roadmap-configure.png'), fullPage: true });

 await page.getByRole('button', { name: 'Generate roadmap' }).click();
 await expect(page.getByText('Preview: not active until you accept it')).toBeVisible();
 const timeline = page.getByRole('region', { name: 'Milestone timeline' });
 await expect(timeline).toContainText('Sun, 27 Jan 2030');
 await expect(page.getByRole('heading', { name: 'Beyond your deadline' })).toBeVisible();
 await expect(page.getByRole('region', { name: 'Where you are now' })).toContainText('Wed, 9 Jan 2030, 19:00–20:00');
 await page.screenshot({ path: test.info().outputPath('roadmap-review.png'), fullPage: true });
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-review-mobile.png'), fullPage: true });
 await page.setViewportSize({ width: 1280, height: 900 });

 await page.getByRole('button', { name: 'Back to configuration' }).click();
 await expect(page.getByRole('heading', { name: 'Your runway' })).toBeVisible();
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.setViewportSize({ width: 1280, height: 900 });
 await page.getByRole('button', { name: 'Return to roadmap' }).click();
 await page.getByRole('button', { name: 'Accept plan' }).click();
 await expect(page.getByText('Your active roadmap')).toBeVisible();

 await page.getByText('Mark session complete').click();
 await page.getByRole('textbox', { name: 'What did you produce? (optional)' }).fill('The endpoint test passes.');
 await page.getByRole('button', { name: 'Complete session' }).click();
 await expect(page.getByRole('heading', { name: 'Completed sessions' })).toBeVisible();
 await expect(page.getByText('Your note: The endpoint test passes.')).toBeVisible();
 await expect(timeline).toContainText('Outcome not yet demonstrated.');

 await page.reload();
 await expect(page.getByText('Your active roadmap')).toBeVisible();
 await page.getByRole('button', { name: 'Change settings' }).click();
 await page.getByLabel('Weekly budget in hours').fill('4');
 await expect(page.getByRole('button', { name: 'Save settings' })).toBeVisible();
 await page.getByRole('button', { name: 'Preview updated roadmap' }).click();
 const changes = page.getByRole('region', { name: 'What this preview changes' });
 await expect(changes).toContainText('1 completed session stays exactly as recorded.');
 await expect(changes).toContainText('Add input validation to the endpoint.');
 await expect(page.getByText('Your note: The endpoint test passes.')).toBeVisible();
 expect(state.planner.active!.id).toBe('plan1');
 await page.getByRole('button', { name: 'Accept plan' }).click();
 await expect(page.getByText('Moved the next session to Thursday.')).toBeVisible();

 await page.getByRole('button', { name: 'Continue with chat helper' }).click();
 await expect(page.getByRole('textbox', { name: 'Ask for a change' })).toBeVisible();
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 expect(generations).toBe(2);
});

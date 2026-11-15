import { test, expect, type Page } from '@playwright/test';
import type { MonthPreview, Outline, PlannedRoadmap, Workspace } from '../../src/features/roadmap/types';
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
 let state = initial(), generations = 0, modelMessages = 0, months = 0;
 const requests: string[] = [];
 const firstPlan: PlannedRoadmap = roadmap();
 const respond = (route: Parameters<Parameters<Page['route']>[1]>[0], body: unknown, status = 200) => route.fulfill({ status, json: body });
 await page.route('**/api/v1/roadmaps/**', async route => {
  const path = new URL(route.request().url()).pathname.replace('/api/v1/roadmaps', '');
  requests.push(`${route.request().method()} ${path}`);
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
  if (path === '/planner/outlines/generate') {
   generations++;
   const candidate: Outline = { id: `outline-${generations}`, revision: generations, assessment_hash: firstPlan.assessment_hash,
    summary: generations === 1 ? firstPlan.summary : 'Moved the next session to Thursday.', gaps: firstPlan.gaps, milestones: firstPlan.milestones,
    routine_rules: [], deadline_outcome: firstPlan.deadline_outcome, beyond_deadline: firstPlan.beyond_deadline, exclusions: firstPlan.exclusions, config: state.planner.config };
   state = { ...state, version: state.version + 1, operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' }, assessment: firstPlan.assessment, planner: { ...state.planner, outline_candidate: candidate } };
   return respond(route, { version: state.version, operation: state.operation }, 202);
  }
  if (path.match(/^\/planner\/outlines\/outline-\d+\/accept$/)) {
   state = { ...state, version: state.version + 1, planner: { ...state.planner, outline_active: state.planner.outline_candidate, outline_candidate: null } };
   return respond(route, state);
  }
  if (path === '/planner/months/generate') {
   months++;
   const revision = Boolean(body.revision);
   const candidate: MonthPreview = { id: revision ? 'month-2' : 'month-1', month: body.month, start_date: '2030-01-09', end_exclusive: '2030-01-28', time_zone: 'Asia/Singapore',
    ...(revision ? { replaces_block_id: 'month-1', replaced_task_ids: [] } : {}), tasks: [{ id: revision ? 'a2' : 'a1', title: revision ? 'Add input validation to the endpoint.' : 'Write one tested Python endpoint.', instructions: 'Build and test the endpoint.', completion_outcome: 'The endpoint test passes.', milestone_key: 'm1', schedule: [{ date: revision ? '2030-01-10' : '2030-01-09', start_time: revision ? '18:00' : '19:00', duration_minutes: 60 }] }] };
   state = { ...state, version: state.version + 1, operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' }, planner: { ...state.planner, month_candidate: candidate } };
   return respond(route, { version: state.version, operation: state.operation }, 202);
  }
  if (path.match(/^\/planner\/months\/month-[12]\/accept$/)) {
   const revision = path.includes('month-2');
   const done = state.planner.active?.assignments.find(a => a.status === 'completed');
   const active = revision ? roadmap({ id: 'plan2', base_active_id: 'plan1', summary: 'Moved the next session to Thursday.', assignments: [...(done ? [done] : []), { ...firstPlan.assignments[0], id: 'a2', key: 'a2', date: '2030-01-10', start_time: '18:00', task: 'Add input validation to the endpoint.' }] }) : firstPlan;
   state = { ...state, version: state.version + 1, planner: { ...state.planner, active, active_review: review(active), month_candidate: null, month_blocks: [{ id: revision ? 'month-2' : 'month-1', month: '2030-01' }], signals: [] } };
   return respond(route, state);
  }
  if (path === '/planner/tasks/status') {
   const active = { ...state.planner.active!, assignments: state.planner.active!.assignments.map(a => a.id === body.task_id ? { ...a, status: body.status === 'completed' ? 'completed' as const : 'scheduled' as const, evidence_note: body.evidence_note, completed_at: '2030-01-09T12:00:00+00:00' } : a) };
   state = { ...state, version: state.version + 1, planner: { ...state.planner, active, active_review: { ...review(active), next_assignment_id: null }, signals: [{ kind: 'progress', message: 'You’ve completed 1 session(s) since this roadmap was prepared.' }] } };
   return respond(route, state);
  }
  return respond(route, state);
 });

 await page.goto('/roadmap');
 await expect(page.getByRole('heading', { name: 'What elo will use' })).toBeVisible();
 await expect(page.getByRole('heading', { name: 'Plan helper' })).toBeVisible();
 await expect(page.getByRole('textbox', { name: 'Answer here' })).not.toBeFocused();
 const beside = async () => (await page.getByRole('region', { name: 'Chat helper' }).boundingBox())!.x > (await page.locator('.plan-road').boundingBox())!.x + 200;
 await page.setViewportSize({ width: 1920, height: 1080 });
 expect(await page.locator('.roadmap-workspace').evaluate(el => innerWidth - el.getBoundingClientRect().right)).toBeLessThanOrEqual(64);
 expect(await beside()).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-planner-wide.png'), fullPage: true });
 await page.setViewportSize({ width: 1280, height: 900 });
 expect(await beside()).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-planner.png'), fullPage: true });
 await page.setViewportSize({width:1440,height:1000}); await page.screenshot({path:test.info().outputPath('roadmap-planner-1440.png'),fullPage:true});
 await expect(page.locator('.road-stop[aria-current="step"]')).toContainText('and finish by');
 await page.setViewportSize({ width: 390, height: 844 });
 await page.screenshot({path:test.info().outputPath('roadmap-planner-390.png'),fullPage:true});
 expect(await noOverflow(page)).toBe(true);
 await page.setViewportSize({ width: 1280, height: 900 });
 await expect(page.getByRole('button', { name: 'Generate roadmap' })).toBeDisabled();
 expect(generations).toBe(0);

 await expect(page.getByRole('heading', { name: 'When would you like to be ready?' })).toBeVisible();
 await expect(page.getByRole('button', { name: 'Send message' })).toBeInViewport({ ratio: 1 });
 await page.getByRole('textbox', { name: 'Answer here' }).fill('Five hours a week until 27 January, with Sunday as backup.');
 await page.getByRole('button', { name: 'Send message' }).click();
 await expect(page.getByRole('log')).toContainText('I added those to the planner');
 await expect(page.getByLabel('Target date')).toHaveValue('2030-01-27');
 await page.screenshot({ path: test.info().outputPath('roadmap-helper.png'), fullPage: false });
 await page.setViewportSize({ width: 390, height: 844 });
 await expect(page.getByRole('region', { name: 'Chat helper' })).toHaveCount(0);
 expect(await noOverflow(page)).toBe(true);
 await page.getByRole('button', { name: 'Continue with chat helper' }).click();
 await expect(page.getByRole('region', { name: 'Chat helper' })).toBeVisible();
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-helper-mobile.png') });
 await page.getByRole('button', { name: 'Close chat helper' }).click();
 await page.getByRole('button', { name: 'Add blocked-out time' }).click();
 const blackout = page.getByRole('group', { name: 'Blackout 2' });
 await blackout.getByLabel('Blackout 2 repeats').selectOption('monthly');
 await expect(blackout).toContainText('18:00–20:00');
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-blackout-mobile.png'), fullPage: true });
 await blackout.getByRole('button', { name: 'Remove blackout 2' }).click();
 await page.setViewportSize({ width: 1280, height: 900 });
 const runwaySection = page.getByRole('region', { name: 'Your runway' });
 await expect(runwaySection).toContainText('2 weeks, 5 days');
 await expect(runwaySection).toContainText('+2 hours (not enabled)');
 await page.getByRole('checkbox', { name: 'Allow backup blocks when preferred time runs out' }).check();
 await expect(runwaySection).toContainText('13 hours 30 minutes');
 await page.screenshot({ path: test.info().outputPath('roadmap-configure.png'), fullPage: true });

 await page.getByRole('button', { name: 'Generate roadmap' }).click();
 await expect(page.getByRole('heading', { name: 'Review your milestone outline' })).toBeVisible();
 await expect(page.getByRole('group', { name: 'Milestone 1' }).getByLabel('Title')).toHaveValue('Build a Python API');
 expect(months).toBe(0);
 await page.screenshot({ path: test.info().outputPath('roadmap-review.png'), fullPage: true });
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-review-mobile.png'), fullPage: true });
 await page.setViewportSize({ width: 1280, height: 900 });
 await page.getByRole('button', { name: 'Accept outline' }).click();
 await expect(page.getByRole('heading', { name: 'Your milestone outline' })).toBeVisible();
 await page.getByRole('button', { name: 'Change planning settings' }).click();
 await expect(page.getByRole('heading', { name: 'Your runway' })).toBeVisible();
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.setViewportSize({ width: 1280, height: 900 });
 await page.getByRole('button', { name: 'Return to roadmap' }).click();
 await page.getByLabel('Month', { exact: true }).fill('2030-01');
 await page.getByRole('button', { name: 'Generate month preview' }).click();
 await expect(page.getByRole('heading', { name: 'Preview for 2030-01' })).toBeVisible();
 await expect(page.getByText('Write one tested Python endpoint.', { exact: true })).toBeVisible();
 expect(state.planner.active).toBeNull();
 await page.getByRole('button', { name: 'Accept month' }).click();
 await expect(page.getByRole('navigation', { name: 'Roadmap views' })).toBeVisible();
 for (const view of ['Today', 'Week', 'Month', 'Milestones', 'Progress']) {
  await page.getByRole('navigation', { name: 'Roadmap views' }).getByRole('button', { name: view, exact: true }).click();
  await page.screenshot({ path: test.info().outputPath(`roadmap-${view.toLowerCase()}.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await noOverflow(page)).toBe(true);
  await page.screenshot({ path: test.info().outputPath(`roadmap-${view.toLowerCase()}-mobile.png`), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
 }
 await page.getByRole('navigation', { name: 'Roadmap views' }).getByRole('button', { name: 'Today', exact: true }).click();
 await page.getByRole('button', { name: 'Mark done: Write one tested Python endpoint.' }).click();
 await expect(page.getByRole('button', { name: 'Mark not done: Write one tested Python endpoint.' })).toHaveAttribute('aria-pressed', 'true');
 await page.reload();
 await expect(page.getByRole('button', { name: 'Mark not done: Write one tested Python endpoint.' })).toBeVisible();
 await page.getByRole('button', { name: /Plan settings/ }).click();
 await page.getByLabel('Weekly budget in hours').fill('4');
 await expect(page.getByText('All changes saved')).toBeVisible();
 await page.reload();
 await page.getByRole('button', { name: /Plan settings/ }).click();
 await expect(page.getByLabel('Weekly budget in hours')).toHaveValue('4');
 await page.getByRole('button', { name: 'Preview updated roadmap' }).click();
 await expect(page.getByRole('heading', { name: 'Review your milestone outline' })).toBeVisible();
 expect(state.planner.active!.id).toBe('plan1');
 await page.getByRole('button', { name: 'Accept outline' }).click();
 await page.getByRole('button', { name: 'Revise 2030-01' }).click();
 await expect(page.getByText('Add input validation to the endpoint.', { exact: true })).toBeVisible();
 await expect(page.getByText(/Completed, started, edited, removed and note-bearing work remains saved/)).toBeVisible();
 expect(state.planner.active!.id).toBe('plan1');
 await page.getByRole('button', { name: 'Accept month' }).click();
 await expect(page.getByRole('navigation', { name: 'Roadmap views' })).toBeVisible();
 expect(state.planner.active!.id).toBe('plan2');
 await page.getByRole('button', { name: /Plan settings/ }).click();
 await page.setViewportSize({ width: 390, height: 844 });
 if (!await page.getByRole('region', { name: 'Chat helper' }).isVisible()) await page.getByRole('button', { name: 'Continue with chat helper' }).click();
 await expect(page.getByRole('textbox', { name: 'Ask for a change' })).toBeVisible();
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 expect(generations).toBe(2);
 expect(months).toBe(2);
 expect(requests.filter(request => request.includes('/planner/roll-forward'))).toHaveLength(0);
});

test('a date field stays inside its border while editing, and a date problem shows only the field', async ({ page }) => {
 await page.setViewportSize({ width: 1280, height: 900 });
 await signIn(page);
 const state = workspace({ planner: { ...blankPlanner(), config: config({ start_date: '2030-01-09' }), runway: runway({ can_generate: false, issues: [{ code: 'start_in_past', message: 'Choose a start date from today onwards.' }] }) } });
 await page.route('**/api/v1/roadmaps/**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/planner/runway') ? state.planner.runway : state }));
 await page.goto('/roadmap');
 const field = page.getByLabel('Start date');
 const token = page.locator('.date-token').first();
 await field.focus();
 await expect(token).toHaveClass(/warn/);
 const [inner, outer] = [await field.boundingBox(), await token.boundingBox()];
 expect(inner!.x).toBeGreaterThanOrEqual(outer!.x);
 expect(inner!.y).toBeGreaterThanOrEqual(outer!.y);
 expect(inner!.x + inner!.width).toBeLessThanOrEqual(outer!.x + outer!.width + .5);
 expect(inner!.y + inner!.height).toBeLessThanOrEqual(outer!.y + outer!.height + .5);
 const content = page.locator('.road-stop[aria-current="step"] .road-content');
 if (await content.count()) await expect(content).toHaveCSS('box-shadow', 'none');
 await page.screenshot({ path: test.info().outputPath('date-focus.png') });
 await page.getByRole('button', { name: /Skills profile/ }).click();
 await page.keyboard.press('Escape');
 await expect(page.locator('.use-panel')).toHaveCount(0);
});

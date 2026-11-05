import { test, expect, type Page } from '@playwright/test';
import type { ActiveView, PlanAssignment, PlannedRoadmap, Proposal, Workspace } from '../../src/features/roadmap/types';
import { activeView, blankPlanner, candidateView, config, review, roadmap, runway, task, workspace } from '../fixtures/roadmap-workspace';

function initial(): Workspace { return workspace({ planner: { ...blankPlanner(), inputs: { goal: { role: 'Backend developer', target_type: 'specific_job', skills: [{ name: 'Python' }] }, cv: { id: 'synthetic-cv', name: 'synthetic-cv.docx' }, skills: [{ ref: 'cv:skill', name: 'Git', kind: 'skill', text: 'Used Git on a synthetic project.' }], experience: [{ ref: 'cv:project', name: 'Synthetic API project', kind: 'project', text: 'Built an API.' }], skill_groups: { Git: 'Tools' } } } }); }

async function signIn(page: Page) {
 await page.addInitScript(() => { localStorage.setItem('elo.access-epoch', '1'); sessionStorage.setItem('elo.session', JSON.stringify({ token: 'synthetic-session', epoch: '1' })); });
 await page.route('**/api/v1/profile**', route => { const path = new URL(route.request().url()).pathname;
  return route.fulfill({ json: path.endsWith('/auth-config') ? { mode: 'email', google_enabled: false } : path.endsWith('/auth/session') ? { id: 'synthetic-owner', name: 'Synthetic User', email_verified: true, provider: 'email' } : { version: 1, onboarding_complete: true, occupational_status: 'employed', education: {} } }); });
}
const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

const secondTask = () => task({ id: 'a2', key: 'a2', task: 'Add input validation to the endpoint.', completion_criterion: 'Bad requests return errors.', week_start: '2030-01-14', date: '2030-01-14', start_time: '19:00', baseline: '2030-01-14 19:00' });
const firstPlan = (): PlannedRoadmap => roadmap({ assignments: [task(), secondTask()] });
const effect = (summary: string, extra: Partial<Proposal['effect']> = {}): Proposal['effect'] => ({ summary, finish_before: '2030-02-17', finish_after: '2030-02-24', target_before: '2030-01-27', target_after: '2030-01-27', capacity_before_minutes: 552, capacity_after_minutes: 312, tasks_moved: [], tasks_backlogged: [], tasks_added: [], tasks_removed: [], decisions: [], warnings: [], week_start: null, workload_before_minutes: null, workload_after_minutes: null, uses_buffer: false, add_block_suggested: false, ...extra });

test('chat helper fills the planner, then generate, review, accept and run the weekly planner', async ({ page }) => {
 await signIn(page);
 let state = initial(), generations = 0, modelMessages = 0, overrides: Partial<ActiveView> = {};
 const respond = (route: Parameters<Parameters<Page['route']>[1]>[0], body: unknown, status = 200) => route.fulfill({ status, json: body });
 /** Save a changed plan the way the service would: one new version, with the page's numbers recalculated. */
 const save = (plan: PlannedRoadmap, extra: Partial<Workspace['planner']> = {}) => { state = { ...state, version: state.version + 1, planner: { ...state.planner, active: plan, active_review: review(plan), active_view: activeView(plan, overrides), ...extra } }; return state; };
 const current = () => state.planner.active as PlannedRoadmap;
 const update = (id: string, change: Partial<PlanAssignment>) => ({ ...current(), revision: current().revision + 1, assignments: current().assignments.map(item => item.id === id ? { ...item, ...change } : item) });
 await page.route('**/api/v1/roadmaps/**', async route => {
  const path = new URL(route.request().url()).pathname.replace('/api/v1/roadmaps', '');
  if (route.request().method() === 'GET') return respond(route, path.startsWith('/history/') ? firstPlan() : state);
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
   const candidate = generations === 1 ? firstPlan() : roadmap({ id: 'plan2', base_active_id: 'plan1', summary: 'A second roadmap towards the same goal.', assignments: [task({ id: 'n1', key: 'n1', task: 'Harder endpoint work.' })], changes: { completed_preserved: 0, assignments_added: ['Harder endpoint work.'], assignments_moved: [], assignments_removed: [], milestones_added: [], milestones_moved: [], milestones_removed: [] } });
   state = { ...state, version: state.version + 1, operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' }, assessment: candidate.assessment, planner: { ...state.planner, candidate, candidate_review: review(candidate), candidate_view: candidateView(candidate) } };
   return respond(route, { version: state.version, operation: state.operation }, 202);
  }
  if (path === '/planner/accept') {
   const next = state.planner.candidate!, previous = state.planner.active as PlannedRoadmap | null;
   const archived = previous ? [{ id: 'archive1', schema_version: 'roadmap-v3', role: 'Backend developer', summary: previous.summary, start_date: '2030-01-09', target_date: '2030-01-27', archived_at: '2030-01-11', completed_minutes: 60, planned_minutes: 240, tasks_completed: 1, tasks_total: 2, milestones_completed: 0, milestones_total: 1 }] : [];
   overrides = {};
   return respond(route, save(next, { candidate: null, candidate_review: null, candidate_view: null, signals: [], archived }));
  }
  if (path === '/planner/assignments/status') return respond(route, save(update(body.assignment_id, { status: body.status, completed_at: '2030-01-09T12:00:00+00:00' })));
  if (path === '/planner/tasks/update') return respond(route, save(update(body.task_id, { feedback: body.feedback })));
  if (path === '/planner/tasks/move') {
   if (body.start_time === '19:00' && body.date === '2030-01-14') return respond(route, { detail: 'Another task already occupies that time. Choose another placement.', code: 'slot_occupied' }, 409);
   return respond(route, save(update(body.task_id, { date: body.date, start_time: body.start_time, week_start: '2030-01-14', action_needed: null })));
  }
  if (path === '/planner/tasks/custom') { const added = task({ id: 'c1', key: 'c1', origin: 'custom', kind: 'custom', milestone_key: null, task: body.title, duration_minutes: body.duration_minutes, week_start: body.week_start, status: 'backlog', date: null, start_time: null, completion_criterion: null, backlog_reason: 'No time chosen yet.', baseline: null, count_hours: body.count_hours }); return respond(route, save({ ...current(), assignments: [...current().assignments, added] })); }
  if (path === '/planner/events/undo') { const plan = update('a2', { date: '2030-01-08', start_time: '19:00', week_start: '2030-01-07', auto_moves: 0, action_needed: { reason: 'undone', message: 'You undid the automatic move. Choose what to do with it.', occurrence: '2030-01-08' } }); return respond(route, save({ ...plan, events: plan.events.map(item => ({ ...item, undone: true })) })); }
  if (path === '/planner/checkins/answer') { overrides = { ...overrides, checkin: { ...overrides.checkin!, status: 'answered', answers: { week_feel: body.week_feel, next_week: body.next_week, note: body.note } } }; return respond(route, save(current())); }
  if (path === '/planner/checkins/propose') { overrides = { ...overrides, checkin: { ...overrides.checkin!, status: 'proposed' } }; save(current(), { proposal: { id: 'checkin1', kind: 'checkin', base_revision: 0, created_at: '2030-01-11', message: 'Eased next week after a busy one.', week_start: '2030-01-07', effect: effect('Next week’s workload becomes 3 hours.', { workload_before_minutes: 240, workload_after_minutes: 180 }) } }); state = { ...state, operation: { id: body.mutation_id, status: 'succeeded', stage: 'complete' } }; return respond(route, { version: state.version, operation: state.operation }, 202); }
  if (path === '/planner/proposals/pause') return respond(route, save(current(), { proposal: { id: 'pause1', kind: 'pause', base_revision: 0, created_at: '2030-01-11', message: null, week_start: body.week_start, effect: effect('Pause the week of 2030-01-21. Your target date stays the same.', { tasks_moved: ['Add input validation to the endpoint.'] }) } }));
  if (path === '/planner/proposals/edit') return respond(route, save(current(), { proposal: { id: 'edit1', kind: 'edit', base_revision: 0, created_at: '2030-01-11', message: null, week_start: null, effect: effect('Update this roadmap’s settings. Your progress and history stay as they are.', { tasks_moved: ['Add input validation to the endpoint.'] }) } }));
  if (path === '/planner/proposals/accept') {
   const proposal = state.planner.proposal!;
   if (proposal.kind === 'checkin') overrides = { ...overrides, checkin: null };
   const plan = proposal.kind === 'pause' ? { ...current(), week_states: { '2030-01-21': { paused: true, exception_task_ids: [], workload_minutes: null, workload_source: null } } } : current();
   return respond(route, save(plan, { proposal: null }));
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

 // Accepted: the page follows the weekly-planner order, with the next task first.
 const today = page.getByRole('region', { name: 'Today' });
 const name = 'Write one tested Python endpoint.';
 await expect(page.getByRole('heading', { name: 'Coach' })).toBeVisible();
 await expect(page.getByRole('region', { name: 'Weekly roadmap' })).toContainText('Target date: Sun, 27 Jan 2030');
 await page.screenshot({ path: test.info().outputPath('roadmap-active.png'), fullPage: true });
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.screenshot({ path: test.info().outputPath('roadmap-active-mobile.png'), fullPage: true });
 await page.setViewportSize({ width: 1280, height: 900 });

 // Moving a task explains a clash in place, and a free time saves.
 await today.getByRole('button', { name: `Move ${name}` }).click();
 const moveForm = today.getByRole('form', { name: `Move ${name}` });
 await moveForm.getByLabel('Date').fill('2030-01-14');
 await moveForm.getByRole('button', { name: 'Save time' }).click();
 await expect(moveForm.getByRole('alert')).toContainText('Another task already occupies that time');
 await moveForm.getByLabel('Time').fill('20:00');
 await moveForm.getByRole('button', { name: 'Save time' }).click();
 await expect(today).toContainText('Mon, 14 Jan 2030, 20:00–21:00');

 // Completion is one click, and feedback is optional.
 await today.getByRole('button', { name: `Complete ${name}` }).click();
 const feedback = today.getByRole('group', { name: `How was ${name}?` });
 await feedback.getByRole('button', { name: 'Too hard' }).click();
 await expect(page.locator('.active-progress')).toContainText('1 h of 4 h');

 // A custom task with no time waits in Backlog.
 const weekly = page.getByRole('region', { name: 'Weekly roadmap' });
 await weekly.getByRole('button', { name: 'Add task to the week of Mon, 7 Jan 2030' }).click();
 const addForm = weekly.getByRole('form', { name: /Add a task to the week of/ });
 await addForm.getByLabel('Title').fill('Mock interview with a friend');
 await addForm.getByRole('button', { name: 'Add task' }).click();
 const backlog = page.getByRole('region', { name: 'Backlog' });
 await expect(backlog).toContainText('Mock interview with a friend');
 await expect(backlog).toContainText('No time chosen yet.');
 expect(await noOverflow(page)).toBe(true);

 // On the next access a missed task has moved. Undo restores it and asks the user.
 overrides = { ...overrides };
 const moved = update('a2', { date: '2030-01-16', start_time: '19:00', auto_moves: 1 });
 save({ ...moved, events: [{ id: 'auto:a2', type: 'auto_move', at: '2030-01-09T00:00:00+00:00', task_id: 'a2', message: 'Moved to Wednesday 19:00', undo: {}, undone: false }] });
 await page.reload();
 const coach = page.getByRole('region', { name: 'Coach' });
 await expect(coach).toContainText('Moved to Wednesday 19:00');
 await coach.getByRole('button', { name: 'Undo: Moved to Wednesday 19:00' }).click();
 await expect(coach).toContainText('You undid the automatic move');
 await expect(coach.getByRole('button', { name: /^Undo/ })).toHaveCount(0);

 // The weekly check-in saves answers, then shows a proposal to accept.
 overrides = { ...overrides, checkin: { week_start: '2030-01-07', status: 'open', opens_at: '2030-01-11T18:00', expires_at: '2030-01-14T19:00', recap: { planned_minutes: 60, completed_minutes: 60, remaining_minutes: 0, due_minutes: 60, completed_due_minutes: 60, moved: ['Moved to Wednesday 19:00'], skipped: [], suggest_less: false }, answers: null, next_week: '2030-01-14', next_week_target_minutes: 240 } };
 save(current());
 await page.reload();
 const checkin = page.getByRole('region', { name: 'Weekly check-in' });
 await checkin.getByRole('radio', { name: 'Busier than usual' }).check();
 await checkin.getByRole('radio', { name: 'Less' }).check();
 await checkin.getByRole('textbox', { name: /Anything to add/ }).fill('Exams next week.');
 await page.screenshot({ path: test.info().outputPath('roadmap-checkin.png'), fullPage: true });
 await checkin.getByRole('button', { name: 'Save and prepare a proposal' }).click();
 const checkinProposal = page.getByRole('region', { name: 'Next week’s workload becomes 3 hours.' });
 await expect(checkinProposal).toContainText('Eased next week after a busy one.');
 await expect(checkinProposal).toContainText('3 h (was 4 h)');
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 await page.setViewportSize({ width: 1280, height: 900 });
 await checkinProposal.getByRole('button', { name: 'Accept changes' }).click();
 await expect(checkinProposal).toHaveCount(0);
 await expect(page.getByRole('region', { name: 'Weekly check-in' })).toHaveCount(0);

 // Pausing previews the effect first.
 await page.locator('.week-row').nth(2).locator('summary').click();
 await weekly.getByRole('button', { name: 'Pause the week of Mon, 21 Jan 2030' }).click();
 const pause = page.getByRole('region', { name: /Pause the week of 2030-01-21/ });
 await expect(pause).toContainText('Add input validation to the endpoint.');
 await page.screenshot({ path: test.info().outputPath('roadmap-pause-preview.png'), fullPage: true });
 await pause.getByRole('button', { name: 'Accept changes' }).click();
 await expect(page.locator('.week-row').nth(2)).toContainText('Paused');
 await expect(weekly.getByRole('button', { name: 'Unpause the week of Mon, 21 Jan 2030' })).toBeAttached();

 // Edit plan previews changes and applies them only on acceptance.
 await page.getByRole('button', { name: 'Edit plan' }).click();
 await page.getByLabel('Weekly budget in hours').fill('4');
 await page.getByRole('button', { name: 'Preview changes' }).click();
 const edit = page.getByRole('region', { name: /Update this roadmap’s settings/ });
 await expect(edit).toBeVisible();
 expect(generations).toBe(1);
 await edit.getByRole('button', { name: 'Accept changes' }).click();
 await expect(edit).toHaveCount(0);

 // Start new roadmap is pre-filled. The current one stays active until the new one is accepted.
 await page.getByRole('button', { name: 'Start new roadmap' }).click();
 await expect(page.getByLabel('Target date')).toHaveValue('2030-01-27');
 await page.getByRole('button', { name: 'Generate new roadmap' }).click();
 await expect(page.getByText('Your current roadmap stays active until you accept this one.')).toBeVisible();
 expect(state.planner.active!.id).toBe('plan1');
 await page.getByRole('button', { name: 'Accept plan' }).click();
 await expect(page.getByText('Your active roadmap')).toBeVisible();
 await page.getByText('Milestones, projected outcome, gaps and past roadmaps').click();
 const past = page.getByRole('region', { name: 'Past roadmaps' });
 await expect(past).toContainText('1 of 2 tasks');
 await past.getByRole('button', { name: /View past roadmap/ }).click();
 await expect(past.getByRole('region', { name: 'Past roadmap details' })).toContainText('Read-only');
 await page.screenshot({ path: test.info().outputPath('roadmap-secondary.png'), fullPage: true });

 await page.getByRole('button', { name: 'Continue with chat helper' }).click();
 await expect(page.getByRole('textbox', { name: 'Ask for a change' })).toBeVisible();
 await page.setViewportSize({ width: 390, height: 844 });
 expect(await noOverflow(page)).toBe(true);
 expect(generations).toBe(2);
});

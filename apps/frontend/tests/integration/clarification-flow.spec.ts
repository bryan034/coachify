import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import { createLocalAccount } from './account-helpers';

const source = 'Synthetic analyst vacancy. Build reports using Python. Query data using SQL. Work with a team and explain your findings.';
const projectAnswer = 'I wrote the SQL queries. A teammate built the Python application, with guidance from our tutor.';
const workAnswer = 'I checked reporting output under supervision. I do not know the full Python implementation.';

async function confirmAndSelect(page: Page, id: string) {
 const card = page.getByRole('article', { name: `Career target ${id}`, exact: true });
 await card.getByRole('button', { name: 'Confirm target', exact: true }).click();
 await card.getByRole('button', { name: 'Select target', exact: true }).click();
 await expect(card.getByRole('button', { name: 'Selected target', exact: true })).toBeVisible();
}

test('confirmed Career targets drive saved project, work and skill clarification across reloads and target switches', async ({ page, browser }) => {
 test.setTimeout(150_000);
 page.on('dialog', dialog => dialog.accept());
 const account = await createLocalAccount(page, 'Synthetic clarification reviewer');
 const profile = await (await account.get('/api/v1/profile')).json();
 expect((await account.finish({ expected_version: profile.version, occupational_status: 'employed', no_previous_education: true })).ok()).toBeTruthy();
 await page.goto('/career-goal');
 await page.getByRole('textbox', { name: 'Job description', exact: true }).fill(source);
 await page.getByLabel('Target role', { exact: true }).fill('Synthetic data analyst');
 await page.getByLabel('Career field', { exact: true }).fill('Data analytics');
 await page.getByLabel('Skill name 1', { exact: true }).fill('Python');
 await page.getByRole('textbox', { name: /^Exact JD excerpt 1/ }).fill('Build reports using Python.');
 await page.getByRole('button', { name: 'Add skill', exact: true }).click();
 await page.getByLabel('Skill name 2', { exact: true }).fill('SQL');
 await page.getByRole('textbox', { name: /^Exact JD excerpt 2/ }).fill('Query data using SQL.');
 await page.getByRole('button', { name: 'Save target draft', exact: true }).click();
 await expect.poll(async () => (await (await account.get('/api/v1/career/targets')).json()).targets.length).toBe(1);
 const saved = await (await account.get('/api/v1/career/targets')).json();
 const targetId = saved.targets[0].id;
 expect(saved.selection.career_target_id).toBeNull();
 expect(saved.targets[0]).toMatchObject({ status: 'draft', company: null, requirements_source: 'user_reviewed_jd' });
 expect(JSON.stringify(saved.targets)).not.toContain(source);
 const targetCard = page.getByRole('article', { name: `Career target ${targetId}`, exact: true });
 await targetCard.getByRole('button', { name: 'Confirm target', exact: true }).click();
 expect((await (await account.get('/api/v1/career/targets')).json()).selection.career_target_id).toBeNull();
 await targetCard.getByRole('button', { name: 'Select target', exact: true }).click();
 await expect(targetCard.getByRole('button', { name: 'Selected target', exact: true })).toBeVisible();
 await page.reload();
 await expect(page.getByRole('textbox', { name: 'Job description', exact: true })).toHaveValue('');
 await expect(page.getByRole('article', { name: `Career target ${targetId}`, exact: true })).toContainText('Build reports using Python.');

 await page.goto('/cv');
 await page.getByLabel('CV document', { exact: true }).setInputFiles(path.join(process.cwd(), 'tests/fixtures/synthetic-clarification-cv.docx'));
 await page.getByRole('button', { name: 'Upload CV', exact: true }).click();
 let cvId = '';
 await expect.poll(async () => {
  const value = await (await account.get('/api/v1/cv')).json();
  cvId = value.cvs[0]?.id ?? '';
  return value.cvs[0]?.status;
 }, { timeout: 30_000 }).toBe('ready');
 await page.getByRole('button', { name: 'Refresh saved status', exact: true }).click();
 await page.getByRole('article', { name: `CV ${cvId}`, exact: true }).getByRole('button', { name: 'Select for analysis', exact: true }).click();
 await expect(page.getByLabel('Confirmed clarification target', { exact: true })).toContainText('Synthetic data analyst');
 await page.getByRole('button', { name: 'Prepare relevant questions', exact: true }).click();
 const project = page.locator('.cv-question').filter({ has: page.getByRole('heading', { name: 'What did you personally contribute, and what did teammates or guidance cover?', exact: true }) });
 await project.getByLabel('Your explanation', { exact: true }).fill(projectAnswer);
 await project.getByRole('button', { name: 'Save explanation', exact: true }).click();
 await expect(project.getByRole('button', { name: 'Edit explanation', exact: true })).toBeVisible();
 const work = page.locator('.cv-question').filter({ has: page.getByRole('heading', { name: 'What did you personally do in this responsibility, including any assistance or supervision?', exact: true }) });
 await work.getByLabel('Your explanation', { exact: true }).fill(workAnswer);
 await work.getByRole('button', { name: 'Save explanation', exact: true }).click();
 await expect(work.getByRole('button', { name: 'Edit explanation', exact: true })).toBeVisible();
 const afterAnswers = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 while (await page.getByRole('button', { name: 'Skip and continue', exact: true }).count()) {
  const before = await page.getByRole('button', { name: 'Skip and continue', exact: true }).count();
  await page.getByRole('button', { name: 'Skip and continue', exact: true }).first().click();
  await expect(page.getByRole('button', { name: 'Skip and continue', exact: true })).toHaveCount(before - 1);
 }
 const clarified = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 expect(clarified.clarifications).toHaveLength(4);
 expect(clarified.clarifications.filter((q: { status: string }) => q.status === 'answered')).toHaveLength(2);
 expect(clarified.clarifications.filter((q: { status: string }) => q.status === 'skipped')).toHaveLength(1);
 // Python attributed only to a teammate is no longer an active proficiency question.
 expect(clarified.skills.find((skill: { skill_id: string }) => skill.skill_id === 'skill:sql').sources).toEqual(expect.arrayContaining([expect.objectContaining({ attribution: 'personal' })]));
 expect(clarified.effective_version).toBe(afterAnswers.effective_version);
 await page.reload();
 await expect(page.getByRole('button', { name: 'Edit explanation', exact: true })).toHaveCount(2);
 await expect(page.getByRole('button', { name: 'Answer voluntarily', exact: true })).toHaveCount(1);

 // Unrelated personal guidance changes relevance, never the saved contribution.
 await page.goto('/career-goal');
 await page.getByRole('radio', { name: 'Career exploration', exact: true }).check();
 await page.getByLabel('Target role', { exact: true }).fill('Synthetic visual designer');
 await page.getByLabel('Career field', { exact: true }).fill('Design');
 await page.getByLabel('Skill name 1', { exact: true }).fill('Illustration');
 await page.getByLabel('Guidance/context 1 (optional)', { exact: true }).fill('A direction I want to explore, not an employer requirement.');
 await page.getByRole('button', { name: 'Save target draft', exact: true }).click();
 await expect.poll(async () => (await (await account.get('/api/v1/career/targets')).json()).targets.length).toBe(2);
 const targets = await (await account.get('/api/v1/career/targets')).json();
 const exploration = targets.targets.find((target: { id: string }) => target.id !== targetId);
 expect(exploration.skills[0].origin).toBe('user_guidance');
 await confirmAndSelect(page, exploration.id);
 await page.goto('/cv');
 await page.getByRole('button', { name: 'Prepare relevant questions', exact: true }).click();
 await expect(page.getByText('No relevant clarification questions are pending for this target. This does not confirm capability or complete an analysis.', { exact: true })).toBeVisible();
 await expect(page.getByRole('button', { name: 'Edit explanation', exact: true })).toHaveCount(2);
 await expect(page.getByLabel('Confirmed clarification target', { exact: true })).toContainText('Synthetic visual designer');
 const selectedExploration = await (await account.get('/api/v1/career/targets/selected-context')).json();
 expect(selectedExploration).toMatchObject({ id: exploration.id, type: 'career_exploration', confirmed: true });
 const explorationQuestions = await (await account.get(`/api/v1/cv/${cvId}/clarifications`)).json();
 expect(explorationQuestions).toMatchObject({ prepared: true, deferred: false });
 expect(explorationQuestions.context).toEqual(selectedExploration);
 const switched = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 expect(switched.effective_version).toBe(clarified.effective_version);
 expect(switched.clarifications).toEqual(clarified.clarifications);

 await page.goto('/career-goal');
 await page.getByRole('article', { name: `Career target ${targetId}`, exact: true }).getByRole('button', { name: 'Select target', exact: true }).click();
 await expect(page.getByRole('article', { name: `Career target ${targetId}`, exact: true }).getByRole('button', { name: 'Selected target', exact: true })).toBeVisible();
 await page.goto('/cv');
 await page.getByRole('button', { name: 'Prepare relevant questions', exact: true }).click();
 await expect(page.getByRole('button', { name: 'Skip and continue', exact: true })).toHaveCount(0);
 await expect(page.getByLabel('Confirmed clarification target', { exact: true })).toContainText('Synthetic data analyst');
 const selectedAgain = await (await account.get('/api/v1/career/targets/selected-context')).json();
 expect(selectedAgain).toMatchObject({ id: targetId, type: 'specific_job', confirmed: true });
 expect(selectedAgain.selection_version).toBeGreaterThan(selectedExploration.selection_version);
 const returnedQuestions = await (await account.get(`/api/v1/cv/${cvId}/clarifications`)).json();
 expect(returnedQuestions).toMatchObject({ prepared: true, deferred: false });
 expect(returnedQuestions.context).toEqual(selectedAgain);
 await page.getByRole('button', { name: 'Answer voluntarily', exact: true }).first().click();
 const voluntary = page.locator('.cv-question').filter({ has: page.getByRole('button', { name: 'Save explanation', exact: true }) });
 await voluntary.getByLabel('Your explanation', { exact: true }).fill('I do not know my proficiency yet.');
 await voluntary.getByRole('button', { name: 'Save explanation', exact: true }).click();
 await expect(page.getByRole('button', { name: 'Edit explanation', exact: true })).toHaveCount(3);
 const final = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 expect(final.clarifications).toHaveLength(4);
 expect(final.effective_version).toBe(clarified.effective_version);
 expect(final.clarifications.find((question: { answer: string }) => question.answer === 'I do not know my proficiency yet.')).toMatchObject({ interpretation_status: 'ready', resolution: 'unanswerable' });
 const selection = (await (await account.get('/api/v1/cv')).json()).selection;
 const declarations = await (await account.get('/api/v1/profile/capabilities')).json();
 const input = await account.get(`/api/v1/cv/${cvId}/capability-input?expected_version=${final.version}&expected_selection_version=${selection.version}&expected_declarations_version=${declarations.version}`);
 expect(input.ok()).toBeTruthy();
 const snapshot = await input.json();
 expect(snapshot.items.find((item: { kind: string }) => item.kind === 'project').description).toBe(final.original_items.find((item: { kind: string }) => item.kind === 'project').description);
 expect(snapshot.skills.find((skill: { skill_id: string }) => skill.skill_id === 'skill:sql').sources).toEqual(expect.arrayContaining([expect.objectContaining({ attribution: 'personal', evidence: expect.arrayContaining([expect.objectContaining({ excerpt: 'I wrote the SQL queries.' })]) })]));
 const currentTarget = await (await account.get('/api/v1/career/targets/selected-context')).json();
 expect(currentTarget).toMatchObject({ id: targetId, confirmed: true, type: 'specific_job' });
 await page.screenshot({ path: test.info().outputPath('confirmed-target-clarifications.png'), fullPage: true });

 const otherContext = await browser.newContext({ baseURL: process.env.PROFILE_E2E_BASE_URL });
 try {
  const otherPage = await otherContext.newPage();
  const other = await createLocalAccount(otherPage, 'Synthetic separate target owner');
  const otherProfile = await (await other.get('/api/v1/profile')).json();
  expect((await other.finish({ expected_version: otherProfile.version, occupational_status: 'employed', no_previous_education: true })).ok()).toBeTruthy();
  expect((await other.get(`/api/v1/career/targets/${targetId}`)).status()).toBe(404);
  expect((await other.get(`/api/v1/career/targets/${targetId}/confirmed-context?expected_version=${currentTarget.version}`)).status()).toBe(404);
  expect((await other.get(`/api/v1/cv/${cvId}/clarifications`)).status()).toBe(404);
  expect(await (await other.get('/api/v1/career/targets/selected-context')).json()).toBeNull();
 } finally { await otherContext.close(); }
});

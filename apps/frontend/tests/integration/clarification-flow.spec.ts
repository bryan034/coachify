import { openCvReviewTools } from '../fixtures/cv-ui';
import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import { createLocalAccount } from './account-helpers';
import {seedCanonicalGoal,confirmCanonicalGoal} from './canonical-career';

const projectAnswer = 'I wrote the SQL queries. A teammate built the Python application, with guidance from our tutor.';
const workAnswer = 'I checked reporting output under supervision. I do not know the full Python implementation.';

test('confirmed Career targets drive saved project, work and skill clarification across reloads and target switches', async ({ page, browser }) => {
 test.setTimeout(150_000);
 page.on('dialog', dialog => dialog.accept());
 const account = await createLocalAccount(page, 'Synthetic clarification reviewer');
 const profile = await (await account.get('/api/v1/profile')).json();
 expect((await account.finish({ expected_version: profile.version, occupational_status: 'employed', no_previous_education: true })).ok()).toBeTruthy();
 const target=await seedCanonicalGoal(account,{role:'Synthetic data analyst',field:'Data analytics',skills:[{name:'Python',evidence:'Build reports using Python.'},{name:'SQL',evidence:'Query data using SQL.'}]});
 const targetId=target.id;
 const saved=await (await account.get('/api/v1/career/goals/current')).json();
 expect(saved.goal._id).toBe(targetId);
 expect(await (await account.get('/api/v1/career/goals/current/confirmed-context')).json()).toBeNull();
 const initialContext=await confirmCanonicalGoal(page,account,target);
 expect(initialContext).toMatchObject({id:targetId,confirmed:true,role:'Synthetic data analyst'});
 await page.reload();
 await expect(page.getByRole('heading',{name:'Confirmed for CV review',exact:true})).toBeVisible();
 expect(await (await account.get('/api/v1/career/goals/current/confirmed-context')).json()).toEqual(initialContext);

 await page.goto('/cv');await openCvReviewTools(page);
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
 await page.reload();await openCvReviewTools(page);
 await expect(page.getByRole('button', { name: 'Edit explanation', exact: true })).toHaveCount(2);
 await expect(page.getByRole('button', { name: 'Answer voluntarily', exact: true })).toHaveCount(1);

 // An unrelated canonical exploration changes relevance, never the saved contribution.
 const exploration=await seedCanonicalGoal(account,{role:'Synthetic visual designer',field:'Design',target_type:'career_exploration',skills:[{name:'Illustration'}]});
 const explorationGoal=await (await account.get('/api/v1/career/goals/current')).json();
 expect(explorationGoal.goal.target_type).toBe('career_exploration');
 expect(await (await account.get('/api/v1/career/goals/current/confirmed-context')).json()).toBeNull();
 await confirmCanonicalGoal(page,account,exploration);
 await page.goto('/cv');await openCvReviewTools(page);
 await page.getByRole('button', { name: 'Prepare relevant questions', exact: true }).click();
 await expect(page.getByText('No relevant clarification questions are pending for this target. This does not confirm capability or complete an analysis.', { exact: true })).toBeVisible();
 await expect(page.getByRole('button', { name: 'Edit explanation', exact: true })).toHaveCount(2);
 await expect(page.getByLabel('Confirmed clarification target', { exact: true })).toContainText('Synthetic visual designer');
 const selectedExploration = await (await account.get('/api/v1/career/goals/current/confirmed-context')).json();
 expect(selectedExploration).toMatchObject({ id: exploration.id, type: 'career_exploration', confirmed: true });
 const explorationQuestions = await (await account.get(`/api/v1/cv/${cvId}/clarifications`)).json();
 expect(explorationQuestions).toMatchObject({ prepared: true, deferred: false });
 expect(explorationQuestions.context).toEqual(selectedExploration);
 const switched = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 expect(switched.effective_version).toBe(clarified.effective_version);
 expect(switched.clarifications).toEqual(clarified.clarifications);

 const restored=await seedCanonicalGoal(account,{goal_id:targetId,role:'Synthetic data analyst',field:'Data analytics',skills:[{name:'Python',evidence:'Build reports using Python.'},{name:'SQL',evidence:'Query data using SQL.'}]});
 await confirmCanonicalGoal(page,account,restored);
 await page.goto('/cv');await openCvReviewTools(page);
 await page.getByRole('button', { name: 'Prepare relevant questions', exact: true }).click();
 await expect(page.getByRole('button', { name: 'Skip and continue', exact: true })).toHaveCount(0);
 await expect(page.getByLabel('Confirmed clarification target', { exact: true })).toContainText('Synthetic data analyst');
 const selectedAgain = await (await account.get('/api/v1/career/goals/current/confirmed-context')).json();
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
 const currentTarget = await (await account.get('/api/v1/career/goals/current/confirmed-context')).json();
 expect(currentTarget).toMatchObject({ id: targetId, confirmed: true, type: 'specific_job' });
 await page.screenshot({ path: test.info().outputPath('confirmed-target-clarifications.png'), fullPage: true });

 const otherContext = await browser.newContext({ baseURL: process.env.PROFILE_E2E_BASE_URL });
 try {
  const otherPage = await otherContext.newPage();
  const other = await createLocalAccount(otherPage, 'Synthetic separate target owner');
  const otherProfile = await (await other.get('/api/v1/profile')).json();
  expect((await other.finish({ expected_version: otherProfile.version, occupational_status: 'employed', no_previous_education: true })).ok()).toBeTruthy();
  // A context outside this account's current selection is a generic conflict; it reveals no goal data.
  expect((await other.get(`/api/v1/career/goals/${targetId}/confirmed-context?expected_version=${currentTarget.version}`)).status()).toBe(409);
  expect(await (await other.get('/api/v1/career/goals/current/cv-confirmation')).json()).toMatchObject({goal_id:null,confirmed:false,context:null});
  expect((await other.get(`/api/v1/cv/${cvId}/clarifications`)).status()).toBe(404);
  expect(await (await other.get('/api/v1/career/goals/current/confirmed-context')).json()).toBeNull();
 } finally { await otherContext.close(); }
});

import { openCvReviewTools } from '../fixtures/cv-ui';
import { test, expect, type Page } from '@playwright/test';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { createLocalAccount } from './account-helpers';
import { grantPremium } from './plan-fixtures';

async function uploadCv(page: Page, files: Parameters<ReturnType<Page['getByLabel']>['setInputFiles']>[0]) {
 await expect(page.locator('.cv-workspace')).toHaveAttribute('aria-busy', 'false');
 await expect(page.locator('form[aria-busy="true"]')).toHaveCount(0);
 await page.getByLabel('CV document', { exact: true }).setInputFiles(files);
 const upload = page.getByRole('button', { name: 'Upload CV', exact: true });
 await expect(upload).toBeEnabled();
 await upload.click();
}

test('saved CVs retain corrections, keep the active CV and compose manual inputs through real services', async ({ page, browser }) => {
 test.setTimeout(210_000);
 page.setDefaultTimeout(15_000);
 const account = await createLocalAccount(page, 'Synthetic CV reviewer');
 const before = await (await account.get('/api/v1/profile')).json();
 const complete = await account.finish({ expected_version: before.version, occupational_status: 'employed', no_previous_education: true });
 expect(complete.ok()).toBeTruthy();
 await grantPremium(account);
 await page.goto('/cv');await openCvReviewTools(page);
 await page.getByLabel('Capability name', { exact: true }).fill('Public speaking');
 await page.getByLabel('Capability description', { exact: true }).fill('I presented a synthetic class project.');
 await page.getByRole('button', { name: 'Add capability', exact: true }).click();
 await expect(page.getByText('I presented a synthetic class project.', { exact: true })).toBeVisible();

 const source = path.join(process.cwd(), 'tests/fixtures/synthetic-cv.docx');
 await uploadCv(page, source);
 let cvId = '';
 await expect.poll(async () => {
  const value = await (await account.get('/api/v1/cv')).json();
  cvId = value.cvs[0]?.id ?? '';
  return value.cvs[0]?.status;
 }, { timeout: 30_000 }).toBe('ready');
 const initialList = await (await account.get('/api/v1/cv')).json();
 expect(initialList.cvs.some((cv:{id:string})=>cv.id===cvId)).toBe(true);
 await openCvReviewTools(page);
 await page.evaluate(() => window.dispatchEvent(new Event('focus')));
 const saved = page.getByRole('article', { name: `CV ${cvId}`, exact: true });
 await expect(saved.getByText('Active CV',{exact:true})).toBeVisible();
 await expect.poll(async()=>(await (await account.get('/api/v1/cv')).json()).selection.cv_id).toBe(cvId);
 await page.getByRole('button', { name: 'Edit or remove Team dashboard', exact: true }).click();
 const editor = page.getByRole('form', { name: 'Edit Team dashboard', exact: true });
 await editor.getByLabel('Description', { exact: true }).fill('I wrote SQL queries; another teammate implemented the Python application.');
 await editor.getByRole('button', { name: 'Save correction', exact: true }).click();
 await expect(editor).not.toBeVisible();
 await page.reload();await openCvReviewTools(page);
 await expect(page.getByRole('region', { name: 'Projects', exact: true }).locator('.cv-copy')).toHaveText('I wrote SQL queries; another teammate implemented the Python application.');
 await page.getByLabel('Capability name', { exact: true }).fill('Python');
 await page.getByLabel('Capability description', { exact: true }).fill('I used Python in a separate synthetic exercise.');
 await page.getByRole('radio', { name: /Attach to CV evidence: Python/ }).check();
 await page.getByRole('button', { name: 'Add capability', exact: true }).click();
 await expect(page.getByText('I used Python in a separate synthetic exercise.', { exact: true })).toBeVisible();
 await page.screenshot({ path: test.info().outputPath('saved-cv-review.png'), fullPage: true });

 const corrected = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 expect(corrected.profile_version).toBeGreaterThan(0);
 const project = corrected.items.find((item: { kind: string }) => item.kind === 'project');
 expect(project.provenance).toBe('user_corrected');
 const selected = (await (await account.get('/api/v1/cv')).json()).selection;
 const manual = await (await account.get('/api/v1/profile/capabilities')).json();
 const snapshot = await account.get(`/api/v1/cv/${cvId}/capability-input?expected_version=${corrected.version}&expected_selection_version=${selected.version}&expected_declarations_version=${manual.version}`);
 expect(snapshot.ok()).toBeTruthy();
 const input = await snapshot.json();
 expect(input.cv_id).toBe(cvId);
 expect(input.declarations.map((item: { name: string }) => item.name)).toEqual(['Public speaking', 'Python']);
 expect(input.declarations[1].provenance).toBe('user_declared');
 expect(input.declarations[1].attached_to.cv_id).toBe(cvId);
 expect(input.declarations[1].attached_to.item_id).toBe(corrected.items.find((item: { kind: string; title: string }) => item.kind === 'skill' && item.title === 'Python').id);
 expect(input.items.find((item: { id: string }) => item.id === project.id).description).toBe(project.description);
 expect((await account.get(`/api/v1/cv/${cvId}/capability-input?expected_version=0&expected_selection_version=${selected.version}&expected_declarations_version=${manual.version}`)).status()).toBe(409);

 await page.getByRole('button', { name: 'Re-upload this source', exact: true }).click();
 await page.getByLabel('CV document', { exact: true }).setInputFiles(source);
 await page.getByRole('button', { name: 'Re-upload same source', exact: true }).click();
 await expect.poll(async () => {
  const current = await (await account.get(`/api/v1/cv/${cvId}`)).json();
  return current.status === 'ready' && current.extraction_version > corrected.extraction_version;
 }, { timeout: 30_000 }).toBe(true);
 const reprocessed = await (await account.get(`/api/v1/cv/${cvId}`)).json();
 expect(reprocessed.items.find((item: { id: string }) => item.id === project.id).description).toBe(project.description);
 expect((await (await account.get('/api/v1/cv')).json()).cvs).toHaveLength(1);
 await openCvReviewTools(page);

 await uploadCv(page, { name: 'synthetic-cv.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: readFileSync(path.join(process.cwd(), 'tests/fixtures/synthetic-cv-failure.docx')) });
 await expect.poll(async () => {
  const value = await (await account.get('/api/v1/cv')).json();
  return value.cvs.find((item: { id: string }) => item.id !== cvId)?.status;
 }, { timeout: 90_000, intervals: [2_000] }).toBe('failed');
 const finalList = await (await account.get('/api/v1/cv')).json();
 expect(finalList.cvs).toHaveLength(2);
 expect(finalList.cvs.map((item: { file_name: string }) => item.file_name)).toEqual(['synthetic-cv.docx', 'synthetic-cv.docx']);
 expect(finalList.selection.cv_id).toBe(cvId);
 expect((await (await account.get('/api/v1/profile/capabilities')).json()).declarations).toHaveLength(2);
 expect((await (await account.get(`/api/v1/cv/${cvId}/clarifications`)).json()).deferred).toBe(true);

 await openCvReviewTools(page);
 await page.route(/\/api\/v1\/cv(?:\?.*)?$/, route => {
  const url = new URL(route.request().url()); url.searchParams.set('limit', '1');
  return route.continue({url:url.toString()});
 });
 await page.reload(); await openCvReviewTools(page);
 await expect(page.getByLabel('Selected CV', {exact:true})).toHaveText('Active CV: synthetic-cv.docx');
 await expect(page.getByRole('article', {name:`CV ${cvId}`,exact:true})).toHaveCount(0);
 await expect(page.getByRole('region', {name:'CV review',exact:true})).toContainText(`CV ${cvId} · Source Profile version`);
 await expect(page.getByRole('region', {name:'Projects',exact:true}).locator('.cv-copy')).toHaveText(project.description);
 await page.getByRole('button', {name:'Show more saved CVs',exact:true}).click();
 await expect(page.getByRole('article', {name:`CV ${cvId}`,exact:true}).getByText('Active CV',{exact:true})).toBeVisible();
 await expect(page.getByRole('article', {name:`CV ${cvId}`,exact:true}).getByRole('button', {name:'Make active',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button', {name:'Show more saved CVs',exact:true})).toHaveCount(0);

 const otherContext = await browser.newContext({ baseURL: process.env.PROFILE_E2E_BASE_URL });
 try {
  const otherPage = await otherContext.newPage();
  const other = await createLocalAccount(otherPage, 'Synthetic isolated CV owner');
  const otherProfile = await (await other.get('/api/v1/profile')).json();
  expect((await other.finish({ expected_version: otherProfile.version, occupational_status: 'employed', no_previous_education: true })).ok()).toBeTruthy();
  expect((await other.get(`/api/v1/cv/${cvId}`)).status()).toBe(404);
  expect((await other.get(`/api/v1/cv/operations/${reprocessed.operation_id}`)).status()).toBe(404);
  expect((await (await other.get('/api/v1/cv')).json()).cvs).toEqual([]);
 } finally { await otherContext.close(); }
 expect((await page.request.get('/api/v1/cv')).status()).toBe(401);

 const conversationList = await (await account.get(`/api/v1/cv/conversations?cv_id=${cvId}`)).json();
 page.once('dialog', dialog => dialog.accept());
 await page.getByRole('article', {name:`CV ${cvId}`,exact:true}).getByRole('button', {name:'Delete CV',exact:true}).click();
 await expect(page.getByRole('article', {name:`CV ${cvId}`,exact:true})).toHaveCount(0);
 await expect(page.getByLabel('Selected CV', {exact:true})).toContainText('No active CV yet.');
 expect((await account.get(`/api/v1/cv/${cvId}`)).status()).toBe(404);
 for (const chat of conversationList.conversations) expect((await account.get(`/api/v1/cv/conversations/${chat.id}`)).status()).toBe(404);
 expect((await (await account.get('/api/v1/profile/capabilities')).json()).declarations).toHaveLength(2);
 await page.reload();await openCvReviewTools(page);
 await expect(page.getByRole('article', {name:`CV ${cvId}`,exact:true})).toHaveCount(0);
 await expect(page.getByRole('textbox', {name:'Capability name',exact:true})).toBeEnabled();
});

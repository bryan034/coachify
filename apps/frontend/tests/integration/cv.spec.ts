import { openCvReviewTools } from '../fixtures/cv-ui';
import { test, expect } from '@playwright/test';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { createLocalAccount } from './account-helpers';

test('saved CVs retain corrections, require explicit selection and compose manual inputs through real services', async ({ page, browser }) => {
 test.setTimeout(120_000);
 const account = await createLocalAccount(page, 'Synthetic CV reviewer');
 const before = await (await account.get('/api/v1/profile')).json();
 const complete = await account.finish({ expected_version: before.version, occupational_status: 'employed', no_previous_education: true });
 expect(complete.ok()).toBeTruthy();
 await page.goto('/cv');await openCvReviewTools(page);
 await page.getByLabel('Capability name', { exact: true }).fill('Public speaking');
 await page.getByLabel('Capability description', { exact: true }).fill('I presented a synthetic class project.');
 await page.getByRole('button', { name: 'Add capability', exact: true }).click();
 await expect(page.getByText('I presented a synthetic class project.', { exact: true })).toBeVisible();

 const source = path.join(process.cwd(), 'tests/fixtures/synthetic-cv.docx');
 await page.getByLabel('CV document', { exact: true }).setInputFiles(source);
 await page.getByRole('button', { name: 'Upload CV', exact: true }).click();
 let cvId = '';
 await expect.poll(async () => {
  const value = await (await account.get('/api/v1/cv')).json();
  cvId = value.cvs[0]?.id ?? '';
  return value.cvs[0]?.status;
 }, { timeout: 30_000 }).toBe('ready');
 const initialList = await (await account.get('/api/v1/cv')).json();
 expect(initialList.selection.cv_id).toBeNull();
 await page.getByRole('button', { name: 'Refresh saved status', exact: true }).click();
 const saved = page.getByRole('article', { name: `CV ${cvId}`, exact: true });
 await saved.getByRole('button', { name: 'Select for analysis', exact: true }).click();
 await expect(saved.getByRole('button', { name: 'Selected', exact: true })).toBeVisible();
 await page.getByRole('button', { name: 'Edit or remove Team dashboard', exact: true }).click();
 const editor = page.getByRole('form', { name: 'Edit Team dashboard', exact: true });
 await editor.getByLabel('Description', { exact: true }).fill('I wrote SQL queries; another teammate implemented the Python application.');
 await editor.getByRole('button', { name: 'Save correction', exact: true }).click();
 await expect(editor).not.toBeVisible();
 await page.reload();await openCvReviewTools(page);
 await expect(page.getByRole('region', { name: 'Projects', exact: true }).locator('.cv-copy')).toHaveText('I wrote SQL queries; another teammate implemented the Python application.');
 // Exercise the real Profile -> CV -> Profile authenticated reference check.
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

 // Re-supply the exact source to the existing CV. The new extraction must keep
 // its correction overlay, source identity and explicit selection.
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

 // A model boundary failure on a different CV must not replace selected input.
 await page.getByLabel('CV document', { exact: true }).setInputFiles({ name: 'synthetic-cv.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: readFileSync(path.join(process.cwd(), 'tests/fixtures/synthetic-cv-failure.docx')) });
 await page.getByRole('button', { name: 'Upload CV', exact: true }).click();
 await expect.poll(async () => {
  const value = await (await account.get('/api/v1/cv')).json();
  return value.cvs.find((item: { id: string }) => item.id !== cvId)?.status;
 }, { timeout: 30_000 }).toBe('failed');
 const finalList = await (await account.get('/api/v1/cv')).json();
 expect(finalList.cvs).toHaveLength(2);
 expect(finalList.cvs.map((item: { file_name: string }) => item.file_name)).toEqual(['synthetic-cv.docx', 'synthetic-cv.docx']);
 expect(finalList.selection.cv_id).toBe(cvId);
 expect((await (await account.get('/api/v1/profile/capabilities')).json()).declarations).toHaveLength(2);
 expect((await (await account.get(`/api/v1/cv/${cvId}/clarifications`)).json()).deferred).toBe(true);

 // A different authenticated account sees neither the original nor its saved
 // operation, and an unsigned request cannot enumerate sources.
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
});

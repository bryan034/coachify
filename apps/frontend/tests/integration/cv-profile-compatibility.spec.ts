import { openCvReviewTools } from '../fixtures/cv-ui';
import { test, expect } from '@playwright/test';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { createLocalAccount } from './account-helpers';

const lastSchool = { institution: { kind: 'custom', name: 'Synthetic Polytechnic', country_code: 'SG' }, course: 'Synthetic computing diploma' };
const cases = [
  { name: 'student', profile: { occupational_status: 'student', school_category: 'university', education: { ...lastSchool, study_year: 2 } }, edit: { education: { course: 'Updated synthetic course' } } },
  { name: 'national service', profile: { occupational_status: 'national_service', school_category: 'polytechnic', education: lastSchool }, edit: { education: { course: 'Updated synthetic course' } } },
  { name: 'employed', profile: { occupational_status: 'employed', no_previous_education: true }, edit: { employment: { role: 'Updated synthetic role' } } },
  { name: 'unemployed with previous work', profile: { occupational_status: 'unemployed', previously_employed: true, no_previous_education: true, employment: { employer: 'Synthetic former employer', role: 'Synthetic former analyst', industry: 'Synthetic industry' } }, edit: { employment: { role: 'Updated synthetic former role' } } },
  { name: 'unemployed seeking first job', profile: { occupational_status: 'unemployed', previously_employed: false, school_category: 'polytechnic', education: { ...lastSchool, graduation_year: 2024 } }, edit: { education: { course: 'Updated synthetic course' } } },
];

for (const scenario of cases) {
  test(`C-series upload and declarations work with ${scenario.name} Profile data`, async ({ page }) => {
    test.setTimeout(90_000);
    const account = await createLocalAccount(page, `Synthetic ${scenario.name} CV owner`);
    const initial = await (await account.get('/api/v1/profile')).json();
    const completion = await account.finish({ expected_version: initial.version, ...scenario.profile });
    expect(completion.ok()).toBeTruthy();
    const background = await (await account.get('/api/v1/profile')).json();
    expect(background.onboarding_complete).toBe(true);

    await page.goto('/cv');await openCvReviewTools(page);
    await page.getByLabel('Capability name', { exact: true }).fill('Public speaking');
    await page.getByLabel('Capability description', { exact: true }).fill('I presented a synthetic group project.');
    await page.getByRole('button', { name: 'Add capability', exact: true }).click();
    await expect(page.getByText('I presented a synthetic group project.', { exact: true })).toBeVisible();
    // C07 must not overwrite education, employment, completion or the Profile revision.
    expect(await (await account.get('/api/v1/profile')).json()).toEqual(background);

    // All synthetic accounts share one gateway IP. Pace this extra branch matrix
    // to the real six-uploads/minute policy instead of relaxing the gateway limit.
    await delay(10_100);
    await page.getByLabel('CV document', { exact: true }).setInputFiles(path.join(process.cwd(), 'tests/fixtures/synthetic-cv.docx'));
    const upload = page.waitForResponse(response => response.url().endsWith('/api/v1/cv/uploads') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Upload CV', exact: true }).click();
    expect((await upload).status()).toBe(202);
    let cvId = '';
    await expect.poll(async () => {
      const result = await (await account.get('/api/v1/cv')).json();
      cvId = result.cvs[0]?.id ?? '';
      return result.cvs[0]?.status;
    }, { timeout: 30_000 }).toBe('ready');
    await page.getByRole('button', { name: 'Refresh saved status', exact: true }).click();
    await page.getByRole('article', { name: `CV ${cvId}`, exact: true }).getByRole('button', { name: 'Select for analysis', exact: true }).click();
    await expect(page.getByLabel('Selected CV', { exact: true })).toContainText(cvId);
    await expect(page.getByText(`Source Profile version ${background.version}`, { exact: false })).toBeVisible();
    const saved = await (await account.get(`/api/v1/cv/${cvId}`)).json();
    const declarations = await (await account.get('/api/v1/profile/capabilities')).json();
    expect(saved.profile_version).toBe(background.version);

    const edited = await account.patch('/api/v1/profile', { data: { expected_version: background.version, ...scenario.edit }, headers: { 'Idempotency-Key': crypto.randomUUID() } });
    expect(edited.ok()).toBeTruthy();
    const current = await edited.json();
    expect(current.version).toBeGreaterThan(background.version);
    expect(current.onboarding_complete).toBe(true);
    await page.reload();await openCvReviewTools(page);
    await expect(page.getByLabel('Selected CV', { exact: true })).toContainText(cvId);
    await expect(page.getByText('I presented a synthetic group project.', { exact: true })).toBeVisible();
    expect(await (await account.get('/api/v1/profile/capabilities')).json()).toEqual(declarations);
  });
}

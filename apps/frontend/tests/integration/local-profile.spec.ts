import { test, expect } from '@playwright/test';

test('local UI saves to MongoDB and restores after reload without Google', async ({ page }) => {
  // No page.route mocks: browser → gateway → FastAPI → MongoDB.
  const auth = await page.request.get('/api/v1/profile/auth-config');
  expect(await auth.json()).toEqual({ mode: 'local_test' });
  await page.goto('/profile');
  await expect(page.getByRole('button', { name: 'Save background' })).toBeEnabled();
  await expect(page.getByText('Sign in to save and return to your profile.')).toHaveCount(0);
  await page.getByRole('radio', { name: 'Student', exact: true }).check();
  await page.locator('summary').filter({ hasText: /^University/ }).press('Enter');
  await page.getByRole('searchbox', { name: 'Search schools' }).fill('Harvard');
  await page.getByRole('button', { name: 'Select Harvard University', exact: true }).click();
  await expect(page.getByRole('searchbox')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'What course are you studying?' }).fill('Computing & Design');
  await page.getByRole('spinbutton', { name: /Current study level/ }).fill('6');
  const review = page.getByRole('checkbox', { name: /I have reviewed the education details/ });
  if (await review.isVisible()) await review.check();
  const write = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith('/api/v1/profile'));
  await page.getByRole('button', { name: 'Save background' }).click();
  expect((await write).status()).toBe(200);
  await expect(page.getByText('Profile saved.')).toBeVisible();
  const saved = await (await page.request.get('/api/v1/profile')).json();
  expect(saved.education.institution.name).toBe('Harvard University');
  expect(saved.education.course).toBe('Computing & Design');
  expect(saved.current_study_year).toBe(6);
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'What course are you studying?' })).toHaveValue('Computing & Design');
  await expect(page.getByRole('spinbutton', { name: /Current study level/ })).toHaveValue('6');
  await expect(page.getByText('Harvard University', { exact: true })).toBeVisible();
  const historical = await (await page.request.get(`/api/v1/profile/versions/${saved.version}`)).json();
  expect(historical.education).toEqual(saved.education);
});

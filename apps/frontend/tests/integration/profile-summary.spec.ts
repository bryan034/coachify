import { test, expect } from '@playwright/test';
import { createLocalAccount, fillCurrentEmployment } from './account-helpers';

test('employed summary persists work details and development preview never changes them', async ({ page }, testInfo) => {
  const api = await createLocalAccount(page, 'Synthetic summary account');
  await page.getByRole('button', { name: 'Employed', exact: true }).click();
  await fillCurrentEmployment(page);
  await page.getByRole('button', { name: 'No applicable previous education' }).click();
  await page.getByRole('button', { name: 'Enter elo', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole('link', { name: 'My profile', exact: false }).click();
  await expect(page.getByRole('heading', { name: 'Current employment' })).toBeVisible();
  await expect(page.getByText('Synthetic company', { exact: true })).toBeVisible();
  await expect(page.getByText('Synthetic analyst', { exact: true })).toBeVisible();
  await expect(page.getByText('Year of study', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox')).toHaveCount(0);
  const saved = await (await api.get('/api/v1/profile')).json();
  expect(saved.employment).toEqual({ employer: 'Synthetic company', role: 'Synthetic analyst', industry: 'Synthetic industry' });
  await page.screenshot({ path: testInfo.outputPath('profile-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('profile-mobile.png'), fullPage: true });
  await page.getByRole('link', { name: 'Preview onboarding', exact: false }).click();
  await expect(page).toHaveURL(/\/onboarding\/preview$/);
  await expect(page.getByRole('navigation')).toHaveCount(0);
  await page.getByRole('button', { name: 'Student', exact: true }).click();
  await page.getByRole('button', { name: 'Secondary School', exact: true }).click();
  await page.getByRole('button', { name: 'My school isn’t listed' }).click();
  await page.getByRole('textbox', { name: 'School name' }).fill('Synthetic preview school');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'No applicable named course / Skip', exact: true }).click();
  await page.getByRole('button', { name: 'Secondary 2', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Finish preview', exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
  expect(await (await api.get('/api/v1/profile')).json()).toEqual(saved);
  await expect(page.getByText('Synthetic company', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Preview onboarding', exact: false }).click();
  await page.getByRole('button', { name: 'Exit preview', exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
  expect(await (await api.get('/api/v1/profile')).json()).toEqual(saved);
  await page.getByRole('button', { name: 'Edit profile', exact: false }).click();
  await page.getByRole('textbox', { name: 'Role', exact: true }).fill('Discard this draft');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByText('Synthetic analyst', { exact: true })).toBeVisible();
  expect(await (await api.get('/api/v1/profile')).json()).toEqual(saved);
  // Employment also remains editable through the ordinary versioned Profile API.
  await page.getByRole('button', { name: 'Edit profile', exact: false }).click();
  await page.getByRole('textbox', { name: 'Role', exact: true }).fill('Synthetic senior analyst');
  await page.setViewportSize({width:1280,height:1000});
  await page.screenshot({path:testInfo.outputPath('profile-editor-desktop.png'),fullPage:true});
  const fields=page.locator('.profile-editor-label');
  const positions=await fields.evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().x));
  expect(new Set(positions).size).toBe(1);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('profile-editor-mobile.png'),fullPage:true});
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByText('Profile updated.', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByText('Synthetic senior analyst', { exact: true })).toBeVisible();
  expect((await (await api.get('/api/v1/profile')).json()).employment.role).toBe('Synthetic senior analyst');
  await page.reload();
  await expect(page.getByText('Synthetic senior analyst', { exact: true })).toBeVisible();
});

for (const previouslyEmployed of [true, false]) {
  test(`unemployed onboarding persists previous employment: ${previouslyEmployed}`, async ({ page }, testInfo) => {
    const api = await createLocalAccount(page, 'Synthetic work history account');
    await page.setViewportSize({ width: 1280, height: 900 });
    const width = await page.locator('.onboarding-question').evaluate(element => element.getBoundingClientRect().width);
    expect(width).toBeCloseTo(1280 * .75, 0);
    await page.locator('.onboarding-question').evaluate(async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)); });
    await page.screenshot({ path: testInfo.outputPath('onboarding-wide.png'), fullPage: true });
    await page.getByRole('button', { name: 'Unemployed', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Have you worked before?' })).toBeVisible();
    await page.getByRole('button', { name: previouslyEmployed ? 'Yes, I have' : 'No, not yet', exact: true }).click();
    if (previouslyEmployed) {
      await page.getByRole('textbox', { name: 'Previous employer' }).fill('DBS');
      await page.getByRole('button', { name: 'DBS Bank', exact: true }).click();
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
      await page.getByRole('textbox', { name: 'Role', exact: true }).fill('Synthetic previous role');
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
      await page.getByRole('textbox', { name: 'Industry', exact: true }).fill('Synthetic custom industry');
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
    }
    await expect(page.getByRole('heading', { name: 'Your last education path.' })).toBeVisible();
    await page.getByRole('button', { name: 'No applicable previous education' }).click();
    await page.getByRole('button', { name: 'Enter elo', exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.goto('/profile');
    const saved = await (await api.get('/api/v1/profile')).json();
    expect(saved.previously_employed).toBe(previouslyEmployed);
    if (previouslyEmployed) {
      await expect(page.getByRole('heading', { name: 'Previous employment' })).toBeVisible();
      await expect(page.getByText('DBS Bank', { exact: true })).toBeVisible();
      await expect(page.getByText('Synthetic custom industry', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Edit profile', exact: false }).click();
      await page.getByRole('textbox', { name: 'Industry', exact: true }).fill('Edited custom industry');
      await page.getByRole('button', { name: 'Save changes', exact: true }).click();
      await expect(page.getByText('Edited custom industry', { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByText('Edited custom industry', { exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole('heading', { name: 'Previous employment' })).toHaveCount(0);
      expect(saved.employment.employer).toBeNull();
    }
    await expect(page.getByRole('heading', { name: 'Current employment' })).toHaveCount(0);
  });
}

test('never-employed graduate saves graduation year to MongoDB and can edit it after reload', async ({ page }) => {
  const api = await createLocalAccount(page, 'Synthetic graduate account');
  await page.getByRole('button', { name: 'Unemployed', exact: true }).click();
  await page.getByRole('button', { name: 'No, not yet', exact: true }).click();
  await page.getByRole('button', { name: 'University', exact: true }).click();
  await page.getByRole('button', { name: 'My school isn’t listed' }).click();
  await page.getByRole('textbox', { name: 'School name' }).fill('Synthetic graduate institution');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'When did you graduate?' })).toBeVisible();
  await page.getByRole('spinbutton', { name: 'Year of graduation' }).fill('2024');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What course did you study?' })).toBeVisible();
  expect((await (await api.get('/api/v1/profile')).json()).education.graduation_year).toBe(2024);
  await page.getByRole('button', { name: 'No applicable named course / Skip', exact: true }).click();
  await page.getByRole('button', { name: 'Enter elo', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto('/profile');
  await expect(page.getByText('Year of graduation', { exact: true })).toBeVisible();
  await expect(page.getByText('2024', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit profile', exact: false }).click();
  await page.getByRole('spinbutton', { name: 'Year of graduation' }).fill('2023');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByText('2023', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('2023', { exact: true })).toBeVisible();
  const canonical = await (await api.get('/api/v1/profile')).json();
  expect(canonical.education.graduation_year).toBe(2023);
  expect(canonical.education.institution.name).toBe('Synthetic graduate institution');
  expect(canonical.onboarding_complete).toBe(true);
});

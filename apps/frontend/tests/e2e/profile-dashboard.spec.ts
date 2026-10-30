import { test, expect } from '@playwright/test';

test('production profile is a summary and direct onboarding preview stays unavailable', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('elo.access-epoch', '1'); sessionStorage.setItem('elo.session', JSON.stringify({ token: 'synthetic-session', epoch: '1' })); localStorage.setItem('development_tools_enabled','true'); });
  await page.route('**/api/v1/profile**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth-config')) return route.fulfill({ json: { mode: 'email', development_tools_enabled: false } });
    if (path.endsWith('/auth/session')) return route.fulfill({ json: { id: 'synthetic', name: 'Synthetic user', provider: 'email', email_verified: true } });
    if (path.endsWith('/school-categories')) return route.fulfill({ json: [] });
    return route.fulfill({ json: { version: 2, onboarding_complete: true, occupational_status: 'employed', school_category: 'university', education_review_required: false,
      education: { institution: { kind: 'custom', name: 'Synthetic school' }, course: 'Synthetic course', study_year: 3 }, current_study_year: null, employment: { employer: 'Synthetic company', role: 'Synthetic analyst' } } });
  });
  await page.goto('/profile');
  await expect(page.getByRole('heading', { name: 'My profile', exact: true })).toBeVisible();
  await expect(page.getByText('Place of last education', { exact: true })).toBeVisible();
  await expect(page.getByText('Synthetic company', { exact: true })).toBeVisible();
  await expect(page.getByText('Year of study', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Preview onboarding/ })).toHaveCount(0);
  await expect(page.getByRole('textbox')).toHaveCount(0);
  await page.goto('/onboarding/preview?development_tools_enabled=true');
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByRole('heading', { name: 'Where are you right now?' })).toHaveCount(0);
});

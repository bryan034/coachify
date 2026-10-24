import { test, expect } from '@playwright/test';

test('save, reload, browse international schools, switch status and retry', async ({ page }) => {
  // Only the Google and HTTP boundaries are mocked. Production has no test-auth path.
  const categories = [
    { id: 'secondary', label: 'Secondary School' }, { id: 'ite', label: 'Institute of Technical Education' },
    { id: 'polytechnic', label: 'Polytechnic / Diploma' }, { id: 'junior_college', label: 'Junior College' },
    { id: 'university', label: 'University' },
  ];
  let saved = { version: 0, occupational_status: null as string | null, school_category: null as string | null,
    education_context: null as string | null, education_review_required: false, education: {} as Record<string, unknown> };
  let failSave = false;
  await page.route('https://accounts.google.com/gsi/client', route => route.fulfill({ contentType: 'application/javascript', body: `window.google = { accounts: { id: {
    initialize: function(options) { this.callback = options.callback; },
    renderButton: function(el) { const b = document.createElement('button'); b.textContent = 'Sign in with Google (test)'; b.onclick = () => this.callback({ credential: 'test-token' }); el.appendChild(b); }, disableAutoSelect: function() {}
  } } };` }));
  await page.route('**/api/v1/profile**', async route => {
    const url = new URL(route.request().url());
  if (url.pathname.endsWith('/planning-inputs')) return route.fulfill({json:{profile_version:saved.version,planning_revision:0,ready:false,issues:[],availability_periods:[]}});
    if (url.pathname.endsWith('auth-config')) return route.fulfill({ json: { mode: 'google' } });
    if (url.pathname.endsWith('school-categories')) return route.fulfill({ json: categories });
    if (url.pathname.endsWith('school-countries')) return route.fulfill({ json: [{ code: 'US', name: 'United States' }] });
    if (url.pathname.endsWith('institutions')) return route.fulfill({ json: {
      items: [{ id: 'test-harvard', name: 'Harvard University', country: 'United States', country_code: 'US' }], total: 1, offset: 0, limit: 25,
      snapshot_date: '2026-10-24', coverage_note: 'Test directory boundary fixture.',
    } });
    if (route.request().method() === 'PATCH') {
      if (failSave) return route.fulfill({ status: 503, json: { detail: 'Temporary save failure. Retry.' } });
      const input = route.request().postDataJSON();
      if (input.education?.institution?.kind === 'catalogue') input.education.institution = { kind: 'catalogue', id: 'test-harvard', name: 'Harvard University', country_code: 'US' };
      expect(input.expected_version).toBe(saved.version);
      saved = { ...saved, occupational_status: input.occupational_status, school_category: input.school_category,
        education: { ...saved.education, ...input.education },
        version: saved.version + 1, education_context: input.occupational_status === 'student' ? 'current' : 'last', education_review_required: saved.version > 0 };
    }
    return route.fulfill({ json: saved });
  });
  await page.goto('/profile');
  await page.getByRole('button', { name: 'Sign in with Google (test)' }).click();
  await expect(page.getByRole('button', { name: 'Save background' })).toBeEnabled();
  await page.getByRole('radio', { name: 'Student', exact: true }).check();
  await page.getByText('University', { exact: true }).click();
  await page.getByRole('searchbox', { name: 'Search schools' }).fill('Harvard');
  await page.getByRole('combobox', { name: 'Country / territory' }).selectOption('US');
  await expect(page.getByRole('button', { name: 'Select Harvard University' })).toBeVisible();
  await page.getByRole('button', { name: 'Select Harvard University' }).click();
  await page.getByRole('checkbox', { name: 'No applicable named course/programme' }).uncheck();
  await page.getByRole('textbox', { name: 'What course are you studying?' }).fill('Computing & Design');
  await page.getByRole('spinbutton', { name: /Current study level/ }).fill('6');
  await page.getByRole('button', { name: 'Save background' }).click();
  await expect(page.getByText('Profile saved.')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Sign in with Google (test)' }).click();
  await expect(page.getByRole('radio', { name: 'Student', exact: true })).toBeChecked();
  await expect(page.getByRole('textbox', { name: 'What course are you studying?' })).toHaveValue('Computing & Design');
  await expect(page.getByRole('spinbutton', { name: /Current study level/ })).toHaveValue('6');
  await page.getByRole('radio', { name: 'Employed', exact: true }).check();
  await expect(page.getByText('Where did you last study?')).toBeVisible();
  await expect(page.getByText(/Please review your education details/)).toBeVisible();
  await page.getByRole('radio', { name: 'No applicable previous education' }).check();
  failSave = true;
  await page.getByRole('button', { name: 'Save background' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toHaveText('Temporary save failure. Retry.');
  await expect(page.getByRole('radio', { name: 'Employed', exact: true })).toBeChecked();
  failSave = false;
  await page.getByRole('button', { name: 'Save background' }).click();
  await expect(page.getByText('Profile saved.')).toBeVisible();
  // Client-side workspace navigation preserves the in-memory Google identity.
  await page.getByRole('link', { name: 'Home', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to Coachify' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  await page.getByRole('link', { name: 'My profile' }).click();
  await expect(page.getByRole('button', { name: 'Save background' })).toBeEnabled();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Save background' })).toBeDisabled();
  await expect(page.getByRole('radio', { name: 'Student', exact: true })).not.toBeChecked();

});

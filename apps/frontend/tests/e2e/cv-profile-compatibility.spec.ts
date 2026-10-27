import { test, expect, type Page } from '@playwright/test';
import { policy, savedCv, emptyDeclarations, clarificationState, confirmedTarget } from '../fixtures/cv';

async function workspace(page: Page) {
  let sessionStatus = 200;
  let sessionChecks = 0;
  let release: (() => void) | undefined;
  let pending: Promise<void> | undefined;
  const writes: string[] = [];
  const cv = savedCv('profile-compatible-cv');
  cv.profile_version = 3;
  cv.clarifications = [{ id: 'contribution', item_id: cv.items[0].id, kind: 'project', question: 'Which Python work was yours?', uncertainty_key: 'contribution', status: 'unanswered', answer: null, career_target_id: confirmedTarget.id, career_target_version: confirmedTarget.version }];
  await page.addInitScript(() => {
    localStorage.setItem('coachify.access-epoch', '1');
    sessionStorage.setItem('coachify.session', JSON.stringify({ token: 'synthetic-session', epoch: '1' }));
  });
  await page.route('**/api/v1/profile**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth-config')) return route.fulfill({ json: { mode: 'email', google_enabled: false } });
    if (path.endsWith('/auth/logout')) return route.fulfill({ json: { logged_out: true } });
    if (path.endsWith('/auth/session')) {
      sessionChecks++;
      const status = sessionStatus;
      await pending;
      return route.fulfill({ status, json: status === 200 ? { id: 'synthetic-account', name: 'Synthetic User', email_verified: true, provider: 'email' } : { detail: status === 401 ? 'Session expired.' : 'Connection unavailable.' } });
    }
    if (path.endsWith('/school-categories')) return route.fulfill({ json: [] });
    if (path.endsWith('/capabilities')) {
      if (route.request().method() !== 'GET') writes.push(path);
      return route.fulfill({ json: emptyDeclarations });
    }
    return route.fulfill({ json: { version: 3, onboarding_complete: true, occupational_status: 'student', school_category: 'university', education: { institution: { kind: 'custom', name: 'Synthetic university' }, course: 'Computing', study_year: 2 }, employment: {}, education_review_required: false } });
  });
  await page.route('**/api/v1/cv{,/**}', route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET') writes.push(path);
    if (path.endsWith('/policy')) return route.fulfill({ json: policy });
    if (path === '/api/v1/cv') return route.fulfill({ json: { cvs: [cv], selection: { cv_id: cv.id, version: 1 } } });
    if (path.endsWith('/clarifications')) return route.fulfill({ json: clarificationState(cv, confirmedTarget, true) });
    return route.fulfill({ json: cv });
  });
  return {
    writes,
    checks: () => sessionChecks,
    status: (value: number) => { sessionStatus = value; },
    hold: () => { pending = new Promise<void>(resolve => { release = resolve; }); },
    release: () => { release?.(); pending = undefined; },
  };
}

async function visibility(page: Page, state: 'visible' | 'hidden') {
  await page.evaluate(value => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value });
    document.dispatchEvent(new Event('visibilitychange'));
  }, state);
}

async function enterDrafts(page: Page) {
  await page.goto('/cv');
  await expect(page.getByRole('textbox', { name: 'Your explanation' })).toBeEnabled();
  await page.getByRole('button', { name: 'Edit or remove Team dashboard' }).click();
  await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Unsaved correction: I prepared the data.');
  await page.getByRole('textbox', { name: 'Your explanation' }).fill('Unsaved explanation: I wrote the Python cleanup script.');
  await page.getByLabel('Capability name', { exact: true }).fill('Public speaking');
  await page.getByLabel('Capability description', { exact: true }).fill('Unsaved capability: I presented our results.');
  await page.getByLabel('CV document', { exact: true }).setInputFiles({ name: 'draft-cv.pdf', mimeType: 'application/pdf', buffer: Buffer.from('Synthetic unsent upload; boundary APIs are mocked.') });
}

async function expectDrafts(page: Page) {
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Unsaved correction: I prepared the data.');
  await expect(page.getByRole('textbox', { name: 'Your explanation' })).toHaveValue('Unsaved explanation: I wrote the Python cleanup script.');
  await expect(page.getByLabel('Capability name', { exact: true })).toHaveValue('Public speaking');
  await expect(page.getByLabel('Capability description', { exact: true })).toHaveValue('Unsaved capability: I presented our results.');
  expect(await page.getByLabel('CV document', { exact: true }).evaluate((input: HTMLInputElement) => input.files?.[0]?.name)).toBe('draft-cv.pdf');
  await expect(page.getByRole('button', { name: 'Upload CV', exact: true })).toBeEnabled();
}

test('C-series drafts survive tab changes and connection recovery with no idle timeout', async ({ page }) => {
  const session = await workspace(page);
  await page.clock.install();
  await enterDrafts(page);
  await page.getByRole('textbox', { name: 'Your explanation' }).focus();
  const originalChecks = session.checks();
  await visibility(page, 'hidden');
  await page.clock.fastForward(6 * 60_000);
  expect(session.checks()).toBe(originalChecks);
  await expectDrafts(page);

  session.status(503);
  session.hold();
  await visibility(page, 'visible');
  await expect(page.getByRole('heading', { name: 'Checking your session' })).toBeVisible();
  // The private subtree remains mounted, but neither forms nor navigation are available.
  await expect(page.locator('.cv-workspace')).toHaveCount(1);
  await expect(page.getByRole('textbox', { name: 'Your explanation' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Career Goal', exact: true })).toHaveCount(0);
  expect(await page.locator('.cv-workspace').evaluate(element => Boolean(element.closest('[inert]')))).toBe(true);
  expect(session.writes).toEqual([]);
  session.release();
  await expect(page.getByRole('heading', { name: 'Connection interrupted' })).toBeVisible();
  await expect(page.getByText(/Your unsaved work is still in this tab\./)).toBeVisible();

  session.status(200);
  await page.getByRole('button', { name: 'Retry session', exact: true }).click();
  await expectDrafts(page);
  await expect(page.getByRole('textbox', { name: 'Your explanation' })).toBeFocused();
  // A foreground tab may revalidate, but six minutes alone must never discard work or demand refresh.
  await page.clock.fastForward(6 * 60_000);
  await expectDrafts(page);
  await expect(page.getByRole('heading', { name: 'Connection interrupted' })).toHaveCount(0);
  expect(session.writes).toEqual([]);
  const storage = await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]));
  expect(storage).not.toContain('Unsaved');
  await page.screenshot({ path: test.info().outputPath('recovered-cv-drafts.png'), fullPage: true });
});

test('a restored browser page revalidates without remounting unfinished C-series work', async ({ page }) => {
  const session = await workspace(page);
  await enterDrafts(page);
  session.hold();
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
  await expect(page.getByRole('heading', { name: 'Checking your session' })).toBeVisible();
  await expect(page.locator('.cv-workspace')).toHaveCount(1);
  session.release();
  await expectDrafts(page);
  expect(session.writes).toEqual([]);
});

test('confirmed session expiry clears private drafts and the selected upload', async ({ page }) => {
  const session = await workspace(page);
  await enterDrafts(page);
  session.status(401);
  await visibility(page, 'hidden');
  await visibility(page, 'visible');
  await expect(page.locator('.cv-workspace')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('coachify.session'))).toBeNull();
  expect(session.writes).toEqual([]);
});

test('an old pending session check cannot restore drafts after another tab changes account', async ({ page }) => {
  const session = await workspace(page);
  await enterDrafts(page);
  session.hold();
  await visibility(page, 'hidden');
  await visibility(page, 'visible');
  await expect(page.getByRole('heading', { name: 'Checking your session' })).toBeVisible();
  const oldRequestCancelled = page.waitForEvent('requestfailed', request => request.url().endsWith('/profile/auth/session'));
  await page.evaluate(() => {
    localStorage.setItem('coachify.access-epoch', 'other-account');
    window.dispatchEvent(new StorageEvent('storage', { key: 'coachify.access-epoch', newValue: 'other-account', storageArea: localStorage }));
  });
  await expect(page.locator('.cv-workspace')).toHaveCount(0);
  await oldRequestCancelled;
  session.release();
  await expect(page.getByRole('heading', { name: 'Connection interrupted' })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('coachify.session'))).toBeNull();
  expect(session.writes).toEqual([]);
});

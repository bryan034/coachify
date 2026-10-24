import { test, expect } from '@playwright/test';
import { createLocalAccount, fillCurrentEmployment } from './account-helpers';

test('P09–P12 register, switch A/B, restore history, revoke and protect back/reload', async ({ page }) => {
 await page.goto('/');
 await expect(page.getByRole('link', { name: 'Create account', exact: true })).toBeVisible();
 await expect(page.getByRole('link', { name: 'Sign in to your account' })).toBeVisible();
 const a = await createLocalAccount(page, 'Synthetic account A');
 const who = await (await a.get('/api/v1/profile/auth/session')).json();
 expect((await a.finish({expected_version:0,occupational_status:'employed',school_category:'university',education:{institution:{kind:'custom',name:'Synthetic A school'},course:'Synthetic A course'}})).ok()).toBe(true);
 await page.goto('/profile');
 await page.getByRole('button',{name:'Edit profile',exact:false}).click();
 await expect(page.getByRole('textbox', {name:'What course did you study?'})).toHaveValue('Synthetic A course');
 await page.getByRole('button', {name:/^(Sign out|Exit setup and sign out)$/}).first().click();
 await expect(page).toHaveURL(/\/$/);
 expect((await a.get('/api/v1/profile')).status()).toBe(401);
 await page.goto('/profile');
 await expect(page).toHaveURL(/\/$/);
 await page.goBack();
 await expect(page.getByText('Synthetic A school',{exact:true})).toHaveCount(0);
 const b = await createLocalAccount(page, 'Synthetic account B');
 await expect((await b.get('/api/v1/profile')).json()).resolves.toMatchObject({version:0});
 await page.getByRole('button', {name:/^(Sign out|Exit setup and sign out)$/}).first().click();
 await expect(page).toHaveURL(/\/$/);
 await page.goto('/login');
 await page.getByRole('textbox',{name:'Email address',exact:true}).fill(a.email);
 await page.getByLabel('Password',{exact:true}).fill(a.password);
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page).toHaveURL(/\/dashboard$/);
 await expect(page.locator('[aria-label="Saved background"]')).toContainText('Synthetic A school');
 await page.getByRole('link',{name:'My profile'}).click();
 await page.getByRole('button',{name:'Edit profile',exact:false}).click();
 await expect(page.getByRole('textbox',{name:'What course did you study?'})).toHaveValue('Synthetic A course');
 await expect(page.getByText('Synthetic account B',{exact:true})).toHaveCount(0);
});

test('logout failure stays locked across reload and old retry does not clear B', async ({ page }) => {
 const a = await createLocalAccount(page,'Synthetic logout A');
 let fail = true;
 await page.route('**/api/v1/profile/auth/logout', route => fail ? route.fulfill({status:503,json:{detail:'Synthetic termination outage'}}) : route.continue());
 await page.getByRole('button',{name:/^(Sign out|Exit setup and sign out)$/}).first().click();
 await expect(page).toHaveURL(/\/$/);
 await expect(page.getByRole('main').getByRole('alert')).toContainText('Server sign-out could not be confirmed');
 await page.reload();
 await expect(page.getByRole('main').getByRole('alert')).toContainText('Sign-out is pending');
 await expect(page.getByRole('button',{name:'Save background'})).toHaveCount(0);
 const b = await createLocalAccount(page,'Synthetic logout B');
 fail=false;
 // A's late termination retry is session-specific and cannot revoke B.
 expect((await page.request.post('/api/v1/profile/auth/logout',{headers:a.headers})).ok()).toBe(true);
 expect((await b.get('/api/v1/profile')).ok()).toBe(true);
 await page.reload();
 await expect(page.getByRole('heading',{name:'Where are you right now?'})).toBeVisible();
});

test('another tab signing out clears private UI and drafts', async ({ page, context }) => {
 await createLocalAccount(page,'Synthetic multi-tab');
 const other = await context.newPage();
 // Simulate opening a same-account tab; access secrets stay in sessionStorage, never localStorage.
 const stored = await page.evaluate(() => sessionStorage.getItem('coachify.session'));
 await other.goto('/');
 await other.evaluate(value => sessionStorage.setItem('coachify.session',value!),stored);
 await other.goto('/profile');
 await expect(other.getByRole('heading',{name:'Where are you right now?'})).toBeVisible();
 await other.getByRole('button',{name:'Employed',exact:true}).click();
 await fillCurrentEmployment(other);
 await other.getByRole('button',{name:'University',exact:true}).click();
 await other.getByRole('button',{name:'My school isn’t listed'}).click();
 await other.getByRole('textbox',{name:'School name'}).fill('Private unsaved draft');
 await page.bringToFront();
 await expect(page.getByRole('button',{name:/^(Sign out|Exit setup and sign out)$/}).first()).toBeVisible();
 await page.getByRole('button',{name:/^(Sign out|Exit setup and sign out)$/}).first().click();
 await other.bringToFront();
 await expect(other).toHaveURL(/\/$/);
 await expect(other.getByRole('textbox')).toHaveCount(0);
 await other.reload();
 await expect(other.getByRole('link',{name:'Create account',exact:true})).toBeVisible();
});

test('P13/P14 partial setup stays guarded and another tab observes completion',async({page,context})=>{
 const api=await createLocalAccount(page,'Synthetic onboarding tabs');
 await page.getByRole('button',{name:'Employed',exact:true}).click();
 await fillCurrentEmployment(page);
 await page.getByRole('button',{name:'No applicable previous education'}).click();
 await expect(page.getByRole('button',{name:'Enter Coachify',exact:true})).toBeEnabled();
 expect((await(await api.get('/api/v1/profile')).json()).onboarding_complete).toBe(false);
 expect((await page.request.post('/api/v1/career/imports/url',{headers:api.headers,data:{url:'https://example.test/job'}})).status()).toBe(403);
 await page.goto('/roadmap');await expect(page).toHaveURL(/\/onboarding$/);
 const stored=await page.evaluate(()=>sessionStorage.getItem('coachify.session'));
 const other=await context.newPage();await other.goto('/');
 await other.evaluate(value=>sessionStorage.setItem('coachify.session',value!),stored);
 await other.goto('/onboarding');await expect(other.getByRole('button',{name:'Enter Coachify'})).toBeEnabled();
 await page.bringToFront();await expect(page.getByRole('button',{name:'Enter Coachify'})).toBeEnabled();
 await page.getByRole('button',{name:'Enter Coachify'}).click();await expect(page).toHaveURL(/\/dashboard$/);
 await other.bringToFront();await expect(other).toHaveURL(/\/dashboard$/);
 await other.goto('/onboarding');await expect(other).toHaveURL(/\/dashboard$/);
 const saved=await(await api.get('/api/v1/profile')).json();expect(saved.onboarding_complete).toBe(true);
 expect(saved.weekly_hours).toBeNull();expect(saved.application_date).toBeNull();
});

import { expect, test } from '@playwright/test';

test('browser login keeps its credential in an HttpOnly cookie and only stores the public marker', async ({ page, context }) => {
 const secret = 'a'.repeat(64);
 const account = { id: 'synthetic-cookie-account', name: 'Synthetic', provider: 'email', email_verified: true };
 let marker = '', reads = 0;
 await page.route('**/api/v1/profile**', route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  expect(request.headers()['x-elo-browser']).toBe('1');
  expect(request.headers().authorization).toBeUndefined();
  if (path.endsWith('/auth-config')) return route.fulfill({ json: { mode: 'email' } });
  if (path.endsWith('/school-categories')) return route.fulfill({ json: [] });
  if (path.endsWith('/auth/attempts')) return route.fulfill({ json: { nonce: 'synthetic' } });
  if (path.endsWith('/auth/complete')) {
   marker = request.postDataJSON().session_token;
   expect(marker).not.toBe(secret);
   return route.fulfill({ json: account, headers: { 'Set-Cookie': `elo_session=${marker}.${secret}; HttpOnly; Secure; SameSite=Strict; Path=/api/v1` } });
  }
  if (path.endsWith('/auth/logout')) return route.fulfill({ json: { ok: true }, headers: { 'Set-Cookie': 'elo_session=; Max-Age=0; HttpOnly; Secure; SameSite=Strict; Path=/api/v1' } });
  expect(request.headers()['x-elo-session']).toBe(marker);
  expect(request.headers().cookie).toContain(`elo_session=${marker}.${secret}`);
  reads++;
  if (path.endsWith('/auth/session')) return route.fulfill({ json: account });
  return route.fulfill({ json: { version: 0, onboarding_complete: false, education: {} } });
 });
 await page.goto('/login');
 await page.getByRole('textbox', { name: 'Email address' }).fill('synthetic@example.test');
 await page.getByLabel('Password', { exact: true }).fill('Synthetic passphrase 2026!');
 await page.getByRole('button', { name: 'Sign in', exact: true }).click();
 await expect(page).toHaveURL(/\/onboarding$/);
 const stored = await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]));
 expect(stored).not.toContain(secret);
 expect(JSON.parse((await page.evaluate(() => sessionStorage.getItem('elo.session')))!)).toEqual(expect.objectContaining({ marker }));
 const cookie = (await context.cookies()).find(item => item.name === 'elo_session');
 expect(cookie).toEqual(expect.objectContaining({ httpOnly: true, secure: true, sameSite: 'Strict' }));
 await page.reload();
 await expect(page.getByRole('heading', { name: 'Where are you right now?' })).toBeVisible();
 expect(reads).toBeGreaterThan(2);
 await page.getByRole('button', { name: 'Exit setup' }).click();
 await expect.poll(async () => (await context.cookies()).some(item => item.name === 'elo_session')).toBe(false);
});

test('production CSP permits hydration but blocks injected inline scripts and handlers', async ({ page }) => {
 await page.route('**/api/v1/profile**', route => route.fulfill({ json: route.request().url().endsWith('/auth-config') ? { mode: 'email' } : [] }));
 await page.route('**/login', async route => {
  const response = await route.fetch();
  const body = (await response.text()).replace('</body>', '<script id="injected-script">window.eloInjected = true</script><button id="injected-handler" onclick="window.eloInjected = true">Injected handler</button></body>');
  await route.fulfill({ response, body });
 });
 const response = await page.goto('/login');
 const headers = response!.headers();
 const policy = headers['content-security-policy'];
 const nonce = policy.match(/'nonce-([^']+)'/)![1];
 expect(policy).not.toContain('unsafe-eval');
 expect(headers['x-frame-options']).toBe('DENY');
 expect(headers['x-content-type-options']).toBe('nosniff');
 expect(headers['cache-control']).toContain('no-store');
 const nonces = await page.locator('script:not(#injected-script)').evaluateAll(nodes => nodes.map(node => (node as HTMLScriptElement).nonce));
 expect(nonces.length).toBeGreaterThan(0);
 expect(nonces.every(value => value === nonce)).toBe(true);
 await page.locator('#injected-handler').click();
 expect(await page.evaluate(() => (window as Window & { eloInjected?: boolean }).eloInjected)).toBeUndefined();
 const next = await page.request.get('/login');
 expect(next.headers()['content-security-policy']).not.toContain(`'nonce-${nonce}'`);
 const script = await page.locator('script[src]').first().getAttribute('src');
 expect((await page.request.get(`${script}.map`)).status()).toBe(404);
});

import { expect, test, type Page } from '@playwright/test';
import { gmailTestMailbox, gmailTestRecipient, gmailVerificationCode } from './gmail-inbox';
export const TEST_PASSWORD='Synthetic passphrase 2026!';

async function mailpitVerificationCode(page: Page, inbox: string, recipient: string) {
  let code: string | undefined;
  await expect.poll(async () => {
    const search = await page.request.get(`${inbox}/api/v1/search`, { params: { query: `to:${recipient}` } });
    if (!search.ok()) return false;
    const messages: { messages?: { ID: string }[] } = await search.json();
    const id = messages.messages?.[0]?.ID;
    if (!id) return false;
    const message = await page.request.get(`${inbox}/api/v1/message/${id}`);
    if (!message.ok()) return false;
    const body: { Text: string } = await message.json();
    code = body.Text.match(/\b[0-9]{6}\b/)?.[0];
    return !!code;
  }, { timeout: 10_000 }).toBe(true);
  if (!code) throw new Error('The disposable inbox returned no verification code.');
  return code;
}

export async function fillCurrentEmployment(page: Page) {
 await page.getByRole('textbox',{name:'Place of employment'}).fill('Synthetic company');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('textbox',{name:'Role',exact:true}).fill('Synthetic analyst');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('textbox',{name:'Industry',exact:true}).fill('Synthetic industry');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
}
export async function createLocalAccount(page: Page, name = 'Synthetic test account') {
 const inbox = process.env.MAILPIT_BASE_URL;
 const mailbox = inbox ? { kind: 'mailpit', url: inbox } as const : { kind: 'gmail', ...gmailTestMailbox() } as const;
 const email = mailbox.kind === 'gmail' ? gmailTestRecipient(mailbox.address) : `synthetic-${crypto.randomUUID()}@example.test`;
 if (mailbox.kind === 'gmail') test.setTimeout(test.info().timeout + 75_000);
 await page.goto('/register');
 await page.getByRole('textbox', { name: 'Display name (optional)' }).fill(name);
 await page.getByRole('textbox',{name:'Email address',exact:true}).fill(email);
 await page.getByLabel('Password',{exact:true}).fill(TEST_PASSWORD);
 await page.getByRole('button', { name: 'Create account', exact: true }).click();
 await expect(page.getByRole('heading',{name:'Verify your email.'})).toBeVisible();
 const code = mailbox.kind === 'gmail' ? await gmailVerificationCode(mailbox, email) : await mailpitVerificationCode(page, mailbox.url, email);
 await page.getByRole('textbox',{name:'Verification code'}).fill(code);
 await page.getByRole('button',{name:'Verify email',exact:true}).click();
 await expect(page).toHaveURL(/\/onboarding$/);
 await expect(page.getByRole('heading', { name: 'Where are you right now?' })).toBeVisible();
 const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem('elo.session')!).marker as string);
 const headers = { 'X-Elo-Browser': '1', 'X-Elo-Session': token };
 return {
  token,headers,email,password:TEST_PASSWORD,
  get: (path: string) => page.request.get(path, { headers }),
  patch: (path: string, options: { data: object; headers?: Record<string, string> }) => page.request.patch(path, { ...options, headers: { ...headers, ...options.headers } }),
  finish: (data:Record<string, unknown> & {occupational_status?:string;employment?:object}) => page.request.post('/api/v1/profile/onboarding/complete',{data:{...(data.occupational_status==='employed'?{employment:{employer:'Synthetic company',role:'Synthetic analyst',industry:'Synthetic industry'}}:{}),...data},headers:{...headers,'Idempotency-Key':crypto.randomUUID()}}),
 };
}

import { expect, type Page } from '@playwright/test';
export const TEST_PASSWORD='Synthetic passphrase 2026!';
export async function inboxCode(page:Page,email:string){
 const inbox=process.env.MAILPIT_BASE_URL;
 if(!inbox)throw new Error('Set MAILPIT_BASE_URL to the disposable test inbox.');
 let id='';
 await expect.poll(async()=>{
  const response=await page.request.get(`${inbox}/api/v1/search`,{params:{query:`to:${email}`}});
  const data=await response.json();id=data.messages?.[0]?.ID||'';return id;
 }).not.toBe('');
 const message=await(await page.request.get(`${inbox}/api/v1/message/${id}`)).json();
 const code=String(message.Text).match(/\b[0-9]{6}\b/)?.[0];
 if(!code)throw new Error('Synthetic verification mail contained no code.');
 return code;
}
export async function createLocalAccount(page: Page, name = 'Synthetic test account') {
 const email=`synthetic-${crypto.randomUUID()}@example.test`;
 await page.goto('/register');
 await page.getByRole('textbox', { name: 'Display name (optional)' }).fill(name);
 await page.getByRole('textbox',{name:'Email address',exact:true}).fill(email);
 await page.getByLabel('Password',{exact:true}).fill(TEST_PASSWORD);
 await page.getByRole('button', { name: 'Create account', exact: true }).click();
 await expect(page.getByRole('heading',{name:'Verify your email.'})).toBeVisible();
 await page.getByRole('textbox',{name:'Verification code'}).fill(await inboxCode(page,email));
 await page.getByRole('button',{name:'Verify email',exact:true}).click();
 await expect(page).toHaveURL(/\/onboarding$/);
 await expect(page.getByRole('button', { name: 'Finish setup' })).toBeEnabled();
 const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem('coachify.session')!).token as string);
 const headers = { Authorization: `Bearer ${token}` };
 return {
  token,headers,email,password:TEST_PASSWORD,
  get: (path: string) => page.request.get(path, { headers }),
  patch: (path: string, options: { data: object; headers?: Record<string, string> }) => page.request.patch(path, { ...options, headers: { ...headers, ...options.headers } }),
  finish: (data:object) => page.request.post('/api/v1/profile/onboarding/complete',{data,headers:{...headers,'Idempotency-Key':crypto.randomUUID()}}),
 };
}

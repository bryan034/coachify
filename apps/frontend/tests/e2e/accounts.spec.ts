import { test, expect } from '@playwright/test';

test('P09–P16 Google entry, OTP verification, initial setup, reload and logout', async ({ page }) => {
 let privateReads=0; let attempts=0; let completed=0; let nonce=''; let accessToken=''; let ended=false;
 const account={id:'synthetic-google',name:'Synthetic Google Account',provider:'google',email:'synthetic@example.test',email_verified:true};
 let profile={version:0,onboarding_complete:false,occupational_status:null,school_category:null,education_context:null,education_review_required:false,education:{}};
 await page.route('https://accounts.google.com/gsi/client', route=>route.fulfill({contentType:'application/javascript',body:`window.google={accounts:{id:{initialize:function(o){this.options=o;},renderButton:function(el){const b=document.createElement('button');b.textContent='Continue with Google (test)';b.onclick=()=>this.options.callback({credential:'verified-google-'+this.options.nonce});el.appendChild(b);},disableAutoSelect:function(){}}}};`}));
 await page.route('**/api/v1/profile**', route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'google',google_enabled:true,email_password_enabled:true,email_verification_required:true}});
  if(path.endsWith('/school-categories'))return route.fulfill({json:[{id:'university',label:'University'}]});
  if(path.endsWith('/auth/attempts')){attempts++;nonce='synthetic-nonce-'+attempts;return route.fulfill({json:{nonce}});}
  if(path.endsWith('/auth/attempts/cancel'))return route.fulfill({json:{ok:true}});
  if(path.endsWith('/auth/complete')){
   const input=route.request().postDataJSON();expect(input.credential).toBe('verified-google-'+nonce);accessToken=input.session_token;expect(accessToken.length).toBeGreaterThanOrEqual(32);completed++;return route.fulfill({json:{verification_required:true,challenge_id:'synthetic-challenge',masked_email:'s***@example.test',expires_at:new Date(Date.now()+600000).toISOString(),resend_at:new Date(Date.now()+60000).toISOString()}});
  }
  if(path.endsWith('/auth/verify-email')){expect(route.request().postDataJSON().code).toBe('123456');return route.fulfill({json:account});}
  if(route.request().method()==='PATCH'){profile={...profile,...route.request().postDataJSON(),version:profile.version+1};return route.fulfill({json:profile});}
  if(path.endsWith('/onboarding/complete')){profile={...profile,...route.request().postDataJSON(),version:profile.version+1,onboarding_complete:true};return route.fulfill({json:profile});}
  if(path.endsWith('/auth/logout')){ended=true;return route.fulfill({json:{ok:true}});}
  if(path.endsWith('/auth/session'))return route.fulfill({status:ended?401:200,json:ended?{detail:'Ended'}:account});
  if(path.endsWith('/companies')||path.endsWith('/industries'))return route.fulfill({json:[]});
  if(path.endsWith('/planning-inputs'))return route.fulfill({json:{profile_version:0,planning_revision:0,ready:false,issues:[],availability_periods:[]}});
  privateReads++;expect(route.request().headers().authorization).toBe('Bearer '+accessToken);return route.fulfill({json:profile});
 });
 await page.goto('/');
 await expect(page.getByRole('link',{name:'Create account',exact:true})).toBeVisible();
 expect(privateReads).toBe(0);
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('link',{name:'Create account',exact:true}).click();
 await page.getByRole('button',{name:'Continue with Google (test)'}).click();
 await expect(page.getByRole('heading',{name:'Verify your email.'})).toBeVisible();
 expect(privateReads).toBe(0);
 await page.getByRole('textbox',{name:'Verification code'}).fill('123456');
 await page.getByRole('button',{name:'Verify email',exact:true}).click();
 await expect(page).toHaveURL(/\/onboarding$/);
 expect(completed).toBe(1);
 await page.reload();
 await expect(page.getByRole('heading',{name:'Where are you right now?'})).toBeVisible();
 await page.getByRole('button',{name:'Employed',exact:true}).click();
 await page.getByRole('textbox',{name:'Place of employment'}).fill('Synthetic company');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('textbox',{name:'Role',exact:true}).fill('Synthetic analyst');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('textbox',{name:'Industry',exact:true}).fill('Synthetic industry');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'No applicable previous education'}).click();
 await page.getByRole('button',{name:'Enter Coachify',exact:true}).click();
 await expect(page).toHaveURL(/\/dashboard$/);
 expect(completed).toBe(1);
 await page.getByRole('button',{name:'Sign out',exact:true}).first().click();
 await expect(page).toHaveURL(/\/$/);
 await page.reload();
 await expect(page.getByRole('link',{name:'Create account',exact:true})).toBeVisible();
 await expect(page.getByText('Synthetic Google Account',{exact:true})).toHaveCount(0);
});

test('signed-out deep links and unavailable configuration never expose private UI',async({page})=>{
 await page.route('**/api/v1/profile**', route=>route.fulfill({status:503,json:{detail:'Connection unavailable'}}));
 await page.goto('/login?returnTo=https://outside.example.invalid');
 await expect(page.getByRole('main').getByRole('alert')).toContainText('Connection unavailable');
 await expect(page.getByRole('button',{name:'Retry connection'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Save background'})).toHaveCount(0);
 expect(page.url()).not.toContain('outside.example.invalid/');
});

test('email-only registration accepts a non-Gmail address and verifies OTP without Google', async ({page}) => {
 let googleRequests=0;
 const account={id:'synthetic-email',name:'Synthetic Account',provider:'email',email:'synthetic-user@outlook.com',email_verified:true};
 let registration:{email:string;password:string;session_token:string;credential?:string}|undefined;
 page.on('request', request=>{if(request.url().startsWith('https://accounts.google.com/'))googleRequests++;});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false,email_password_enabled:true,email_verification_required:true}});
  if(path.endsWith('/auth/attempts'))return route.fulfill({json:{nonce:'synthetic-email-only-nonce'}});
  if(path.endsWith('/auth/attempts/cancel'))return route.fulfill({json:{ok:true}});
  if(path.endsWith('/auth/complete')){
   registration=route.request().postDataJSON();
   return route.fulfill({json:{verification_required:true,challenge_id:'synthetic-challenge',masked_email:'s***@outlook.com',expires_at:new Date(Date.now()+600000).toISOString(),resend_at:new Date(Date.now()+60000).toISOString()}});
  }
  if(path.endsWith('/auth/verify-email')){
   expect(route.request().postDataJSON().code).toBe('123456');
   return route.fulfill({json:account});
  }
  if(path.endsWith('/auth/session'))return route.fulfill({json:account});
  if(path.endsWith('/school-categories'))return route.fulfill({json:[]});
  return route.fulfill({json:{version:0,onboarding_complete:false,occupational_status:null,school_category:null,education_context:null,education_review_required:false,education:{}}});
 });
 await page.goto('/register');
 await expect(page.getByText('Or continue with Google')).toHaveCount(0);
 await page.getByRole('textbox',{name:'Email address'}).fill('synthetic-user@outlook.com');
 await page.getByLabel('Password',{exact:true}).fill('Synthetic passphrase 2026!');
 await page.getByRole('button',{name:'Create account',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Verify your email.'})).toBeVisible();
 expect(registration?.email).toBe('synthetic-user@outlook.com');
 expect(registration?.credential).toBeUndefined();
 await page.getByRole('textbox',{name:'Verification code'}).fill('123456');
 await page.getByRole('button',{name:'Verify email',exact:true}).click();
 await expect(page).toHaveURL(/\/onboarding$/);
 expect(googleRequests).toBe(0);
});

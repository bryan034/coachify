import {test,expect} from '@playwright/test';

test('P13 uses canonical completion, guards deep links and distinguishes profile outage',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 let complete=false;let outage=false;
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'local_test',google_enabled:false,email_password_enabled:true}});
  if(path.endsWith('/school-categories'))return route.fulfill({json:[{id:'university',label:'University'}]});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic',name:'Synthetic',provider:'local_test',email_verified:true}});
  if(outage)return route.fulfill({status:503,json:{detail:'Synthetic profile outage'}});
  if(path.endsWith('/planning-inputs'))return route.fulfill({json:{profile_version:7,planning_revision:0,ready:false,issues:[],availability_periods:[]}});
  return route.fulfill({json:{version:7,onboarding_complete:complete,onboarding_state:complete?'complete':'legacy_unconfirmed',occupational_status:'employed',school_category:'university',education_context:'last',education_review_required:false,education:{institution:{kind:'custom',name:'Synthetic Legacy School'},course:'Synthetic legacy course'},employment:{employer:'Synthetic company',role:'Synthetic role',industry:'Synthetic industry'}}});
 });
 await page.goto('/dashboard');
 await expect(page).toHaveURL(/\/onboarding$/);
 await expect(page.getByRole('heading',{name:'Your next chapter starts here.'})).toBeVisible();
 await expect(page.getByText('Synthetic legacy course',{exact:true})).toBeVisible();
 await expect(page.getByRole('navigation')).toHaveCount(0);
 await page.goto('/roadmap');
 await expect(page).toHaveURL(/\/onboarding$/);
 await page.reload();
 await expect(page).toHaveURL(/\/onboarding$/);
 complete=true;
 await page.reload();
 await expect(page).toHaveURL(/\/dashboard$/);
 await page.goto('/onboarding');
 await expect(page).toHaveURL(/\/dashboard$/);
 outage=true;
 await expect(page.getByRole('heading',{name:'Welcome to Coachify'})).toBeVisible();
 await page.goto('/profile');
 await expect(page).toHaveURL(/\/profile$/);
 await expect(page.getByRole('main').getByRole('alert')).toContainText('Synthetic profile outage');
 await expect(page.getByRole('button',{name:'Retry profile'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Enter Coachify'})).toHaveCount(0);
 outage=false;
 await page.getByRole('button',{name:'Retry profile'}).click();
 await expect(page.getByRole('button',{name:'Edit profile',exact:false})).toBeVisible();
});

async function previewSetup(page: import('@playwright/test').Page) {
 await page.addInitScript(() => {
  localStorage.setItem('coachify.access-epoch','1');
  sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-preview',epoch:'1'}));
  const state = window as unknown as Window & { setupAnimations: string[] };
  state.setupAnimations = [];
  document.addEventListener('animationstart',event => state.setupAnimations.push(event.animationName));
 });
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',development_tools_enabled:true}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic',name:'Synthetic',provider:'email',email_verified:true}});
  if(path.endsWith('/school-categories'))return route.fulfill({json:[{id:'university',label:'University'},{id:'secondary',label:'Secondary School'}]});
  if(path.endsWith('/school-countries'))return route.fulfill({json:[{code:'SG',name:'Singapore'}]});
  if(path.endsWith('/institutions'))return route.fulfill({json:{items:Array.from({length:15},(_,i)=>({id:String(i),name:`Synthetic University ${i+1}`,country:'Singapore',country_code:'SG'})),total:15,snapshot_date:'2026-10-24',coverage_note:'Synthetic suggestions.'}});
  return route.fulfill({json:{version:2,onboarding_complete:true,occupational_status:'employed',school_category:null,no_previous_education:true,education_review_required:false,education:{},employment:{employer:'Synthetic company',role:'Synthetic role',industry:'Synthetic industry'}}});
 });
 await page.goto('/onboarding/preview');
 await expect(page.getByRole('heading',{name:'Where are you right now?'})).toBeVisible();
}

test('full-screen setup uses bottom progress and animates forward/back without a sidebar',async({page},testInfo)=>{
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.setViewportSize({width:1440,height:900});
 await previewSetup(page);
 const progress=page.getByRole('progressbar',{name:'Setup progress'});
 await expect(page.getByRole('complementary')).toHaveCount(0);
 await expect(progress).toHaveAttribute('aria-valuenow','1');
 const footer=page.getByRole('contentinfo',{name:'Setup progress'});
 expect((await footer.boundingBox())!.y).toBeGreaterThan(700);
 await page.locator('.onboarding-question').evaluate(async element=>{await Promise.all(element.getAnimations().map(a=>a.finished));});
 await page.screenshot({path:testInfo.outputPath('onboarding-fullscreen-desktop.png')});
 await page.getByRole('button',{name:'Student',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Choose your education path.'})).toBeFocused();
 await expect(progress).toHaveAttribute('aria-valuenow','2');
 await page.getByRole('button',{name:'Back',exact:false}).click();
 await expect(page.getByRole('heading',{name:'Where are you right now?'})).toBeFocused();
 await expect(progress).toHaveAttribute('aria-valuenow','1');
 await expect.poll(()=>page.evaluate(()=>(window as unknown as Window & {setupAnimations:string[]}).setupAnimations)).toContain('setup-backward');
 expect(await page.evaluate(()=>(window as unknown as Window & {setupAnimations:string[]}).setupAnimations)).toContain('setup-forward');
 await page.setViewportSize({width:390,height:844});
 await page.locator('.onboarding-question').evaluate(async element=>{await Promise.all(element.getAnimations().map(a=>a.finished));});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect((await footer.boundingBox())!.y).toBeGreaterThan(650);
 await page.screenshot({path:testInfo.outputPath('onboarding-fullscreen-mobile.png')});
 await page.getByRole('button',{name:'Student',exact:true}).click();
 await page.getByRole('button',{name:'University',exact:true}).click();
 await expect(page.getByRole('button',{name:'Synthetic University 1',exact:true})).toBeVisible();
 const before=(await footer.boundingBox())!;
 await page.locator('.onboarding-body').evaluate(element=>element.scrollTo({top:element.scrollHeight}));
 const after=(await footer.boundingBox())!;
 expect(after.y).toBeCloseTo(before.y,0);
 expect(after.y+after.height).toBeLessThanOrEqual(845);
 await expect(progress).toHaveAttribute('aria-valuetext','Step 3 of 6: Your school');
});

test('reduced-motion setup changes questions without page animations',async({page})=>{
 await page.emulateMedia({reducedMotion:'reduce'});
 await previewSetup(page);
 await page.getByRole('button',{name:'Student',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Choose your education path.'})).toBeFocused();
 expect(await page.locator('.onboarding-question').evaluate(element=>element.getAnimations().length)).toBe(0);
 await page.getByRole('button',{name:'Back',exact:false}).click();
 await expect(page.getByRole('heading',{name:'Where are you right now?'})).toBeFocused();
 expect(await page.locator('.onboarding-question').evaluate(element=>getComputedStyle(element).animationName)).toBe('none');
});

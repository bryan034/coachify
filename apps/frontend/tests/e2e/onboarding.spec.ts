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
  return route.fulfill({json:{version:7,onboarding_complete:complete,onboarding_state:complete?'complete':'legacy_unconfirmed',occupational_status:'employed',school_category:'university',education_context:'last',education_review_required:false,education:{institution:{kind:'custom',name:'Synthetic Legacy School'},course:'Synthetic legacy course'}}});
 });
 await page.goto('/dashboard');
 await expect(page).toHaveURL(/\/onboarding$/);
 await expect(page.getByRole('textbox',{name:'What course did you study?'})).toHaveValue('Synthetic legacy course');
 await page.getByRole('navigation').getByRole('link',{name:'Roadmap',exact:true}).click();
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
 await expect(page.getByRole('button',{name:'Finish setup'})).toHaveCount(0);
 outage=false;
 await page.getByRole('button',{name:'Retry profile'}).click();
 await expect(page.getByRole('button',{name:'Save background'})).toBeEnabled();
});

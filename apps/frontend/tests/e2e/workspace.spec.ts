import { test, expect } from '@playwright/test';
import { policy, emptyDeclarations } from '../fixtures/cv';

const categories = [{ id: 'university', label: 'University' }, { id: 'secondary', label: 'Secondary School' }];
test('workspace uses saved profile data, preserves navigation and leaves missing services disconnected', async ({ page }) => {
 await page.addInitScript(() => { localStorage.setItem('coachify.access-epoch','1'); sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-token',epoch:'1'})); });
 const apiCalls: string[] = [];
 let saved = { version: 0, onboarding_complete:true, occupational_status: null as string | null, school_category: null as string | null, education_context: null as string | null, education_review_required: false, education: {} as Record<string, unknown>, current_study_year: null as number | null };
 await page.route('**/api/**', async route => {
  const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/session')) return route.fulfill({json:{id:'synthetic',name:'Synthetic',provider:'local_test',onboarding_complete:false}});
    if (url.pathname.endsWith('/auth/logout')) return route.fulfill({json:{ok:true}}); apiCalls.push(url.pathname);
  if(url.pathname.endsWith('/cv/policy'))return route.fulfill({json:policy});
  if(url.pathname === '/api/v1/cv')return route.fulfill({json:{cvs:[],selection:{cv_id:null,version:0}}});
  if(url.pathname.endsWith('/profile/capabilities'))return route.fulfill({json:emptyDeclarations});
  expect(url.pathname.startsWith('/api/v1/profile')).toBe(true);
  if (url.pathname.endsWith('/planning-inputs')) return route.fulfill({json:{profile_version:saved.version,planning_revision:0,ready:false,issues:[],availability_periods:[]}});
  if(url.pathname.endsWith('/auth-config')) return route.fulfill({json:{mode:'local_test'}});
  if(url.pathname.endsWith('/school-categories')) return route.fulfill({json:categories});
  if(url.pathname.endsWith('/institutions')) return route.fulfill({json:{items:[],total:0,offset:0,limit:25,snapshot_date:'2026-10-24',coverage_note:'Test fixture'}});
  if(url.pathname.endsWith('/school-countries')) return route.fulfill({json:[]});
  if(route.request().method()==='PATCH') {
   const input=route.request().postDataJSON();
   expect(input.expected_version).toBe(saved.version);
   saved={...saved,...input,education:input.education,version:saved.version+1,current_study_year:input.education.study_year};
  }
  return route.fulfill({json:saved});
 });
 await page.goto('/profile/edit');

 await expect(page.getByRole('button',{name:'Save background'})).toBeEnabled();
 await page.getByRole('combobox',{name:'Occupational status'}).selectOption('student');
 await page.getByRole('combobox',{name:'Education path'}).selectOption('university');
 await page.getByRole('button',{name:'My institution is not listed'}).click();
 await page.getByRole('textbox',{name:'Institution name'}).fill('Synthetic College');
 await page.getByRole('textbox',{name:'What course are you studying?'}).fill('Design & Computing');
 await page.getByRole('spinbutton',{name:/Current study level/}).fill('3');
 await page.getByRole('button',{name:'Save background'}).click();
 await expect(page.getByText('Profile saved.')).toBeVisible();
 await page.getByRole('link',{name:'Home',exact:true}).click();
 await expect(page.locator('[aria-label="Saved background"]')).toContainText('Synthetic College');
 await expect(page.locator('[aria-label="Saved background"]')).toContainText('Design & Computing · Year 3');
 await page.reload();
 await expect(page.locator('[aria-label="Saved background"]')).toContainText('Synthetic College');
 for (const [label,heading] of [['Roadmap','Roadmap'],['Resume & Tracker','Resume & Tracker'],['Chats & Socials','Chats & Socials'],['Calendar & Events','Calendar & Events']]) {
  const link=page.getByRole('navigation').getByRole('link',{name:label,exact:true});
  await link.click();
  await expect(link).toHaveAttribute('aria-current','page');
  await expect(page.getByRole('heading',{level:1,name:heading})).toBeVisible();
  if(label==='Resume & Tracker')await expect(page.getByRole('heading',{name:'No saved CV yet'})).toBeVisible();
  else await expect(page.locator('.feature-notice')).toContainText('Coming soon');
 }
 await page.getByRole('button',{name:'Month',exact:true}).click();
 await expect(page.getByRole('button',{name:'Month',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(page.locator('[aria-label="Month calendar"] .dh')).toHaveCount(7);
 await expect(page.getByRole('button',{name:'+ Add',exact:true})).toBeDisabled();
 await page.getByRole('navigation').getByRole('link',{name:'Resume & Tracker'}).click();
 await expect(page.getByRole('button',{name:'Upload CV'})).toBeDisabled();
 await page.getByRole('navigation').getByRole('link',{name:'Roadmap',exact:true}).click();
 await page.getByRole('button',{name:'Courses',exact:true}).click();
 await expect(page.getByRole('heading',{name:'No courses to show yet'})).toBeVisible();
 await expect(page.getByRole('link',{name:'Edit planning preferences →'})).toBeVisible();
 expect(apiCalls.every(p=>p.startsWith('/api/v1/profile')||(p==='/api/v1/cv'||p.startsWith('/api/v1/cv/')))).toBe(true);
 expect(apiCalls).toContain('/api/v1/cv/policy');
 // Mobile navigation and calendar scrolling stay inside their containers.
 await page.setViewportSize({width:390,height:844});
 for(const label of ['Home','Resume & Tracker','Chats & Socials','Calendar & Events']) {
  await page.getByRole('navigation').getByRole('link',{name:label,exact:true}).click();
  await expect(page.getByRole('navigation').getByRole('link',{name:label,exact:true})).toHaveAttribute('aria-current','page');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 }
});

test('profile connection errors offer retry without enabling writes', async ({page})=>{
 await page.route('**/api/v1/profile**',route=>route.fulfill({status:503,json:{detail:'Unavailable'}}));
 await page.goto('/profile');
 await expect(page.getByRole('main').getByRole('alert')).toContainText('Unavailable');
 await expect(page.getByRole('button',{name:'Save background'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Retry connection'})).toBeEnabled();
});

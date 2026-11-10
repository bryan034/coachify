import { test, expect } from '@playwright/test';
import { blankPlanner } from '../fixtures/roadmap-workspace';
import { mockEmptyConversation } from '../fixtures/cv-ui';
import { policy, emptyDeclarations } from '../fixtures/cv';

const categories = [{ id: 'university', label: 'University' }, { id: 'secondary', label: 'Secondary School' }];
test('workspace uses saved profile data, preserves navigation and leaves missing services disconnected', async ({ page },testInfo) => {
 await mockEmptyConversation(page);
 await page.addInitScript(() => { localStorage.setItem('elo.access-epoch','1'); sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-token',epoch:'1'})); });
 const apiCalls: string[] = [];
 let saved = { version: 0, onboarding_complete:true, occupational_status: null as string | null, school_category: null as string | null, education_context: null as string | null, education_review_required: false, education: {} as Record<string, unknown>, current_study_year: null as number | null };
 await page.route('**/api/**', async route => {
  const url = new URL(route.request().url());
  if(url.pathname.startsWith('/api/v1/assessments/')) return route.fulfill({json:{version:0,stale:false,ready:false,model_available:true,result:null,operation:null,issues:[]}});
  if (url.pathname.includes('/cv/conversations')) return route.fallback();
  if (url.pathname === '/api/v1/career/discoveries') return route.fulfill({json:{items:[],next_cursor:null}});
    if (url.pathname.endsWith('/auth/session')) return route.fulfill({json:{id:'synthetic',name:'Synthetic',provider:'local_test',onboarding_complete:false}});
    if (url.pathname.endsWith('/auth/logout')) return route.fulfill({json:{ok:true}}); apiCalls.push(url.pathname);
  if(url.pathname.endsWith('/cv/policy'))return route.fulfill({json:policy});
  if(url.pathname === '/api/v1/cv')return route.fulfill({json:{cvs:[],selection:{cv_id:null,version:0}}});
  if(url.pathname === '/api/v1/jobs/filters')return route.fulfill({json:{job_types:[{value:'internship',count:1}],industries:[{value:'fintech',count:1}],workplaces:[{value:'hybrid',count:1}],companies:[{value:'Synthetic Pay',count:1}],last_synced_at:'2026-11-05T04:00:00Z'}});
  if(url.pathname === '/api/v1/jobs/applications')return route.fulfill({json:{items:[]}});
  if(url.pathname === '/api/v1/jobs/search')return route.fulfill({json:{items:[{id:'0'.repeat(32),title:'Synthetic Data Intern',company:'Synthetic Pay',industry:'fintech',location:'Singapore',department:null,job_type:'internship',workplace:'hybrid',posted_at:'2026-11-01T00:00:00Z',posted_at_estimated:false,application_deadline:null,excerpt:'Support synthetic payments analysis.',listing_url:'https://jobs.example.test/1',apply_url:'https://jobs.example.test/1/apply',provider:'lever',status:'open'}],total:1,next_cursor:null}});
  if(url.pathname.endsWith('/profile/skills-profile'))return route.fulfill({json:{version:0,status:'empty',saved_at:null,areas:{},entries:[]}});
  if(url.pathname.endsWith('/profile/capabilities'))return route.fulfill({json:emptyDeclarations});
  if(url.pathname === '/api/v1/roadmaps/learning')return route.fulfill({json:{has_roadmap:false,roadmap_id:null,skills_total:0,skills_started:0,skills_done:0,steps:[]}});
  if(url.pathname === '/api/v1/jobs/external-searches')return route.fulfill({json:{items:[{name:'LinkedIn',url:`https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(url.searchParams.get('q')!).replaceAll('%20','+')}&location=Singapore`},{name:'Indeed',url:'https://sg.indeed.com/jobs?q=x&l=Singapore'}]}});
  if(url.pathname === '/api/v1/career/goals/current')return route.fulfill({json:{goal:null,selection_version:0,dependent_results_need_review:false}});
  if(url.pathname === '/api/v1/roadmaps/workspace') {
   expect(route.request().method()).toBe('GET');
   return route.fulfill({json:{planner:blankPlanner(),version:0,messages:[],operation:null,active:null,draft:null,assessment:null,stale:false,context:{ready:false,model_available:true,issues:[{source:'cv',message:'Upload, extract and select a CV before planning.',href:'/cv'},{source:'career',message:'Extract a Career goal before planning.',href:'/career-goal'}],planning_defaults:{application_date:null,weekly_hours:null,availability_periods:[]}}}});
  }
  expect(url.pathname.startsWith('/api/v1/profile'),`unexpected request ${url.pathname}`).toBe(true);
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
 await page.getByRole('link',{name:'Home',exact:true}).first().click();
 // The saved background shows beside the account in the sidebar; Home no longer repeats it.
 await expect(page.locator('.side-bottom .me')).toContainText('Synthetic College');
 await page.reload();
 await expect(page.locator('.side-bottom .me')).toContainText('Synthetic College');
 await page.screenshot({path:testInfo.outputPath('home-desktop.png'),fullPage:true});
 for (const [label,heading] of [['Roadmap','Roadmap'],['Skills Profile','Skills Profile'],['Search Jobs','Search Jobs'],['Conversations','Conversations'],['Calendar','Calendar']]) {
  const link=page.getByRole('navigation').getByRole('link',{name:label,exact:true});
  await link.click();
  await expect(link).toHaveAttribute('aria-current','page');
  await expect(page.getByRole('heading',{level:1,name:heading})).toBeVisible();
  if(label==='Skills Profile'){await page.screenshot({path:testInfo.outputPath('skills-desktop.png'),fullPage:true});await expect(page.getByRole('region',{name:'Skills profile summary'})).toBeVisible();await expect(page.getByRole('textbox',{name:'Message elo'})).toHaveCount(0);}
  else if(label==='Search Jobs'){
   await expect(page.getByRole('textbox',{name:'Job title or keywords'})).toBeVisible();
   await page.getByRole('textbox',{name:'Job title or keywords'}).fill('Data analyst');
   await page.getByRole('button',{name:'Search',exact:true}).click();
   await expect(page.getByRole('link',{name:/LinkedIn/})).toHaveAttribute('href',/keywords=Data\+analyst/);
   await expect(page.getByRole('link',{name:/LinkedIn/})).toHaveAttribute('target','_blank');
   await expect(page.getByRole('heading',{name:'Synthetic Data Intern'})).toBeVisible();
   await expect(page.getByRole('link',{name:/Apply on employer site/})).toHaveAttribute('href','https://jobs.example.test/1/apply');
   await expect(page.getByRole('link',{name:'Skills Profile',exact:true})).toHaveAttribute('href','/cv');
   await page.screenshot({path:testInfo.outputPath('jobs-desktop.png'),fullPage:true});
   const [employer]=await Promise.all([page.waitForEvent('popup'),page.getByRole('link',{name:/Apply on employer site/}).click()]);
   const applicationCheck=page.getByRole('region',{name:'Application check'});
   await expect(applicationCheck).toHaveCount(0);
   await employer.close();
   await page.bringToFront();
   await page.evaluate(()=>window.dispatchEvent(new Event('focus'))); // Playwright keeps every page focused, so returning fires no event of its own.
   await expect(applicationCheck).toContainText('Did you apply to Synthetic Data Intern at Synthetic Pay?');
   await page.screenshot({path:testInfo.outputPath('jobs-application-check.png')});
   await applicationCheck.getByRole('button',{name:'No',exact:true}).click();
   await expect(applicationCheck).toHaveCount(0);
   await expect(page.getByRole('button',{name:'My applications (0)'})).toBeVisible();
  }
  else if(label==='Roadmap') {
   await expect(page.getByRole('heading',{name:'Bring your starting point and direction'})).toBeVisible();
   await expect(page.getByRole('textbox',{name:'Answer here'})).toBeDisabled();
   await expect(page.getByRole('button',{name:'Send message',exact:true})).toBeDisabled();
  } else if(label==='Conversations') await expect(page.getByRole('heading',{name:'Socials are on the way'})).toBeVisible();
  else await expect(page.getByText('Event discovery is coming soon.')).toBeVisible();
 }
 await page.getByRole('button',{name:'Month',exact:true}).click();
 await expect(page.getByRole('button',{name:'Month',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(page.locator('[aria-label="Month calendar"] .dh')).toHaveCount(7);
 // Calendar shows no add or view-event controls until they work.
 await expect(page.getByRole('button',{name:'+ Add',exact:true})).toHaveCount(0);
 await page.getByRole('navigation').getByRole('link',{name:'Skills Profile'}).click();
 await page.getByRole('button',{name:'Upload new CV'}).click();await expect(page.getByRole('button',{name:'Upload CV',exact:true})).toBeDisabled();
 await page.getByRole('navigation').getByRole('link',{name:'Roadmap',exact:true}).click();
 await expect(page.getByRole('heading',{name:'What elo will use'})).toBeVisible();
 await expect(page.locator('.roadmap-prerequisites a[href="/cv"]')).toBeVisible();
 await expect(page.locator('.roadmap-prerequisites a[href="/career-goal"]')).toBeVisible();
 await page.getByRole('tab',{name:'Starting point',exact:true}).click();
 await expect(page.getByRole('tabpanel',{name:'Starting point',exact:true})).toBeVisible();
 expect(apiCalls.every(p=>p.startsWith('/api/v1/profile')||p==='/api/v1/roadmaps/workspace'||p==='/api/v1/career/goals/current'||p==='/api/v1/roadmaps/learning'||p.startsWith('/api/v1/jobs/')||(p==='/api/v1/cv'||p.startsWith('/api/v1/cv/')))).toBe(true);
 expect(apiCalls).toContain('/api/v1/cv/policy');
 // The sidebar stays beside content, and mobile navigation expands on demand.
 const sidebar = await page.locator('.side').boundingBox();
 const main = await page.locator('main').boundingBox();
 expect(sidebar!.x + sidebar!.width).toBeLessThanOrEqual(main!.x);
 await expect(page.locator('.journey-visual, .path-mark')).toHaveCount(0);
 await page.screenshot({path:testInfo.outputPath('sidebar-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeHidden();
 await page.getByRole('button',{name:'Menu',exact:true}).click();
 await page.screenshot({path:testInfo.outputPath('sidebar-mobile.png'),fullPage:true});
 await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Home',exact:true}).focus();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('button',{name:'Menu',exact:true})).toBeFocused();
 for(const label of ['Home','Skills Profile','Search Jobs','Conversations','Calendar']) {
  await page.getByRole('button',{name:'Menu',exact:true}).click();
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible();
  await page.locator('#workspace-sidebar').getByRole('link',{name:label,exact:true}).click();
  await expect(page.locator('.nav a[aria-current=page]')).toHaveText(label);
  await expect(page.getByRole('button',{name:'Menu',exact:true})).toHaveAttribute('aria-expanded','false');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  if(label==='Search Jobs'){
   await page.getByRole('textbox',{name:'Job title or keywords'}).fill('Data analyst');
   await page.getByRole('button',{name:'Search',exact:true}).click();
   await expect(page.getByRole('link',{name:/Indeed/})).toBeVisible();
   await page.screenshot({path:testInfo.outputPath('jobs-mobile.png'),fullPage:true});
  }
 }
});

test('profile connection errors offer retry without enabling writes', async ({page})=>{
 await page.route('**/api/v1/profile**',route=>route.fulfill({status:503,json:{detail:'Unavailable'}}));
 await page.goto('/profile');
 await expect(page.getByRole('main').getByRole('alert')).toContainText('Unavailable');
 await expect(page.getByRole('button',{name:'Save background'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Retry connection'})).toBeEnabled();
});

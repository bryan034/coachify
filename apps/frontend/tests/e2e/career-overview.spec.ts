import {careerFixture} from './career-fixture';
import {mockEmptyConversation} from '../fixtures/cv-ui';
import {policy,emptyDeclarations} from '../fixtures/cv';
import {test,expect} from '@playwright/test';

test('saved briefing accordions, guided refinement, replacement and CV handoff on desktop and mobile',async({page},testInfo)=>{
 await mockEmptyConversation(page);
 await page.route('**/api/v1/profile/capabilities',route=>route.fulfill({json:emptyDeclarations}));
 await page.route('**/api/v1/cv{,/**}',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/skills-profile'))return route.fulfill({json:{version:0,status:'empty',saved_at:null,areas:{},entries:[]}});
  if(path.endsWith('/policy'))return route.fulfill({json:policy});
  if(path==='/api/v1/cv')return route.fulfill({json:{cvs:[],selection:{cv_id:null,version:0}}});
  return route.fallback();
 });
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/capabilities'))return route.fallback();
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{}})});
 });
 let currentRole='Backend Software Engineer',researching=true,edits=0,extractions=0;
 const state=()=>{
  const extraction={role:currentRole,field:'Software Engineering',company:'Example Technologies',location:'Singapore',seniority_level:'Entry level',job_url:null,summary:'Build and maintain backend services, APIs and reliable data systems.',responsibilities:['Build APIs and services','Collaborate with product teams'],skills:[{item_id:'python',name:'Python',category:'Technical',priority:'required',origin:'employer',evidence:'Python is required.'},{item_id:'team',name:'Teamwork',category:'Transferable',priority:'preferred',origin:'employer'}],non_skill_requirements:[{requirement_id:'degree',category:'qualification',description:'Degree in a related discipline',priority:'preferred',evidence:'Degree in a related discipline',group_id:null,group_operator:'all',origin:'employer'}]};
  return {session_id:'000000000000000000000001',revision:edits+1,kind:'jd',phase:researching?'researching':'ready',review:{review_id:'000000000000000000000002',version:edits+1,target_type:'specific_job',extraction,requirements_need_review:false},research:researching?null:{_id:'000000000000000000000003',version:1,last_researched_at:'2026-10-26T00:00:00Z',research_status:'succeeded',process:{round_count:null,stages:[{name:'Technical interview',assessment_type:'Coding exercise'}]},skills:[{name:'SQL joins',interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:['s1'],question_patterns:[]}],sources:[{source_id:'s1',platform:'brave',title:'Public interview report',url:'https://example.test/report',evidence:'Candidates report an SQL assessment.',reliability:'anecdotal',role_match:'related'}]},current:{selection_version:edits+1,goal:null},coverage:[{platform:'brave',status:'succeeded',useful_sources:1,target_sources:3,limit_reached:true}],error:null,retry_after:null};
 };
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/interview-prep'))return route.fulfill({json:{status:'ready',suggestions:null}});
  if(path.endsWith('/role-summary'))return route.fulfill({json:{status:'ready',summary:null}});
  if(path.endsWith('/context/assessment'))return route.fulfill({json:careerFixture(route.request().url(),{status:'no_cv',cv_uploaded:false,skills_evaluated:false})});
  if(path.endsWith('/workspace/jd')){extractions++;currentRole='Data Engineer';return route.fulfill({json:careerFixture(route.request().url(),state())});}
  if(path.endsWith('/workspace/messages')){edits++;return route.fulfill({json:careerFixture(route.request().url(),{reply:edits===1?'Which part would you like to change: your role, skills or location?':'Your goal has been updated.',edit_status:'clarifying'})});}
  return route.fulfill({json:careerFixture(route.request().url(),state())});
 });
 await page.goto('/career-goal');
 await expect(page.getByRole('heading',{level:1,name:'Backend Software Engineer'})).toBeVisible();
 for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:testInfo.outputPath(`career-goal-${width}.png`),fullPage:true});}
 await page.setViewportSize({width:1280,height:900});
 await expect(page.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 await expect(page.locator('#priorities-title')).toHaveText('Skills needed');
 await expect(page.getByText('Python',{exact:true})).toBeVisible();
 await page.getByText('Teamwork',{exact:true}).click();
 await expect(page.locator('.goal-skill-details:visible').getByText('Evaluate your skills to see where you stand.',{exact:true})).toBeVisible();
 await expect(page.getByRole('status').filter({hasText:'elo keeps working'})).toBeVisible();
 await expect(page.locator('.evaluate-banner')).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'Job description'})).toHaveCount(0);
 await expect(page.getByRole('complementary',{name:'Your starting point'})).toHaveCount(0);
 await page.getByRole('navigation',{name:'Career goal pages'}).getByRole('link',{name:'About the role'}).click();
 await page.getByText('Eligibility and commitment',{exact:true}).click();
 await expect(page.getByText('Degree in a related discipline',{exact:false}).first()).toBeVisible();
 researching=false;
 await page.getByRole('navigation',{name:'Career goal pages'}).getByRole('link',{name:'Interview preparation'}).click();
 await expect(page.locator('#interview-preparation')).toContainText('Technical interview');
 await page.screenshot({path:test.info().outputPath('goal-overview-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('goal-overview-mobile.png'),fullPage:true});
 await page.getByRole('link',{name:'Refine goal',exact:true}).click();
 await expect(page.getByRole('log')).toContainText('What would you like to refine');
 await page.getByRole('textbox',{name:'Message elo'}).fill('Help me refine my goal');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('log')).toContainText('Which part would you like to change');
 await page.getByRole('button',{name:'← Career Goal'}).click();
 await expect(page.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 await page.getByRole('button',{name:/Set a new goal/}).click();
 expect(extractions).toBe(0);
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill('A Data Engineer builds data pipelines. Python is required.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page).toHaveURL(/\/career-goal\/chat\?source=jd$/);
 await expect(page.getByRole('log')).toContainText('Let’s look at Data Engineer');
 await page.getByRole('button',{name:'← Career Goal',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Data Engineer',exact:true})).toBeVisible();
 expect(extractions).toBe(1);
 await page.reload();await expect(page.getByRole('heading',{name:'Data Engineer',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Add your skills first'})).toBeVisible();
 for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.locator('.evaluate-banner').screenshot({path:testInfo.outputPath(`evaluate-banner-${width}.png`)});}
 await page.setViewportSize({width:1280,height:900});
 await expect(page.getByRole('button',{name:'Evaluate skills'})).toHaveCount(0);
 await page.getByRole('link',{name:'Go to Skills Profile'}).click();
 await expect(page).toHaveURL(/\/cv$/);
 await expect(page.getByRole('heading',{name:'Skills Profile',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Upload your CV'})).toBeVisible();
 await expect(page.getByRole('textbox',{name:'Message elo'})).toHaveCount(0);
 await expect(page.getByLabel('CV document',{exact:true})).toBeEnabled();
});

test('research tabs keep partial results, citations and refresh on mobile',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{}})});
 });
 const goal={_id:'0'.repeat(24),version:1,target_type:'specific_job',role:'Software Engineering Intern',field:'Software',company:'Example',location:'Singapore',employment_type:'internship',seniority_level:null,job_url:null,skills:[],non_skill_requirements:[],responsibilities:[],summary:'Build software with the engineering team.'};
 const base={status:'completed',findings:[],missing_fields:[],warnings:[],error_code:null,researched_at:'2026-10-26T00:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
 const claim={finding_id:'f0000000000000001',field:'compensation',value:'SGD 1500 per month',confidence:'low',evidence_type:'candidate_reported',source_ids:['s1'],quotes:['An intern reports SGD 1500 per month.'],scope:'related_role',conflict_group:'salary',last_verified_at:'2026-10-26T00:00:00Z'};
 const source={source_id:'s1',url:'https://example.test/report',title:'Public intern report',platform:'other',published_date:null,retrieved_at:'2026-10-26T00:00:00Z'};
 let refreshed='';
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/interview-prep'))return route.fulfill({json:{status:'ready',suggestions:null}});
  if(path.endsWith('/role-summary'))return route.fulfill({json:{status:'ready',summary:null}});
  if(path.endsWith('/context/assessment'))return route.fulfill({json:careerFixture(route.request().url(),{status:'evaluated',cv_uploaded:true,skills_evaluated:true})});
  if(path.endsWith('/opportunity-research')){
   if(route.request().method()==='POST')refreshed=route.request().postDataJSON().category;
   return route.fulfill({json:careerFixture(route.request().url(),{available:true,status:'partial',finished:true,job_id:'job',career_target_id:goal._id,research:null,sources:[source],summary:{overview_refs:[],key_takeaway_refs:[claim.finding_id],consideration_refs:[]},categories:{interview_intelligence:{...base,status:'failed',error_code:'source_unavailable'},internship_insights:{...base,findings:[claim],missing_fields:['benefits','mentorship'],warnings:['Conflicting reports are preserved separately; figures are not averaged.']},career_progression:{...base,findings:[{...claim,finding_id:'f0000000000000002',field:'conversion_salary',value:'SGD 5000 monthly base salary, 2025'}]},conversion_outcomes:{...base,missing_fields:['conversion_rate','historical_cohort']},company_intelligence:{...base,missing_fields:['team_culture']}}})});
  }
  return route.fulfill({json:careerFixture(route.request().url(),{phase:'ready',review:{review_id:'1'.repeat(24),version:1,target_type:'specific_job',extraction:goal,requirements_need_review:false},current:{selection_version:1,goal},research:null,coverage:[],error:null,retry_after:null})});
 });
 await page.goto('/career-goal');
 await expect(page.getByRole('complementary',{name:'Your starting point'})).toHaveCount(0);
 const tabs=page.getByRole('navigation',{name:'Career goal pages'});
 await tabs.getByRole('link',{name:'Interview preparation'}).click();
 await expect(page).toHaveURL(/\/career-goal\/interview$/);
 await expect(page.getByText('Part of this research could not finish. Other results are preserved; refresh to retry.')).toHaveCount(0);
 await tabs.getByRole('link',{name:'About the role'}).click();
 const salary=page.locator('.fact-card').filter({has:page.getByRole('heading',{name:'Salary',exact:true})});
 await expect(salary).toContainText('SGD 1500 per month');await expect(salary).not.toContainText('low confidence');
 await expect(salary.getByRole('link',{name:'Public intern report ↗'})).toHaveAttribute('href','https://example.test/report');
 await expect(page.locator('.fact-card').filter({has:page.getByRole('heading',{name:'Full-time salary'})})).toContainText('SGD 5000 monthly base salary, 2025');
 await expect(page.locator('.fact-card').filter({has:page.getByRole('heading',{name:'Conversion rate'})})).toContainText('Not filled yet.');
 await expect(page.getByRole('note')).toContainText('may be inaccurate or out of date');
 await page.getByRole('button',{name:'Refresh research'}).click();
 await expect.poll(()=>refreshed).toBe(null);
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('opportunity-intelligence-mobile.png'),fullPage:true});
});


test('the grouped skill list supports keyboard disclosure, long lists, confirmed layout and small screens',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  const value=path.endsWith('/auth-config')?{mode:'email',google_enabled:false}:path.endsWith('/auth/session')?{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}:{version:1,onboarding_complete:true,occupational_status:'employed',education:{}};
  return route.fulfill({json:careerFixture(route.request().url(),value)});
 });
 let count=9;
 const longTitle='Ability to learn quickly, investigate failure modes, and iterate based on evidence and user feedback';
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/interview-prep'))return route.fulfill({json:{status:'ready',suggestions:null}});
  if(path.endsWith('/role-summary'))return route.fulfill({json:{status:'ready',summary:null}});
  if(path.endsWith('/context/assessment'))return route.fulfill({json:{status:'not_evaluated',cv_uploaded:true,skills_evaluated:false}});
  if(path.endsWith('/cv-confirmation'))return route.fulfill({json:{goal_id:'111111111111111111111111',goal_version:1,selection_version:1,confirmed:true,context:{id:'111111111111111111111111',version:1,selection_version:1,confirmed:true},reason:null}});
  const goal={_id:'111111111111111111111111',version:1,role:'Product Manager',field:'Product',target_type:'specific_job',skills:Array.from({length:count},(_,i)=>({item_id:`skill-${i}`,name:i===0?longTitle:`Product skill ${i}`,category:i%2?'AI':'Product Management',priority:i<6?'required':'preferred',origin:'employer',context:'Investigate product outcomes using evidence.',evidence:'Learn from user feedback.'}))};
  return route.fulfill({json:careerFixture(route.request().url(),{phase:'ready',current:{selection_version:1,goal}})});
 });
 await page.setViewportSize({width:1440,height:1000});await page.goto('/career-goal');
 await expect(page.locator('#priorities-title')).toHaveText('Skills needed');
 // Skills sit under category headings, most important group first, coloured by importance.
 const rows=page.locator('.goal-skill-row');
 await expect(rows).toHaveCount(9);
 await expect(page.locator('.goal-skill-category h3')).toHaveText(['Product Management','AI']);
 await expect(page.locator('.goal-skill-importance',{hasText:'Essential'})).toHaveCount(6);
 await expect(page.locator('.goal-skill-importance',{hasText:'Important'})).toHaveCount(3);
 const first=await rows.nth(0).boundingBox(),second=await rows.nth(1).boundingBox();
 expect(second!.x).toBe(first!.x);expect(second!.y).toBeGreaterThan(first!.y);
 await page.screenshot({path:test.info().outputPath('learning-focus-desktop.png'),fullPage:true});
 const toggle=page.getByRole('button',{name:longTitle,exact:true});await toggle.focus();await page.keyboard.press('Enter');
 await expect(toggle).toHaveAttribute('aria-expanded','true');
 await expect(page.locator(`#${await toggle.getAttribute('aria-controls')}`)).toBeVisible();
 expect((await rows.nth(1).boundingBox())!.height).toBe(second!.height);
 await page.keyboard.press('Space');await expect(toggle).toHaveAttribute('aria-expanded','false');
 for(const width of [360,390,768]){
  await page.setViewportSize({width,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.setViewportSize({width:360,height:844});
 expect((await rows.nth(1).boundingBox())!.y).toBeGreaterThan((await rows.nth(0).boundingBox())!.y);
 await page.screenshot({path:test.info().outputPath('learning-focus-mobile.png'),fullPage:true});
 count=30;await page.reload();
 await expect(rows).toHaveCount(10);
 await page.getByRole('button',{name:/^Show 20 more skills/}).click();
 await expect(rows).toHaveCount(30);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

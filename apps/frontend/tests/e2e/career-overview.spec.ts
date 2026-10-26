import {test,expect} from '@playwright/test';

test('saved goal categories, guided refinement, replacement and CV handoff on desktop and mobile',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{}}});
 });
 let currentRole='Backend Software Engineer',researching=true,edits=0,extractions=0;
 const state=()=>{
  const extraction={role:currentRole,field:'Software Engineering',company:'Example Technologies',location:'Singapore',seniority_level:'Entry level',job_url:null,summary:'Build and maintain backend services, APIs and reliable data systems.',responsibilities:['Build APIs and services','Collaborate with product teams'],skills:[{item_id:'python',name:'Python',category:'Technical',priority:'required',origin:'employer',evidence:'Python is required.'},{item_id:'team',name:'Teamwork',category:'Transferable',priority:'preferred',origin:'employer'}],non_skill_requirements:[{requirement_id:'degree',category:'Qualifications',description:'Degree in a related discipline',priority:'preferred',group_id:null,group_operator:'all',origin:'employer'}]};
  return {session_id:'000000000000000000000001',revision:edits+1,kind:'jd',phase:researching?'researching':'ready',review:{review_id:'000000000000000000000002',version:edits+1,target_type:'specific_job',extraction,baseline:extraction,requirements_need_review:false},research:researching?null:{_id:'000000000000000000000003',version:1,last_researched_at:'2026-10-26T00:00:00Z',research_status:'succeeded',process:{round_count:null,stages:[{name:'Technical interview',assessment_type:'Coding exercise'}]},skills:[{name:'SQL joins',interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:['s1'],question_patterns:[]}],sources:[{source_id:'s1',platform:'brave',title:'Public interview report',url:'https://example.test/report',evidence:'Candidates report an SQL assessment.',reliability:'anecdotal',role_match:'related'}]},current:{selection_version:edits+1,goal:null},coverage:[{platform:'brave',status:'succeeded',useful_sources:1,target_sources:3,limit_reached:true}],error:null,retry_after:null};
 };
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/context/assessment'))return route.fulfill({json:{status:'no_cv',cv_uploaded:false,skills_evaluated:false}});
  if(path.endsWith('/workspace/jd')){extractions++;currentRole='Data Engineer';return route.fulfill({json:state()});}
  if(path.endsWith('/workspace/messages')){edits++;return route.fulfill({json:{reply:edits===1?'Which part would you like to change: your role, skills or location?':'Your goal has been updated.',edit_status:'clarifying'}});}
  return route.fulfill({json:state()});
 });
 await page.goto('/career-goal');
 await expect(page.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Technical skills'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Transferable skills'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Qualifications',exact:true})).toBeVisible();
 await expect(page.getByRole('status')).toContainText('Researching interview expectations');
 await expect(page.getByRole('textbox',{name:'Job description'})).toHaveCount(0);
 await expect(page.getByRole('link',{name:/Assess my skills/})).toHaveAttribute('href','/cv');
 researching=false;
 await expect(page.getByRole('heading',{name:'Interview process',exact:true})).toBeVisible();
 await page.screenshot({path:test.info().outputPath('goal-overview-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('goal-overview-mobile.png'),fullPage:true});
 await page.getByRole('link',{name:'Refine goal',exact:true}).click();
 await expect(page.getByRole('log')).toContainText('What would you like to refine');
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('Help me refine my goal');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('log')).toContainText('Which part would you like to change');
 await page.getByRole('button',{name:'← Career Goal'}).click();
 await expect(page.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 await page.getByRole('button',{name:/Set a new goal/}).click();
 expect(extractions).toBe(0);
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill('A Data Engineer builds data pipelines. Python is required.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page).toHaveURL(/\/career-goal$/);
 await expect(page.getByRole('heading',{name:'Data Engineer',exact:true})).toBeVisible();
 expect(extractions).toBe(1);
 await page.reload();await expect(page.getByRole('heading',{name:'Data Engineer',exact:true})).toBeVisible();
 await page.getByRole('link',{name:/Assess my skills/}).click();
 await expect(page).toHaveURL(/\/cv$/);
 await expect(page.getByRole('heading',{name:'Resume & Tracker'})).toBeVisible();
});

test('Opportunity Intelligence preserves partial categories, citations and targeted refresh on mobile',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{}}});
 });
 const goal={_id:'0'.repeat(24),version:1,target_type:'specific_job',role:'Software Engineering Intern',field:'Software',company:'Example',location:'Singapore',employment_type:'internship',seniority_level:null,job_url:null,skills:[],non_skill_requirements:[],responsibilities:[],summary:'Build software with the engineering team.'};
 const base={status:'completed',findings:[],missing_fields:[],warnings:[],error_code:null,researched_at:'2026-10-26T00:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
 const claim={finding_id:'f0000000000000001',field:'compensation',value:'SGD 1500 per month',confidence:'low',evidence_type:'candidate_reported',source_ids:['s1'],quotes:['An intern reports SGD 1500 per month.'],scope:'related_role',conflict_group:'salary',last_verified_at:'2026-10-26T00:00:00Z'};
 const source={source_id:'s1',url:'https://example.test/report',title:'Public intern report',platform:'other',published_date:null,retrieved_at:'2026-10-26T00:00:00Z'};
 let refreshed='';
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/context/assessment'))return route.fulfill({json:{status:'evaluated',cv_uploaded:true,skills_evaluated:true}});
  if(path.endsWith('/opportunity-research')){
   if(route.request().method()==='POST')refreshed=route.request().postDataJSON().category;
   return route.fulfill({json:{available:true,status:'partial',finished:true,job_id:'job',career_target_id:goal._id,research:null,sources:[source],summary:{overview_refs:[],key_takeaway_refs:[claim.finding_id],consideration_refs:[]},categories:{interview_intelligence:{...base,status:'failed',error_code:'source_unavailable'},internship_insights:{...base,findings:[claim],missing_fields:['benefits','mentorship'],warnings:['Conflicting reports are preserved separately; figures are not averaged.']},company_intelligence:{...base,missing_fields:['tech_stack']}}}});
  }
  return route.fulfill({json:{phase:'ready',review:{review_id:'1'.repeat(24),version:1,target_type:'specific_job',extraction:goal,requirements_need_review:false},current:{selection_version:1,goal},research:null,coverage:[],error:null,retry_after:null}});
 });
 await page.goto('/career-goal');await expect(page.getByRole('heading',{name:'Opportunity Intelligence'})).toBeVisible();
 await expect(page.getByText('This category could not finish. Other results are preserved; refresh this section to retry.')).toBeVisible();
 await page.getByText('Internship Insights',{exact:true}).click();
 const internships=page.locator('details.intelligence-section').filter({has:page.getByText('Internship Insights',{exact:true})});
 await expect(internships).toContainText('SGD 1500 per month');await expect(internships).toContainText('low confidence');
 await internships.getByText('Evidence and sources',{exact:true}).click();
 await expect(internships.getByRole('link',{name:'Public intern report ↗'})).toHaveAttribute('href','https://example.test/report');
 await expect(internships).toContainText('Published: Unknown');
 await internships.getByRole('button',{name:'Refresh this section'}).click();
 await expect.poll(()=>refreshed).toBe('internship_insights');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('opportunity-intelligence-mobile.png'),fullPage:true});
});

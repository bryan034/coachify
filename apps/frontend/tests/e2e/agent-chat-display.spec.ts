import {test,expect} from '@playwright/test';

test('chat replaces observed activity with a Markdown answer on desktop and mobile',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false}});
 });
 const extraction={role:'Data Analyst',field:'Data',company:null,location:'Singapore',skills:[{name:'SQL',category:'Technical',priority:'required',origin:'employer'}],non_skill_requirements:[],responsibilities:[],summary:'Turn data into useful decisions.'};
 let failureMode='';
 let ready=false,complete!:()=>void;
 const answer=new Promise<void>(resolve=>{complete=resolve;});
 await page.route('**/api/v1/career/**',async route=>{
  if(route.request().url().endsWith('/workspace/messages')){
   if(failureMode)return route.fulfill({status:failureMode==='rate_limited'?429:503,json:{code:failureMode,detail:failureMode==='rate_limited'?'Your 7,000-token allowance has been reached.':'PRIVATE provider JSON diagnostic',...(failureMode==='rate_limited'?{retry_after:10}:{})}});
   await answer;
   return route.fulfill({json:{reply:'## Interview preparation\n\nStart with **SQL joins**.\n\n- Practise queries\n- Explain your approach\n\nUse `SELECT`.',proposed_skills:null}});
  }
  return route.fulfill({json:{session_id:'000000000000000000000001',revision:1,kind:'jd',phase:ready?'ready':'researching',review:{review_id:'000000000000000000000002',version:1,extraction,baseline:extraction,requirements_need_review:false},research:ready?{skills:[{name:'SQL',interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:[],question_patterns:[]}],sources:[]}:null,current:{selection_version:1,goal:null},coverage:[],error:null,retry_after:null}});
 });
 await page.goto('/career-goal/chat?source=jd');
 const log=page.getByRole('log');
 await expect(log.getByRole('status')).toContainText('Researching interview expectations with Brave');
 await page.screenshot({path:test.info().outputPath('researching-desktop.png'),fullPage:true});
 ready=true;
 await expect(log).toContainText('Let’s look at Data Analyst');
 await expect(log.getByRole('status')).toHaveCount(0);
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('How should I prepare?');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(log.getByRole('status')).toContainText('Preparing your answer');
 complete();
 const reply=log.locator('.agent-exchange .assistant').last();
 await expect(reply.getByRole('heading',{name:'Interview preparation'})).toBeVisible();
 await expect(reply.locator('strong')).toHaveText('SQL joins');
 await expect(reply.getByRole('listitem')).toHaveCount(2);
 await expect(reply.locator('.agent-reply')).toHaveAttribute('aria-busy','false');
 await expect(reply.locator('code')).toBeInViewport();
 await expect(log.getByRole('status')).toHaveCount(0);
 await page.screenshot({path:test.info().outputPath('answer-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.emulateMedia({reducedMotion:'reduce'});
 await expect(page.getByRole('textbox',{name:'Message Coachify'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('answer-mobile.png'),fullPage:true});
 failureMode='invalid_output';
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('Explain the assessment');
 const diagnostic=page.waitForResponse(r=>r.url().endsWith('/workspace/messages'));
 await page.getByRole('button',{name:'Send message'}).click();
 expect((await (await diagnostic).json()).code).toBe('invalid_output');
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
 await expect(log.getByRole('alert')).toHaveCount(0);
 await expect(page.getByText('PRIVATE provider JSON diagnostic')).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'Message Coachify'})).toHaveValue('Explain the assessment');
 failureMode='rate_limited';
 await page.getByRole('button',{name:'Retry',exact:true}).click();
 await expect(log.getByRole('alert')).toContainText('7,000-token allowance');
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeDisabled();
});

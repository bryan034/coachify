import {careerFixture} from './career-fixture';
import {test,expect} from '@playwright/test';

test('chat hides validation diagnostics and replaces repair activity with a Markdown answer on desktop and mobile',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false})});
 });
 const extraction={role:'Data Analyst',field:'Data',company:null,location:'Singapore',skills:[{name:'SQL',category:'Technical',priority:'required',origin:'employer'}],non_skill_requirements:[],responsibilities:[],summary:'Turn data into useful decisions.'};
 let failureMode='';
 let ready=false,answered=false;
 const complete=()=>{answered=true;};
 const operation={operation_id:'a'.repeat(32),status:'repairing',retry_after:null,result:null,validation_feedback:{reason:'schema_validation',fields:['reply'],violations:[{field:'reply',issue:'missing'}]}};
 await page.route('**/api/v1/career/**',async route=>{
  if(route.request().url().endsWith('/workspace/messages')){
   if(failureMode)return route.fulfill({status:failureMode==='rate_limited'?429:503,json:careerFixture(route.request().url(),{code:failureMode,detail:failureMode==='rate_limited'?'The AI provider quota was reached.':'PRIVATE provider JSON diagnostic',...(failureMode==='rate_limited'?{retry_after:10}:{})})});
   return route.fulfill({status:202,json:careerFixture(route.request().url(),operation)});
  }
  if(route.request().url().includes('/workspace/operations/')){
   if(!answered)return route.fulfill({json:careerFixture(route.request().url(),operation)});
   return route.fulfill({json:careerFixture(route.request().url(),{...operation,status:'succeeded',validation_feedback:null,result:{reply:'## Interview preparation\n\nStart with **SQL joins**.\n\n- Practise queries\n- Explain your approach\n\nUse `SELECT`.',proposed_skills:null}})});
  }
  return route.fulfill({json:careerFixture(route.request().url(),{session_id:'000000000000000000000001',revision:1,kind:'jd',phase:ready?'ready':'researching',review:{review_id:'000000000000000000000002',version:1,extraction,requirements_need_review:false},research:ready?{skills:[{name:'SQL',interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:['s1'],question_patterns:[]}],sources:[{source_id:'s1',platform:'brave',title:'Public interview report',url:'https://example.test/report',evidence:'Reported SQL exercise',reliability:'anecdotal',role_match:'related'}]}:null,current:{selection_version:1,goal:null},coverage:[],error:null,retry_after:null})});
 });
 await page.goto('/career-goal/chat?source=jd');
 const log=page.getByRole('log');
 await expect(log.getByRole('status')).toContainText('Researching interview expectations');
 await expect(log).not.toContainText('Let’s look at Data Analyst');
 await expect(log.getByRole('heading',{name:'Interview findings'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Resume research'})).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'Message elo'})).toBeDisabled();
 await page.screenshot({path:test.info().outputPath('researching-desktop.png'),fullPage:true});
 ready=true;
 await expect(log).toContainText('Let’s look at Data Analyst');
 await expect(log.getByRole('heading',{name:'Interview findings'})).toBeVisible();
 await expect(log.locator('.agent-message').filter({has:page.getByRole('heading',{name:'Your career goal'})})).toContainText('Interview findings');
 await expect(log.getByRole('status')).toHaveCount(0);
 await page.getByRole('textbox',{name:'Message elo'}).fill('How should I prepare?');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(log.getByRole('status')).toContainText('Refining the response');
 await expect(log.getByRole('alert')).toHaveCount(0);
 await expect(log).not.toContainText('schema_validation');
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toHaveCount(0);
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
 await expect(page.getByRole('textbox',{name:'Message elo'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.getByRole('button',{name:'Role and research details'}).click();
 await expect(page.locator('.agent-details a').first()).toHaveAttribute('href','https://example.test/report');
 await page.getByRole('button',{name:'Hide details'}).click();
 await page.screenshot({path:test.info().outputPath('answer-mobile.png'),fullPage:true});
 failureMode='invalid_output';
 await page.getByRole('textbox',{name:'Message elo'}).fill('Explain the assessment');
 const diagnostic=page.waitForResponse(r=>r.url().endsWith('/workspace/messages'));
 await page.getByRole('button',{name:'Send message'}).click();
 expect((await (await diagnostic).json()).code).toBe('invalid_output');
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
 await expect(log.getByRole('alert')).toContainText('The AI returned an answer that could not be validated');
 await expect(page.getByText('PRIVATE provider JSON diagnostic')).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'Message elo'})).toHaveValue('Explain the assessment');
 failureMode='rate_limited';
 await page.getByRole('button',{name:'Retry',exact:true}).click();
 await expect(log.getByRole('alert')).toContainText('AI provider quota');
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeDisabled();
});

test('career goal changes use guided chat without an edit form or Apply button',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{}})});
 });
 const extraction={role:'Data Analyst',field:'Data',company:null,location:'Singapore',skills:[],non_skill_requirements:[],responsibilities:[],summary:'Analyse business data.'};
 let version=1,location='Singapore',turn=0;
 const workspace=()=>({session_id:'000000000000000000000001',revision:version,kind:'jd',phase:'ready',review:{review_id:'000000000000000000000002',version,target_type:'specific_job',extraction:{...extraction,location},requirements_need_review:false},research:{skills:[],sources:[]},current:{selection_version:version,goal:null},coverage:[],error:null,retry_after:null});
 const jobs=new Map<string,unknown>();let patches=0;
 await page.route('**/api/v1/career/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(route.request().method()==='PATCH')patches++;
  if(path.endsWith('/workspace/messages')){
   turn++;let result:unknown;
   if(turn===1)result={reply:'Which part would you like to change: role, location or skills?',proposed_skills:null,edit_status:'clarifying'};
   else if(turn===2)result={reply:'Which city or country should the job be based in?',proposed_skills:null,edit_status:'clarifying'};
   else {location='London';version++;result={reply:'Your goal location is now London.',proposed_skills:null,edit_status:'saved',workspace:workspace()};}
   const id=turn.toString(16).padStart(32,'0');jobs.set(id,result);
   return route.fulfill({status:202,json:careerFixture(route.request().url(),{operation_id:id,status:'running',result:null,retry_after:null})});
  }
  if(path.includes('/workspace/operations/')){
   const id=path.split('/').at(-1)!;
   return route.fulfill({json:careerFixture(route.request().url(),{operation_id:id,status:'succeeded',result:jobs.get(id),retry_after:null})});
  }
  return route.fulfill({json:careerFixture(route.request().url(),workspace())});
 });
 await page.goto('/career-goal/chat?source=jd');
 const log=page.getByRole('log'),box=page.getByRole('textbox',{name:'Message elo'});
 await expect(log).toContainText('Let’s look at Data Analyst');
 await expect(page.getByRole('button',{name:'Edit career goal',exact:true})).toHaveCount(0);
 await expect(page.getByRole('form',{name:'Edit career goal review'})).toHaveCount(0);
 for(const [message,reply] of [
  ['Change my goal','Which part would you like to change: role, location or skills?'],
  ['The location','Which city or country should the job be based in?'],
  ['London','Your goal location is now London.'],
 ]){
  await box.fill(message);await page.getByRole('button',{name:'Send message'}).click();await expect(log).toContainText(reply);
 }
 await expect(log).toContainText('Location: London');
 await page.reload();
 await expect(log).toContainText('Location: London');
 await expect(page.getByRole('button',{name:'Apply skill changes',exact:true})).toHaveCount(0);
 expect(patches).toBe(0);
 await page.screenshot({path:test.info().outputPath('guided-goal-edit-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('guided-goal-edit-mobile.png'),fullPage:true});
});

test('typing preserves scroll position and research citations sit beside supported claims',async({page})=>{
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{}})});
 });
 const extraction={role:'Data Analyst',field:'Data',company:null,location:'Singapore',skills:[],non_skill_requirements:[],responsibilities:[],summary:Array.from({length:80},(_,i)=>`Preparation paragraph ${i}: understand the role and practise explaining your decisions.`).join('\n\n')};
 await page.route('**/api/v1/career/**',route=>route.fulfill({json:careerFixture(route.request().url(),{session_id:'synthetic',revision:1,kind:'jd',phase:'ready',review:{review_id:'review',version:1,extraction},research:{skills:[{name:'SQL joins',interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:['s1']}],process:{round_count:2,round_count_evidence:{source_ids:['s1'],text:'Two rounds'},stages:[]},sources:[{source_id:'s1',platform:'brave',url:'https://www.example.test/interview#rounds'}]},current:{selection_version:1,goal:null},coverage:[],error:null,retry_after:null})}));
 await page.goto('/career-goal/chat?source=jd');
 const log=page.getByRole('log'),reply=log.locator('.agent-reply').first();
 await expect.poll(()=>log.evaluate(el=>el.scrollHeight-el.clientHeight)).toBeGreaterThan(400);
 await log.hover();await page.mouse.wheel(0,-350);
 await expect(page.getByRole('button',{name:/Jump to latest/})).toBeVisible();
 const before=await log.evaluate(el=>({top:el.scrollTop,length:el.textContent!.length}));
 await expect.poll(()=>log.evaluate(el=>el.textContent!.length)).toBeGreaterThan(before.length+100);
 expect(Math.abs(await log.evaluate(el=>el.scrollTop)-before.top)).toBeLessThan(3);
 await page.getByRole('button',{name:/Jump to latest/}).click();
 await expect.poll(()=>log.evaluate(el=>el.scrollHeight-el.clientHeight-el.scrollTop)).toBeLessThan(5);
 await reply.getByRole('button',{name:'Show full response'}).click();
 const claim=log.getByRole('listitem').filter({hasText:'SQL joins'});
 await expect(claim.getByRole('link',{name:'example.test'})).toHaveAttribute('href','https://www.example.test/interview#rounds');
 await expect(log.getByRole('listitem').filter({hasText:'Reported interview rounds:'}).getByRole('link',{name:'example.test'})).toBeVisible();
 await page.screenshot({path:test.info().outputPath('inline-citations-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect(claim.getByRole('link',{name:'example.test'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

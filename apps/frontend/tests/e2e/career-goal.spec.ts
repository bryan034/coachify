import {careerFixture} from './career-fixture';
import {test,expect,type Page} from '@playwright/test';
async function workspace(page:Page){
 let sessionChecks=0;
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session')){sessionChecks++;return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});}
  if(path.endsWith('/school-categories'))return route.fulfill({json:careerFixture(route.request().url(),[])});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false})});
 });
 await page.route('**/api/v1/career/workspace',route=>route.fulfill({json:careerFixture(route.request().url(),{phase:'empty',review:null,current:{goal:null},exploration_id:null})}));
 return {checks:()=>sessionChecks};
}
test('Career Goal supports three temporary inputs, recovery and responsive navigation',async({page})=>{
 await workspace(page);const calls:string[]=[];
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;if(route.request().method()==='GET')return route.fulfill({json:careerFixture(route.request().url(),path.endsWith('/workspace')?{phase:'empty',current:{goal:null}}:{goals:[],reviews:[]})});calls.push(path);
  expect(route.request().headers().authorization).toBe('Bearer synthetic-session');
  if(path.endsWith('/url')){
   const {url}=route.request().postDataJSON();
   if(url.includes('blocked'))return route.fulfill({status:422,json:careerFixture(route.request().url(),{detail:'This website restricts automated access. Paste the description instead.'})});
   return route.fulfill({json:careerFixture(route.request().url(),{kind:'url',text:'Imported analyst\n• SQL',source_name:'example.test',source_url:url,notices:['Review this temporary preview.']})});
  }
  return route.fulfill({json:careerFixture(route.request().url(),{kind:'document',text:'Document analyst\n• Communication',source_name:'role.txt',notices:[]})});
 });
 await page.goto('/career-goal');
 await expect(page.getByRole('heading',{level:1,name:'Career Goal',exact:true})).toBeVisible();
 const labels=await page.getByRole('navigation').getByRole('link').allTextContents();expect(labels.slice(0,3)).toEqual(['Home','Career Goal','Roadmap']);
 await expect(page.getByRole('navigation').getByRole('link',{name:'Career Goal',exact:true})).toHaveAttribute('aria-current','page');
 const pasted='Analyst 🧭\n\n• Research & SQL\n';
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill(pasted);
 expect(calls).toHaveLength(0);
 await page.getByRole('tab',{name:'Job URL'}).click();
 await page.getByLabel('Job description URL',{exact:true}).fill('https://example.test/job');
 await page.getByRole('button',{name:'Import job page'}).click();
 await expect(page.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('Imported analyst\n• SQL');
 await expect(page.getByText('Imported page',{exact:true})).toHaveCount(0);
 await page.getByRole('textbox',{name:'Review and edit the preview'}).fill('Edited preview');
 await page.getByLabel('Job description URL',{exact:true}).fill('https://example.test/blocked');
 page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'Import job page'}).click();
 await expect(page.getByRole('tabpanel').getByRole('alert')).toContainText('restricts automated access');
 await expect(page.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('Edited preview');
 await page.getByRole('tab',{name:'Upload document'}).click();
 await page.getByLabel('Job description document',{exact:true}).setInputFiles({name:'role.txt',mimeType:'text/plain',buffer:Buffer.from('Document analyst\n• Communication')});
 await expect(page.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('Document analyst\n• Communication');
 await expect(page.getByRole('button',{name:'Read document',exact:true})).toHaveCount(0);
 await page.getByRole('tab',{name:'Paste description'}).click();
 await expect(page.getByRole('textbox',{name:'Job description',exact:true})).toHaveValue(pasted);
 const stored=await page.evaluate(()=>JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]));
 expect(stored).not.toContain('Research');expect(stored).not.toContain('Edited preview');
 page.once('dialog',dialog=>dialog.dismiss());await page.getByRole('navigation').getByRole('link',{name:'Home',exact:true}).click();
 await expect(page).toHaveURL(/\/career-goal$/);
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('tab',{name:'Job URL'}).focus();await page.keyboard.press('ArrowRight');
 await expect(page.getByRole('tab',{name:'Upload document'})).toBeFocused();
 page.once('dialog',dialog=>dialog.accept());await page.reload();
 await expect(page.getByRole('textbox',{name:'Job description',exact:true})).toHaveValue('');
 expect(calls).toEqual(['/api/v1/career/imports/url','/api/v1/career/imports/url','/api/v1/career/imports/document']);
});

test('late Career imports cannot restore content after the page is left',async({page})=>{
 await workspace(page);
 let release!:(value:unknown)=>void;
 const held=new Promise(resolve=>{release=resolve;});
 await page.route('**/api/v1/career/imports/url',async route=>{await held;await route.fulfill({json:careerFixture(route.request().url(),{kind:'url',text:'Old private source',source_name:'old.test',notices:[]})}).catch(()=>{});});
 await page.goto('/career-goal');
 await page.getByRole('tab',{name:'Job URL'}).click();await page.getByLabel('Job description URL',{exact:true}).fill('https://example.test/job');
 await page.getByRole('button',{name:'Import job page'}).click();
 await expect(page.getByText('Preparing a temporary preview. You can switch methods to cancel.')).toBeVisible();
 await page.getByRole('tab',{name:'Paste description'}).click();release(null);
 await expect(page.getByRole('textbox',{name:'Job description',exact:true})).toHaveValue('');
 await page.getByRole('tab',{name:'Job URL'}).click();await expect(page.getByText('Old private source')).toHaveCount(0);
});

function prepared(){
 const extraction={role:'Analyst',field:'Data',company:null,location:'Singapore',seniority_level:null,job_url:null,summary:'Interpret data for decisions.',responsibilities:['Analyse data'],skills:[{item_id:'sql',name:'SQL',category:'Technical',priority:'required',origin:'employer',evidence:'SQL required.'}],non_skill_requirements:[]};
 return {session_id:'000000000000000000000071',revision:1,kind:'jd',phase:'ready',review:{review_id:'000000000000000000000081',version:1,target_type:'specific_job',extraction,metadata_origins:{},requirements_need_review:false,is_confirmed:false,generation:{}},current:{selection_version:1,goal:null,dependent_results_need_review:false},research:{_id:'000000000000000000000091',version:1,research_status:'succeeded',last_researched_at:'2026-01-01T00:00:00Z',skills:[{name:'SQL',category:'Technical',skill_id:null,interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:['s1'],question_patterns:[],independent_report_count:0}],sources:[{source_id:'s1',platform:'reddit',title:'Public interview report',url:'https://example.test/report',evidence:'Reported SQL exercise',reliability:'anecdotal',role_match:'related',published_date:null}]},coverage:[{platform:'brave',status:'succeeded'},{platform:'reddit',status:'succeeded'}],error:null,retry_after:null,expires_at:null,exploration_id:null};
}

test('reopening a pending JD reconnects and reaches the saved goal without a 409 loop',async({page})=>{
 await workspace(page);let complete=false;const keys:string[]=[];
 const operation={operation_id:'e'.repeat(32),status:'waiting_quota',retry_after:1,result:null};
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/workspace/jd')){
   const key=route.request().headers()['idempotency-key'];keys.push(key);
   if(keys.length>1&&key!==keys[0])return route.fulfill({status:409,json:careerFixture(route.request().url(),{code:'operation_in_progress',detail:'An operation is already running.'})});
   return route.fulfill({status:202,json:careerFixture(route.request().url(),operation)});
  }
  if(path.includes('/workspace/operations/'))return route.fulfill({json:careerFixture(route.request().url(),complete?{...operation,status:'succeeded',retry_after:null,result:prepared()}:operation)});
  if(path.endsWith('/context/assessment'))return route.fulfill({json:careerFixture(route.request().url(),{status:'no_cv',cv_uploaded:false,skills_evaluated:false})});
  return route.fulfill({json:careerFixture(route.request().url(),complete?prepared():{phase:'empty',review:null,current:{goal:null},exploration_id:null})});
 });
 await page.goto('/career-goal');
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill('Synthetic analyst position. SQL is required.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page.getByRole('status')).toContainText('Waiting for the research service to resume');
 await page.getByRole('navigation').getByRole('link',{name:'Career Goal',exact:true}).click();
 await expect(page.getByRole('textbox',{name:'Job description',exact:true})).toHaveValue('Synthetic analyst position. SQL is required.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page.getByRole('status')).toContainText('Waiting for the research service to resume');
 expect(keys).toHaveLength(2);expect(keys[1]).toBe(keys[0]);
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:test.info().outputPath('reconnected-extraction-mobile.png'),fullPage:true});
 complete=true;
 await expect(page.getByRole('log')).toContainText('Let’s look at Analyst');
 await expect(page).toHaveURL(/\/career-goal\/chat\?source=jd$/);
 await expect(page.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
 await page.getByRole('button',{name:'← Career Goal',exact:true}).click();
 await expect(page).toHaveURL(/\/career-goal$/);
 await expect(page.getByRole('heading',{name:'Analyst',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

test('one exploration conversation chooses a role without a confirmation step',async({page})=>{
 await workspace(page);let chosen=false,turns=0;
 const draft={_id:'000000000000000000000001',version:1,answers:{},turns:[] as unknown[],cv:{mode:'none',filename:null,cv_id:null},interests:['Data'],preferences:[],suggestions:[] as unknown[],next_question:'aspirations' as string|null,question_text:'What would you like to achieve?' as string|null,context_complete:false};
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/workspace'))return route.fulfill({json:careerFixture(route.request().url(),chosen?prepared():{phase:'empty',review:null,exploration_id:null})});
  if(path.endsWith('/direction')){expect(route.request().postDataJSON().index).toBe(0);chosen=true;return route.fulfill({json:careerFixture(route.request().url(),prepared())});}
  if(path.endsWith('/context'))return route.fulfill({json:careerFixture(route.request().url(),{cvs:[],cv_service_available:true,ai_available:true})});
  if(path.endsWith('/goals/current'))return route.fulfill({json:careerFixture(route.request().url(),{selection_version:0,goal:null})});
  if(path.endsWith('/explorations'))return route.fulfill({json:careerFixture(route.request().url(),draft)});
  if(path.endsWith('/messages')){turns++;const input=route.request().postDataJSON();draft.version++;draft.context_complete=true;draft.next_question=null;draft.suggestions=[{role:'Analyst',field:'Data',rationale:'Based on your interests.',uncertainty:'Capabilities need review.'}];draft.turns.push({answer:{value:input.answer},reply:'Analytics is a direction to explore.'});return route.fulfill({json:careerFixture(route.request().url(),draft)});}
  return route.fulfill({json:careerFixture(route.request().url(),draft)});
 });
 await page.goto('/career-goal/chat');await page.getByRole('checkbox',{name:/Allow elo/}).check();await page.getByRole('textbox',{name:'Message elo'}).fill('I enjoy working with data');await page.getByRole('button',{name:'Send message'}).click();
 await page.getByRole('button',{name:'Explore this direction'}).click();
 await expect(page.getByRole('log')).toContainText('Let’s look at Analyst');
 await expect(page.getByRole('button',{name:/Confirm.*goal/})).toHaveCount(0);
 await page.reload();await expect(page.getByRole('log')).toContainText('SQL exercise');expect(turns).toBe(1);
});

test('switching tabs and healthy revalidation preserve JD drafts after five minutes',async({page,context})=>{
 await page.clock.install();
 const session=await workspace(page);await page.goto('/career-goal');
 const input=page.getByRole('textbox',{name:'Job description',exact:true});
 await input.fill('Unsaved synthetic requirements: SQL.');
 const other=await context.newPage();await other.goto('about:blank');await other.bringToFront();
 await page.bringToFront();
 await expect(input).toHaveValue('Unsaved synthetic requirements: SQL.');
 const checks=session.checks();
 await page.evaluate(()=>{
  Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
  document.dispatchEvent(new Event('visibilitychange'));
 });
 await page.clock.fastForward(5*60*1000+1000);
 expect(session.checks()).toBe(checks);
 await expect(input).toHaveValue('Unsaved synthetic requirements: SQL.');
 await expect(page.getByRole('button',{name:'Refresh application'})).toHaveCount(0);
 await page.evaluate(()=>{
  Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
  document.dispatchEvent(new Event('visibilitychange'));
 });
 await expect.poll(()=>session.checks()).toBeGreaterThan(checks);
 await expect(input).toBeEditable();
 await expect(input).toHaveValue('Unsaved synthetic requirements: SQL.');
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect(page.getByRole('alertdialog')).toHaveCount(0);
 expect(await input.evaluate(el=>!!el.closest('[inert]'))).toBe(false);
 await input.fill('Unsaved synthetic requirements: SQL and Python.');
 await expect(input).toHaveValue('Unsaved synthetic requirements: SQL and Python.');
 await other.close();
});

test('JD extraction stays in chat with observed progress, typed summaries and saved cards',async({page})=>{
 await workspace(page);let complete=false;
 const operation={operation_id:'f'.repeat(32),status:'running',retry_after:null,result:null,activities:['identifying_job','extracting_requirements','searching_interviews','PRIVATE Brave tool output']};
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/workspace/jd'))return route.fulfill({status:202,json:careerFixture(route.request().url(),operation)});
  if(path.includes('/workspace/operations/'))return route.fulfill({json:careerFixture(route.request().url(),complete?{...operation,status:'succeeded',result:prepared()}:operation)});
  if(path.endsWith('/workspace/messages'))return route.fulfill({json:careerFixture(route.request().url(),{reply:'SQL is required for the saved Analyst goal.',proposed_skills:null})});
  if(path.endsWith('/context/assessment'))return route.fulfill({json:careerFixture(route.request().url(),{status:'no_cv',cv_uploaded:false,skills_evaluated:false})});
  return route.fulfill({json:careerFixture(route.request().url(),complete?prepared():{phase:'empty',review:null,current:{goal:null},exploration_id:null})});
 });
 await page.setViewportSize({width:390,height:844});
 await page.goto('/career-goal');
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill('Analyst in Singapore. SQL is required.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 const progress=page.getByRole('status',{name:'Career goal progress'});
 await expect(progress).toContainText('Searching for relevant interview experiences');
 await expect(progress).not.toContainText(/Brave|API|PRIVATE/);
 await page.screenshot({path:test.info().outputPath('jd-chat-progress-mobile.png'),fullPage:true});
 complete=true;
 await expect(page.getByRole('heading',{name:'Your career goal',exact:true})).toBeVisible();
 expect(await page.locator('.agent-reply[aria-busy="true"]').count()).toBeGreaterThan(0);
 await expect(page).toHaveURL(/\/career-goal\/chat\?source=jd$/);
 await expect(page.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
 await page.getByRole('textbox',{name:'Message elo'}).fill('Which skills are needed for this goal?');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('log')).toContainText('SQL is required for the saved Analyst goal.');
 await page.screenshot({path:test.info().outputPath('jd-chat-summary-mobile.png'),fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:'← Career Goal',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Analyst',exact:true})).toBeVisible();
});

test('malformed extraction JSON keeps the draft and retries without crashing or changing the request key',async({page})=>{
 await workspace(page);let submissions=0;const keys:string[]=[];const pageErrors:string[]=[];
 page.on('pageerror',error=>pageErrors.push(error.message));
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/workspace/jd')){
   submissions++;keys.push(route.request().headers()['idempotency-key']);
   return route.fulfill({status:202,json:{operation_id:'d'.repeat(32),status:'running',result:null,retry_after:null}});
  }
  if(path.includes('/workspace/operations/'))return route.fulfill({json:{operation_id:'d'.repeat(32),status:'succeeded',result:submissions===1?{current:{goal:{skills:{name:'PRIVATE malformed result'}}}}:careerFixture('http://fixture.test/api/v1/career/workspace',prepared())}});
  return route.fulfill({json:careerFixture(route.request().url(),submissions>1?prepared():{phase:'empty',current:{goal:null}})});
 });
 await page.goto('/career-goal');
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill('Synthetic analyst position. SQL is required.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page.getByRole('log').getByRole('alert')).toContainText('Career returned an invalid response');
 await expect(page.getByRole('log')).not.toContainText('PRIVATE');
 await expect(page.getByRole('textbox',{name:'Message elo'})).toBeDisabled();
 await page.getByRole('button',{name:'Retry',exact:true}).click();
 await expect(page.getByRole('log')).toContainText('Ask me anything about this goal set!');
 expect(submissions).toBe(2);expect(keys[1]).toBe(keys[0]);expect(pageErrors).toEqual([]);
 await expect(page.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
});

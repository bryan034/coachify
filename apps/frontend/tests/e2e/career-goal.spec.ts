import {test,expect,type Page} from '@playwright/test';
async function workspace(page:Page){
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
  if(path.endsWith('/school-categories'))return route.fulfill({json:[]});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false}});
 });
}
test('Career Goal supports three temporary inputs, recovery and responsive navigation',async({page})=>{
 await workspace(page);const calls:string[]=[];
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;if(route.request().method()==='GET')return route.fulfill({json:{goals:[],reviews:[]}});calls.push(path);
  expect(route.request().headers().authorization).toBe('Bearer synthetic-session');
  if(path.endsWith('/url')){
   const {url}=route.request().postDataJSON();
   if(url.includes('blocked'))return route.fulfill({status:422,json:{detail:'This website restricts automated access. Paste the description instead.'}});
   return route.fulfill({json:{kind:'url',text:'Imported analyst\n• SQL',source_name:'example.test',source_url:url,notices:['Review this temporary preview.']}});
  }
  return route.fulfill({json:{kind:'document',text:'Document analyst\n• Communication',source_name:'role.txt',notices:[]}});
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
 await page.route('**/api/v1/career/imports/url',async route=>{await held;await route.fulfill({json:{kind:'url',text:'Old private source',source_name:'old.test',notices:[]}}).catch(()=>{});});
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
 return {session_id:'000000000000000000000071',revision:1,kind:'jd',phase:'ready',review:{review_id:'000000000000000000000081',version:1,target_type:'specific_job',extraction,baseline:structuredClone(extraction),metadata_origins:{},requirements_need_review:false,is_confirmed:false,generation:{}},current:{selection_version:1,goal:null,dependent_results_need_review:false},research:{_id:'000000000000000000000091',version:1,research_status:'succeeded',last_researched_at:'2026-01-01T00:00:00Z',skills:[{name:'SQL',category:'Technical',skill_id:null,interview_stage:'Technical interview',assessment_type:'SQL exercise',source_ids:['s1'],question_patterns:[],independent_report_count:0}],sources:[{source_id:'s1',platform:'reddit',title:'Public interview report',url:'https://example.test/report',evidence:'Reported SQL exercise',reliability:'anecdotal',role_match:'related',published_date:null}]},coverage:[{platform:'brave',status:'succeeded'},{platform:'reddit',status:'succeeded'}],error:null,retry_after:null,expires_at:null,exploration_id:null};
}

test('one exploration conversation chooses a role without a confirmation step',async({page})=>{
 await workspace(page);let chosen=false,turns=0;
 const draft={_id:'000000000000000000000001',version:1,answers:{},turns:[] as unknown[],cv:{mode:'none',filename:null,cv_id:null},interests:['Data'],preferences:[],suggestions:[] as unknown[],next_question:'aspirations' as string|null,question_text:'What would you like to achieve?' as string|null,context_complete:false};
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/workspace'))return route.fulfill({json:chosen?prepared():{phase:'empty',review:null,exploration_id:null}});
  if(path.endsWith('/direction')){expect(route.request().postDataJSON().index).toBe(0);chosen=true;return route.fulfill({json:prepared()});}
  if(path.endsWith('/context'))return route.fulfill({json:{cvs:[],cv_service_available:true,ai_available:true}});
  if(path.endsWith('/goals/current'))return route.fulfill({json:{selection_version:0,goal:null}});
  if(path.endsWith('/explorations'))return route.fulfill({json:draft});
  if(path.endsWith('/messages')){turns++;const input=route.request().postDataJSON();draft.version++;draft.context_complete=true;draft.next_question=null;draft.suggestions=[{role:'Analyst',field:'Data',rationale:'Based on your interests.',uncertainty:'Capabilities need review.'}];draft.turns.push({answer:{value:input.answer},reply:'Analytics is a direction to explore.'});return route.fulfill({json:draft});}
  return route.fulfill({json:draft});
 });
 await page.goto('/career-goal/chat');await page.getByRole('checkbox',{name:/Allow Coachify/}).check();await page.getByRole('textbox',{name:'Message Coachify'}).fill('I enjoy working with data');await page.getByRole('button',{name:'Send message'}).click();
 await page.getByRole('button',{name:'Explore this direction'}).click();
 await expect(page.getByRole('log')).toContainText('Let’s look at Analyst');
 await expect(page.getByRole('button',{name:/Confirm.*goal/})).toHaveCount(0);
 await page.reload();await expect(page.getByRole('log')).toContainText('SQL exercise');expect(turns).toBe(1);
});

test('JD extraction researches before chat, autosaves edits and restores the latest goal',async({page})=>{
 await workspace(page);let active=prepared(),created=false;const calls:string[]=[];
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname,method=route.request().method();if(method!=='GET')calls.push(path);
  if(path.endsWith('/workspace/jd')){created=true;active={...active,phase:'researching'};return route.fulfill({json:active});}
  if(path.endsWith('/workspace/review')){const body=route.request().postDataJSON();expect(body.session_id).toBe(active.session_id);active={...active,revision:2,review:{...active.review,version:2,extraction:body.content}};return route.fulfill({json:active});}
  if(path.endsWith('/workspace/messages'))return route.fulfill({json:{reply:'Practise SQL joins for the reported assessment.',proposed_skills:null}});
  if(path.endsWith('/workspace')){active={...active,phase:'ready'};return route.fulfill({json:created?active:{phase:'empty',review:null}});}
  return route.fulfill({status:404,json:{detail:'Not found'}});
 });
 await page.goto('/career-goal');await page.getByRole('textbox',{name:'Job description',exact:true}).fill('Data analyst. SQL required.');await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page.getByRole('status').filter({hasText:'Researching interviews'})).toBeVisible();await expect(page.getByRole('button',{name:'Send message'})).toBeDisabled();
 await expect(page.getByRole('log')).toContainText('Let’s look at Analyst');await expect(page.getByRole('log')).toContainText('SQL exercise');
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('How should I prepare?');await page.getByRole('button',{name:'Send message'}).click();await expect(page.getByRole('log')).toContainText('Practise SQL joins');
 await page.getByRole('button',{name:'Edit career goal'}).click();await page.getByRole('textbox',{name:'Company',exact:true}).fill('Example Company');await page.getByRole('checkbox',{name:/I have reviewed/}).check();await page.getByRole('button',{name:'Save review'}).click();
 await expect(page.getByRole('log')).toContainText('Example Company');await expect(page.getByRole('button',{name:/Confirm.*goal/})).toHaveCount(0);
 await page.reload();await expect(page.getByRole('log')).toContainText('Example Company');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Role and research details'}).click();await page.getByText('Public interview report',{exact:true}).click();await expect(page.getByRole('link',{name:'View source'})).toHaveAttribute('href','https://example.test/report');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('single-goal-mobile.png'),fullPage:true});
 expect(calls.filter(p=>p.endsWith('/workspace/jd'))).toHaveLength(1);expect(calls.some(p=>p.endsWith('/confirm'))).toBe(false);
});

test('switching tabs keeps JD work and five-minute inactivity requires an explicit refresh',async({page,context})=>{
 await workspace(page);await page.goto('/career-goal');
 const input=page.getByRole('textbox',{name:'Job description',exact:true});
 await input.fill('Unsaved synthetic requirements: SQL.');
 const other=await context.newPage();await other.goto('about:blank');await other.bringToFront();
 await page.bringToFront();
 await expect(input).toHaveValue('Unsaved synthetic requirements: SQL.');
 await page.clock.install();await page.clock.fastForward(5*60*1000+1000);
 await expect(page.getByRole('alertdialog')).toContainText('Refresh required');
 await expect(page.getByRole('button',{name:'Refresh application'})).toBeFocused();
 expect(await input.inputValue()).toBe('Unsaved synthetic requirements: SQL.');
 expect(await input.evaluate(el=>!!el.closest('[inert]'))).toBe(true);
 await other.close();
});

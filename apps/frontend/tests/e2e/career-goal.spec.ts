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
  const path=new URL(route.request().url()).pathname;calls.push(path);
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

test('one agent chat adapts follow-ups, confirms a direction and restores progress',async({page})=>{
 await workspace(page);
 let draft={_id:'000000000000000000000001',version:1,answers:{} as Record<string,unknown>,turns:[] as unknown[],
  cv:{mode:'none',filename:null,cv_id:null},interests:['Data'],preferences:['Singapore'],suggestions:[] as unknown[],
  next_question:'aspirations' as string|null,question_text:'What would you like to achieve?' as string|null,context_complete:false};
 let current:{selection_version:number;goal:Record<string,unknown>|null;dependent_results_need_review:boolean}={selection_version:0,goal:null,dependent_results_need_review:false};
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/context'))return route.fulfill({json:{cvs:[],cv_service_available:true,ai_available:true}});
  if(path.endsWith('/goals/current'))return route.fulfill({json:current});
  if(path.endsWith('/goals'))return route.fulfill({json:{goals:current.goal?[current.goal]:[],explorations:[draft]}});
  if(path.endsWith('/explorations')||path.endsWith('/explorations/'+draft._id))return route.fulfill({json:draft});
  if(path.endsWith('/messages')){
   const body=route.request().postDataJSON();expect(body.attachment_text).toBeNull();
   const complete=draft.version===2;
   draft={...draft,version:draft.version+1,next_question:complete?null:'aspirations',
    question_text:complete?null:'What kind of work would feel meaningful to you?',context_complete:complete,
    turns:[...draft.turns,{question:'aspirations',answer:{status:'answered',value:body.answer},reply:complete?'Analytics is one possible direction.':'What kind of work would feel meaningful to you?'}]};
   if(complete)draft.suggestions=[{role:'Data analyst',field:'Analytics',rationale:'An option to explore based on your interests.',uncertainty:'Your current proficiency remains unknown.'}];
   return route.fulfill({json:draft});
  }
  if(path.endsWith('/confirm')){
   const body=route.request().postDataJSON();expect(body.expected_draft_version).toBe(3);
   current={selection_version:1,goal:{...body,_id:'000000000000000000000002',version:1,readiness:'pending',skills:[],interests:['Data'],preferences:[]},dependent_results_need_review:false};
   return route.fulfill({json:current});
  }
  return route.fulfill({status:404,json:{detail:'Not found'}});
 });
 await page.goto('/career-goal');await page.getByRole('button',{name:'Explore careers'}).click();
 await expect(page).toHaveURL(/\/career-goal\/chat$/);
 const composer=page.getByRole('textbox',{name:'Message Coachify'});
 await composer.fill('I am not sure yet.');await expect(page.getByRole('button',{name:'Send message'})).toBeDisabled();
 await page.getByRole('checkbox',{name:/Allow Coachify/}).check();await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('log')).toContainText('What kind of work would feel meaningful');
 await expect(page).toHaveURL(/\/career-goal\/chat\?exploration=/);
 await expect(page.getByRole('checkbox',{name:/Allow Coachify/})).toBeChecked();
 await expect(page.getByRole('button',{name:'Review this direction'})).toHaveCount(0);
 await composer.fill('I want to work with data. I studied computing, built SQL projects, enjoy analysis and prefer Singapore.');
 await composer.press('Enter');
 await expect(page.getByRole('heading',{name:'Data analyst',exact:true})).toBeVisible();
 await page.screenshot({path:test.info().outputPath('exploration-desktop.png'),fullPage:true});
 await page.getByRole('button',{name:'Review this direction'}).click();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(page.getByRole('heading',{name:'Review your career goal'})).toBeInViewport();
 await expect(composer).toBeInViewport();
 await page.screenshot({path:test.info().outputPath('exploration-mobile.png'),fullPage:true});
 await page.getByRole('button',{name:'Confirm and save goal'}).click();
 await expect(page.getByText(/Career goal saved/)).toBeVisible();
 await page.reload();
 await expect(page.getByRole('log')).toContainText('I am not sure yet.');
 await page.getByRole('button',{name:'Conversation details'}).click();
 await expect(page.getByText('Selected goal: Data analyst',{exact:true})).toBeVisible();
});

test('selected JD extracts skills on the shared page and reviews proposed additions',async({page})=>{
 await workspace(page);const calls:string[]=[];
 await page.route('**/api/v1/career/**',route=>{const path=new URL(route.request().url()).pathname;calls.push(path);
  if(path.endsWith('/jd/extract'))return route.fulfill({json:{extraction:{role:'Analyst',field:'Data',company:null,skills:[{name:'SQL',category:'Technical',priority:'required',origin:'employer',evidence:'SQL'}]},generation:{}}});
  return route.fulfill({json:{reply:'Python can be an additional learning goal; it is not stated in this JD.',proposed_skills:[{name:'SQL',category:'Technical',priority:'required',origin:'employer',evidence:'SQL'},{name:'Python',category:'Technical',priority:'suggested',origin:'generated_guidance',evidence:null}]}});
 });
 await page.goto('/career-goal');
 await page.getByRole('textbox',{name:'Job description',exact:true}).fill('Synthetic analyst requires SQL and research.');
 await page.getByRole('button',{name:'Extract career goal'}).click();
 await expect(page).toHaveURL(/\/career-goal\/chat\?source=jd$/);
 await expect(page.getByRole('heading',{name:'Skills to review'})).toBeVisible();
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('Add Python as a suggested learning goal.');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('heading',{name:'Proposed skill changes'})).toBeVisible();
 await expect(page.getByRole('region',{name:'Extracted career skills'})).not.toContainText('Python');
 await page.getByRole('button',{name:'Apply proposed changes'}).click();
 await expect(page.getByRole('region',{name:'Extracted career skills'})).toContainText('Python');
 await page.screenshot({path:test.info().outputPath('jd-review-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath('jd-review-mobile.png'),fullPage:true});
 await page.getByRole('button',{name:'View description'}).click();
 await page.getByText('View selected description',{exact:true}).click();
 await expect(page.getByText('Synthetic analyst requires SQL and research.',{exact:true})).toBeVisible();
 expect(await page.evaluate(()=>JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]))).not.toContain('requires SQL');
 await page.reload();await expect(page.getByRole('log')).toContainText('no longer available');
 expect(calls).toEqual(['/api/v1/career/jd/extract','/api/v1/career/jd/messages']);
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

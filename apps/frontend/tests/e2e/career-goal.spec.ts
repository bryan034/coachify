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
 await page.getByRole('textbox',{name:'Review and edit the preview'}).fill('Edited preview');
 await page.getByLabel('Job description URL',{exact:true}).fill('https://example.test/blocked');
 page.once('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'Import job page'}).click();
 await expect(page.getByRole('tabpanel').getByRole('alert')).toContainText('restricts automated access');
 await expect(page.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('Edited preview');
 await page.getByRole('tab',{name:'Upload document'}).click();
 await page.getByLabel('Job description document',{exact:true}).setInputFiles({name:'role.txt',mimeType:'text/plain',buffer:Buffer.from('Document analyst\n• Communication')});
 await page.getByRole('button',{name:'Read document'}).click();
 await expect(page.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('Document analyst\n• Communication');
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

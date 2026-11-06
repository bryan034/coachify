import {expect, test} from '@playwright/test';
import {clarificationState, emptyDeclarations, policy, savedCv} from '../fixtures/cv';

for (const viewport of [{width:1280,height:900},{width:1280,height:800},{width:390,height:844}]) {
 test(`CV chat keeps question actions in the transcript at ${viewport.width}x${viewport.height}`, async ({page}, testInfo) => {
  await page.setViewportSize(viewport);
  await page.addInitScript(() => {
   localStorage.setItem('elo.access-epoch','1');
   sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));
  });
  await page.route('**/api/v1/profile**', route => {
   const path=new URL(route.request().url()).pathname;
   if(path.endsWith('/skills-profile')) return route.fulfill({json:{version:0,status:'empty',saved_at:null,areas:{},entries:[]}});
   if(path.endsWith('/capabilities')) return route.fulfill({json:emptyDeclarations});
   if(path.endsWith('/auth-config')) return route.fulfill({json:{mode:'email',google_enabled:false}});
   if(path.endsWith('/auth/session')) return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
   return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false}});
  });
  const cv=savedCv('chat-layout');
  const question='Which parts of the dashboard did you build?';
  let turns=0;
  await page.route('**/api/v1/cv{,/**}', route => {
   const path=new URL(route.request().url()).pathname;
   if(path.includes('/conversations')) {
    if(path.endsWith('/messages')) turns++;
    return route.fulfill({json:{
    id:'layout-chat',cv_id:cv.id,purpose:'skills_profile',revision:1+turns*2,read_only:false,
    interview:{status:turns>=2?'reviewed_with_gaps':'reviewing',reviewed_items:Math.min(turns,2),total_items:2,estimates:[],topics:[{id:'dashboard',title:'Dashboard',status:turns>0?'reviewed':'current'},{id:'internship',title:'Internship',status:turns>=2?'reviewed_with_gaps':turns===1?'current':'pending'}]},
    previous_conversation_id:null,active_question:turns>=2?null:{id:'q1',item_id:cv.items[0].id,title:'Dashboard',question:turns===1?'What did you do in your internship?':question},context:null,
    messages:[{id:'m1',sequence:1,role:'assistant',text:turns>=2?'Your review is complete. Some details remain uncertain.':turns===1?'What did you do in your internship?':question,actions:[],created_at:'2026-10-28T09:00:00Z'},
     {id:'m2',sequence:2,role:'user',text:'I built the screens.',actions:[],created_at:'2026-10-28T09:01:00Z'}],
    next_before:null,limits:{max_message_chars:4000,max_messages:500},
   }});}
   if(path.endsWith('/policy')) return route.fulfill({json:policy});
   if(path==='/api/v1/cv') return route.fulfill({json:{cvs:[cv],selection:{cv_id:cv.id,version:1}}});
   if(path.endsWith('/clarifications')) return route.fulfill({json:clarificationState(cv)});
   return route.fulfill({json:cv});
  });
  await page.goto(`/cv?review=${cv.id}`);
  await expect(page.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
  await expect(page.getByText(question,{exact:true})).toHaveCount(1);
  await expect(page.locator('.cv-chat-current-topic')).toHaveCount(0);
  await expect(page.locator('.cv-chat-messages').getByRole('button',{name:'Skip this question'})).toBeInViewport();
  await expect(page.locator('.cv-chat-message-user .cv-chat-bubble')).toHaveCSS('background-color','rgb(52, 211, 153)');
  const input=await page.getByRole('textbox',{name:'Message elo'}).boundingBox();
  const history=await page.locator('.cv-chat-messages').boundingBox();
  expect(input!.y-(history!.y+history!.height)).toBeLessThan(24);
  expect(history!.height/viewport.height).toBeGreaterThanOrEqual(.7);
  await expect(page.getByRole('textbox',{name:'Message elo'})).toBeInViewport();
  const actions=await page.locator('.cv-chat-inline-actions').boundingBox();
  expect(input!.y-(actions!.y+actions!.height)).toBeLessThan(64);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.getByRole('progressbar',{name:'Review progress'})).toHaveAttribute('aria-valuemax','2');
  await expect(page.getByRole('button',{name:'Continue review'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Review profile summary'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Review profile',exact:true})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath('chat-layout.png'),fullPage:true});
  await page.getByRole('textbox',{name:'Message elo'}).fill('I built the reporting screens.');
  await page.getByRole('button',{name:'Send message'}).click();
  await expect(page.getByText('What did you do in your internship?',{exact:true})).toBeVisible();
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow','1');
  await page.getByRole('textbox',{name:'Message elo'}).fill('I helped with stakeholder interviews.');
  await page.getByRole('button',{name:'Send message'}).click();
  await expect(page.getByRole('button',{name:'Review profile',exact:true})).toBeEnabled();
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow','2');
  await page.reload();
  await expect(page.getByRole('button',{name:'Review profile',exact:true})).toBeEnabled();
  expect(turns).toBe(2);
  await page.screenshot({path:testInfo.outputPath('review-complete.png'),fullPage:true});
  await page.getByRole('button',{name:'Review profile',exact:true}).click();
  await expect(page.getByRole('region',{name:'Skills profile summary'})).toBeVisible();
 });
}

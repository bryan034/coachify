import {test,expect} from '@playwright/test';
import {careerFixture} from './career-fixture';

for(const [name,path] of [['career chat','/career-goal/chat'],['job description chat','/career-goal/chat?source=jd'],['career discovery','/career-goal/discovery']] as const){
 for(const viewport of [{width:1440,height:900},{width:1280,height:720},{width:820,height:1100},{width:390,height:844}]){
  test(`${name} gives the conversation at least 70% of a ${viewport.width}x${viewport.height} screen`,async({page})=>{
   await page.setViewportSize(viewport);
   await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
   await page.route('**/api/v1/profile**',route=>{
    const url=route.request().url(),path=new URL(url).pathname;
    if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(url,{mode:'email',google_enabled:false})});
    if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(url,{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
    return route.fulfill({json:careerFixture(url,{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false})});
   });
   const draft={_id:'000000000000000000000001',version:1,answers:{},turns:[],cv:{mode:'none',filename:null,cv_id:null},interests:[],preferences:[],suggestions:[],next_question:'aspirations',question_text:'What would you like to achieve?',context_complete:false};
   await page.route('**/api/v1/career/**',route=>{
    const url=route.request().url(),path=new URL(url).pathname;
    if(path.endsWith('/workspace'))return route.fulfill({json:careerFixture(url,{phase:'empty',review:null,exploration_id:null})});
    if(path.endsWith('/context'))return route.fulfill({json:careerFixture(url,{cvs:[],cv_service_available:true,ai_available:true})});
    if(path.endsWith('/goals/current'))return route.fulfill({json:careerFixture(url,{selection_version:0,goal:null})});
    if(path.endsWith('/explorations'))return route.fulfill({json:careerFixture(url,draft)});
    return route.fulfill({status:503,json:{detail:'Synthetic outage.'}});
   });
   await page.goto(path);
   const log=page.getByRole('log');
   await expect(log).toBeVisible();
   const box=(await log.boundingBox())!;
   expect(box.height/viewport.height).toBeGreaterThanOrEqual(.7);
   await page.getByRole('textbox',{name:'Message elo'}).scrollIntoViewIfNeeded();
   await expect(page.getByRole('textbox',{name:'Message elo'})).toBeInViewport();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   const scroll=await page.evaluate(()=>document.documentElement.scrollHeight-innerHeight);
   if(viewport.height>=844&&!(name==='career chat'&&viewport.width<=390))expect(scroll).toBeLessThanOrEqual(0);
   await page.screenshot({path:test.info().outputPath('chat.png')});
  });
 }
}

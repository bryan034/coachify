import {test,expect} from '@playwright/test';
test('career discovery requires scope approval and saves reviewed skills through the shared goal API',async({page},testInfo)=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false}});
 });
 const scope={field:'Software Engineering',area:'Software Engineering',specificity:'field',career_stage:'entry_level',location:'Singapore'};
 const content={role:'Software Engineering',field:'Software Engineering',company:null,job_url:null,location:'Singapore',seniority_level:'entry_level',summary:'Requirements sampled from ten relevant employer job listings.',responsibilities:['Build reliable APIs'],skills:[{item_id:'sql',name:'SQL',category:'technical',origin:'market_research',priority:'required',evidence:'SQL required.'},{item_id:'python',name:'Python',category:'technical',origin:'market_research',priority:'preferred',evidence:'Python preferred.'}],non_skill_requirements:[]};
 const decision={scope,reply:'Software Engineering can remain your broader career target. Confirm the area to research entry-level jobs in Singapore.',question:null,recommendations:[],action:'CONFIRM_AREA'};
 const session={id:'000000000000000000000001',version:1,status:'conversation',stage:null,scope,decision,related_roles:['Software Engineer','Backend Engineer'],sources:[{source_id:'s1',title:'Example employer listing',url:'https://example.test/jobs/1',published_date:null}],stats:[{name:'SQL',requirement_type:'core',mention_count:8,sample_size:10},{name:'Python',requirement_type:'optional',mention_count:4,sample_size:10}],warnings:['Requirements describe this researched sample, not the whole market.'],listings_analysed:10,employers_analysed:5,coverage:'good',error_code:null,limit_scope:null,provider:null,retry_after:null,review:{review_id:'000000000000000000000002',version:1,extraction:content,baseline:content}};
 let started=false,researches=0,confirmed=false;
 await page.route('**/api/v1/career/**',route=>{const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/discoveries/current'))return route.fulfill({json:{available:true,session:started?session:null}});
  if(path.endsWith('/discoveries')){started=true;return route.fulfill({json:{available:true,session:{...session,review:null,decision:null}}});}
  if(path.endsWith('/messages'))return route.fulfill({json:{available:true,session:{...session,review:null}}});
  if(path.endsWith('/research')){researches++;expect(route.request().postDataJSON()).toMatchObject({scope,confirmed:true});return route.fulfill({status:202,json:{available:true,session:{...session,status:'review'}}});}
  if(path.endsWith('/review')){session.review.extraction=route.request().postDataJSON().content;session.review.version++;return route.fulfill({json:session.review});}
  if(path.endsWith('/goals/current'))return route.fulfill({json:{selection_version:0,goal:null}});
  if(path.endsWith('/goals/confirm')){confirmed=true;expect(route.request().postDataJSON()).toMatchObject({review_id:session.review.review_id,target_type:'career_exploration',company:null,job_url:null});expect(session.review.extraction.skills.map(v=>v.name)).toEqual(['SQL']);return route.fulfill({json:{selection_version:1,goal:null}});}
  return route.fulfill({json:{phase:'empty',review:null,current:{goal:null},exploration_id:null}});
 });
 await page.goto('/career-goal/discovery');
 await page.getByRole('checkbox',{name:/Allow Coachify/}).check();
 await page.getByRole('textbox',{name:'Tell Coachify your career direction'}).fill('Software engineering. Keep it broad, entry-level roles in Singapore.');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('heading',{name:'Your proposed scope'})).toBeVisible();expect(researches).toBe(0);expect(confirmed).toBe(false);
 await page.getByRole('button',{name:'Confirm area and research jobs'}).click();
 await expect(page.getByRole('heading',{name:'Review your career target'})).toBeVisible();
 for(const name of ['Core skills','Specialisation-specific skills','Optional skills'])await expect(page.getByRole('heading',{name})).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('heading',{name:'Review your career target'}).scrollIntoViewIfNeeded();
 await page.screenshot({path:testInfo.outputPath('discovery-mobile.png'),fullPage:true});
 await page.getByRole('button',{name:'Remove Python'}).click();
 await page.getByRole('checkbox',{name:/I have reviewed this target/}).check();
 await page.getByRole('button',{name:'Confirm and save goal'}).click();
 await expect(page).toHaveURL(/\/career-goal$/);expect(confirmed).toBe(true);expect(researches).toBe(1);
});

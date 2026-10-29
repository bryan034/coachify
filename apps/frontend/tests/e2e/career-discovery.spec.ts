import {careerFixture} from './career-fixture';
import {test,expect} from '@playwright/test';
test('career discovery opens fresh without inference, researches sent messages and saves only after confirmation',async({page},testInfo)=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false})});
 });
 const scope={field:'Software Engineering',area:'Software Engineering',specificity:'field',career_stage:'entry_level',location:'Singapore'};
 const content={role:'Software Engineering',field:'Software Engineering',company:null,job_url:null,location:'Singapore',seniority_level:'entry_level',summary:'Requirements sampled from ten relevant employer job listings.',responsibilities:['Build reliable APIs'],skills:[{item_id:'sql',name:'SQL',category:'technical',origin:'generated_guidance',priority:'suggested',evidence:null,context:'High learning priority · Useful for querying application data.',source_urls:['https://example.test/jobs/1']},{item_id:'python',name:'Python',category:'technical',origin:'generated_guidance',priority:'suggested',evidence:null,context:'Low learning priority · One optional tool for data processing.',source_urls:['https://example.test/jobs/1']}],non_skill_requirements:[]};
 const decision={scope,reply:'Software Engineering can remain your broader career target. I am researching entry-level jobs in Singapore.',question:null,recommendations:[],action:'START_RESEARCH'};
 const session={id:'000000000000000000000001',version:1,status:'conversation',stage:null,scope,decision,summary:{responsibility_refs:[0],skills:[{name:'SQL',requirement_type:'core',learning_priority:'high',relevance:'Useful for querying application data.',skill_refs:[0]},{name:'Python',requirement_type:'optional',learning_priority:'low',relevance:'One optional tool for data processing.',skill_refs:[1]}],specialisations:[],question:null},related_roles:['Software Engineer','Backend Engineer'],sources:[{source_id:'s1',title:'Example employer listing',url:'https://example.test/jobs/1',published_date:null}],stats:[{name:'SQL',requirement_type:'core',mention_count:8,sample_size:10},{name:'Python',requirement_type:'optional',mention_count:4,sample_size:10}],warnings:['Requirements describe this researched sample, not the whole market.'],listings_analysed:10,employers_analysed:5,coverage:'good',error_code:null,limit_scope:null,provider:null,retry_after:null,review:{review_id:'000000000000000000000002',version:1,extraction:content,}};
 const introduction="Hi, I\u2019m Coachify\u2019s Career Discovery assistant. This chat helps you choose a career direction and build a recommended skill set backed by research.\n\nTo start, tell me a field or role you\u2019re interested in, or describe the kind of work you enjoy. You can keep it broad\u2014no CV, specific vacancy or specialisation is required.\n\nI will ask questions to understand your interests and personalise your goal for you, then research representative roles once we have enough context. You can ask questions or refine the results, and you\u2019ll review and confirm before saving your goal.";
 const bundle="1. Is there a specific role or kind of work you want to explore within this field? You can keep it broad.\n\n2. What interests you about this field? You can say unsure.\n\n3. What other interests do you have, related or unrelated to this field? You can say unsure.\n\n4. What activities do you strongly want to avoid? You can say unsure.\n\n5. What career stage are you looking for: internship, starting out, or experienced? You can say unsure.\n\n6. What work preferences or constraints matter to you? You can say unsure.";
 const profileMessage="Software engineering, keep it broad. I enjoy building applications. Other interests: music. Avoid sales. Entry-level. No work constraints. Singapore.";
 let started=false,researches=0,confirmed=false,starts=0,messagesSent=0;
 const messages:{role:string;content:string}[]=[];
 await page.route('**/api/v1/career/**',route=>{const url=new URL(route.request().url()),path=url.pathname;
  if(path.endsWith('/discoveries/current')&&url.searchParams.get('fresh')==='true')return route.fulfill({json:{available:true,session:null,introduction}});
  if(path.endsWith('/discoveries/current'))return route.fulfill({json:careerFixture(route.request().url(),{available:true,session:started?{...session,status:'review',messages}:null})});
  if(path.endsWith('/discoveries')){started=true;starts++;session.version=1;session.id=String(starts).padStart(24,'0');messages.splice(0,messages.length);return route.fulfill({json:careerFixture(route.request().url(),{available:true,session:{...session,version:1,status:'conversation',scope:null,review:null,decision:null,messages}})});}
  if(path.endsWith('/messages')){
   messagesSent++;expect(route.request().postDataJSON().expected_version).toBe(session.version);session.version++;const message=route.request().postDataJSON().message;messages.push({role:'user',content:message});
   if(message==='Software engineering'){
    messages.push({role:'assistant',content:bundle});
    return route.fulfill({json:careerFixture(route.request().url(),{available:true,session:{...session,status:'conversation',stage:null,review:null,decision:{...decision,action:'ASK_CLARIFICATION'},messages}})});
   }
   messages.push({role:'assistant',content:decision.reply});
   return route.fulfill({json:careerFixture(route.request().url(),{available:true,session:{...session,status:'researching',stage:'search_job_listings',review:null,messages}})});
  }
  if(path.endsWith('/discoveries/'+session.id)){
   messages.push({role:'assistant',content:'Recommended skills: SQL for data queries. [Source](https://example.test/jobs/1). Ask a question or refine this direction.'});
   return route.fulfill({json:careerFixture(route.request().url(),{available:true,session:{...session,status:'review',messages}})});
  }
  if(path.endsWith('/research')){researches++;expect(route.request().postDataJSON()).toMatchObject({scope,confirmed:true});return route.fulfill({status:202,json:careerFixture(route.request().url(),{available:true,session:{...session,status:'review'}})});}
  if(path.endsWith('/review')){session.review.extraction=route.request().postDataJSON().content;session.review.version++;return route.fulfill({json:careerFixture(route.request().url(),session.review)});}
  if(path.endsWith('/goals/current'))return route.fulfill({json:careerFixture(route.request().url(),{selection_version:0,goal:null})});
  if(path.endsWith('/goals/confirm')){confirmed=true;expect(route.request().postDataJSON()).toMatchObject({review_id:session.review.review_id,target_type:'career_exploration',company:null,job_url:null});expect(session.review.extraction.skills.map(v=>v.name)).toEqual(['SQL']);return route.fulfill({json:careerFixture(route.request().url(),{selection_version:1,goal:null})});}
  return route.fulfill({json:careerFixture(route.request().url(),{phase:'empty',review:null,current:{goal:null},exploration_id:null})});
 });
 await page.goto('/career-goal/discovery');
 await expect(page.getByRole('log')).toContainText('This chat helps you choose a career direction');
 await expect(page.getByRole('log').locator('.agent-message')).toHaveCount(1);
 expect(starts).toBe(0);expect(messagesSent).toBe(0);expect(researches).toBe(0);
 await page.getByRole('checkbox',{name:/Allow Coachify/}).check();
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('Software engineering');
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('log').getByRole('listitem')).toHaveCount(6);
 await expect(page.getByRole('log')).toContainText('What other interests do you have');
 await expect(page.getByRole('log')).not.toContainText('Let’s clarify the remaining context');
 await expect(page.getByRole('log')).not.toContainText('one focused question');
 await page.setViewportSize({width:390,height:1100});
 await page.getByRole('log').locator('.agent-message.assistant').last().evaluate(el=>el.scrollIntoView({block:'start'}));
 await page.screenshot({path:testInfo.outputPath('discovery-clarification-bundle-mobile.png'),fullPage:true});
 expect(messagesSent).toBe(1);expect(researches).toBe(0);
 await page.getByRole('textbox',{name:'Message Coachify'}).fill(profileMessage);
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('textbox',{name:'Message Coachify'})).toHaveValue('');
 await expect(page.getByText('Finding relevant job listings')).toBeVisible();
 await expect(page.getByRole('textbox',{name:'Message Coachify'})).toBeEditable();
 expect(researches).toBe(0);expect(confirmed).toBe(false);
 await expect(page.getByRole('button',{name:'Confirm area and research jobs'})).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'Review your career target'})).toBeVisible();
 for(const name of ['Core skills','Specialisation-specific skills','Optional skills'])await expect(page.getByRole('heading',{name})).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(page.getByRole('log')).toContainText('Recommended skills: SQL');
 await expect(page.getByRole('log').getByRole('link')).toHaveAttribute('href','https://example.test/jobs/1');
 await page.getByRole('textbox',{name:'Message Coachify'}).fill('A new unsent question');
 await page.screenshot({path:testInfo.outputPath('discovery-chat-mobile.png'),fullPage:true});
 await page.getByRole('button',{name:'New chat'}).click();
 await expect(page.getByRole('log')).toContainText('This chat helps you choose a career direction');
 await expect(page.getByRole('log').locator('.agent-message')).toHaveCount(1);
 await expect(page.getByRole('log')).not.toContainText('Recommended skills: SQL');
 await expect(page.getByRole('textbox',{name:'Message Coachify'})).toHaveValue('');
 await expect(page.getByRole('heading',{name:'Review your career target'})).toHaveCount(0);
 expect(starts).toBe(1);expect(messagesSent).toBe(2);
 await page.screenshot({path:testInfo.outputPath('discovery-fresh-mobile.png'),fullPage:true});
 await page.reload();
 await expect(page.getByRole('log').locator('.agent-message')).toHaveCount(1);
 await expect(page.getByRole('log')).not.toContainText('Software engineering. Keep it broad');
 expect(starts).toBe(1);expect(messagesSent).toBe(2);
 await page.getByRole('checkbox',{name:/Allow Coachify/}).check();
 await page.getByRole('textbox',{name:'Message Coachify'}).fill(profileMessage);
 await page.getByRole('button',{name:'Send message'}).click();
 await expect(page.getByRole('heading',{name:'Review your career target'})).toBeVisible();
 expect(starts).toBe(2);expect(messagesSent).toBe(3);
 await expect(page.getByRole('textbox',{name:'Career overview'})).toHaveCSS('font-family',await page.getByRole('textbox',{name:'Career title'}).evaluate(input=>getComputedStyle(input).fontFamily));
 await page.getByRole('heading',{name:'Review your career target'}).scrollIntoViewIfNeeded();
 await page.screenshot({path:testInfo.outputPath('discovery-mobile.png'),fullPage:true});
 await page.getByRole('button',{name:'Remove Python'}).click();
 await page.getByRole('checkbox',{name:/I have reviewed this target/}).check();
 await page.getByRole('button',{name:'Confirm and save goal'}).click();
 await expect(page).toHaveURL(/\/career-goal$/);expect(confirmed).toBe(true);expect(researches).toBe(0);
});

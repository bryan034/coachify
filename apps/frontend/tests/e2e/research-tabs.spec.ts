import {expect,type Page} from '@playwright/test';
import {careerFixture,test} from './career-fixture';
import {interviewBrief,roleBrief} from '../fixtures/research-brief';

const goal={_id:'0'.repeat(24),version:1,target_type:'specific_job',role:'GenAI Delivery Intern',field:'Health technology',company:'Example Health',location:'Singapore',employment_type:'internship',seniority_level:null,job_url:null,skills:[],non_skill_requirements:[],responsibilities:[],summary:'Coordinate GenAI projects with delivery teams.'};
const base={status:'completed',findings:[],missing_fields:[],warnings:[],error_code:null,researched_at:'2026-11-21T08:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};

async function mockCareer(page:Page,refreshed:{category?:string|null}){
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{}})});
 });
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/v2/role-research'))return route.fulfill({json:{status:'ready',brief:roleBrief}});
  if(path.endsWith('/v2/interview-research'))return route.fulfill({json:{status:'ready',brief:interviewBrief}});
  if(path.endsWith('/context/assessment'))return route.fulfill({json:careerFixture(route.request().url(),{status:'evaluated',cv_uploaded:true,skills_evaluated:true})});
  if(path.endsWith('/opportunity-research/progress'))return route.fulfill({json:{status:'completed',finished:true,result_version:'v1',categories:{}}});
  if(path.endsWith('/opportunity-research')){
   if(route.request().method()==='POST')refreshed.category=route.request().postDataJSON().category;
   return route.fulfill({json:{available:true,status:'completed',finished:true,job_id:'job',career_target_id:goal._id,research_id:'research',sources:[],error_code:null,updated_at:'2026-11-21T08:00:00Z',
    categories:{interview_intelligence:base,internship_insights:base,career_progression:base,conversion_outcomes:base,company_intelligence:base}}});
  }
  return route.fulfill({json:careerFixture(route.request().url(),{phase:'ready',review:{review_id:'1'.repeat(24),version:1,target_type:'specific_job',extraction:goal,requirements_need_review:false},current:{selection_version:1,goal},research:null,coverage:[],error:null,retry_after:null})});
 });
}

async function expandAll(page:Page){
 const brief=page.locator('.brief');
 for(;;){
  const closed=brief.locator('button.brief-toggle[aria-expanded="false"]');
  if(!await closed.count())break;
  await closed.first().click();
 }
}

async function noHorizontalScroll(page:Page){
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
}

async function citationsResolve(page:Page,prefix:string,titles:string[]){
 const chips=page.locator('.brief a.brief-cite:visible');
 const count=await chips.count();
 expect(count).toBeGreaterThan(0);
 for(let i=0;i<count;i++){
  const chip=chips.nth(i);
  const n=Number(await chip.textContent());
  await expect(chip).toHaveAttribute('href',`#${prefix}-src-${n}`);
  await expect(page.locator(`#${prefix}-src-${n}`)).toContainText(titles[n-1]);
 }
}

async function capture(page:Page,name:string){
 for(const width of [1280,390]){
  await page.setViewportSize({width,height:900});
  await noHorizontalScroll(page);
  await page.screenshot({path:test.info().outputPath(`${name}-${width}.png`),fullPage:true,animations:'disabled'});
 }
 await page.setViewportSize({width:1280,height:900});
}

test('About the role renders the brief, its toggles and citations at desktop and phone widths',async({page})=>{
 const refreshed:{category?:string|null}={};
 await mockCareer(page,refreshed);
 await page.setViewportSize({width:1280,height:900});
 await page.goto('/career-goal/role');
 await expect(page.getByText(roleBrief.summary)).toBeVisible();
 await expect(page.getByRole('note')).toContainText('Researched 21 Nov 2026 from 7 public sources.');
 await capture(page,'about-role-collapsed');

 const pay=page.getByRole('region',{name:'Pay and what comes after'});
 await pay.getByRole('link',{name:'Source 7: Business Analyst salary estimate'}).click();
 await expect(page.locator('#role-src-7')).toHaveClass(/is-flash/);
 await expect(page.locator('#role-src-7')).toBeInViewport();
 await expect(page.getByRole('button',{name:'Show fewer sources'})).toHaveAttribute('aria-expanded','true');
 await page.getByRole('button',{name:'Show fewer sources'}).click();
 await expect(page.locator('#role-src-6')).toHaveCount(0);

 await expandAll(page);
 await expect(page.getByRole('region',{name:'What you would do'}).getByRole('listitem')).toHaveCount(6);
 await expect(page.getByText(/limited time to mentor/)).toBeVisible();
 await citationsResolve(page,'role',roleBrief.sources.map(source=>source.title));
 await capture(page,'about-role-expanded');

 await page.getByRole('button',{name:'Refresh research'}).click();
 await expect.poll(()=>refreshed.category).toBe(null);
});

test('Interview preparation renders the process, difficulty, questions and reports at desktop and phone widths',async({page})=>{
 const refreshed:{category?:string|null}={};
 await mockCareer(page,refreshed);
 await page.setViewportSize({width:1280,height:900});
 await page.goto('/career-goal/interview');
 await expect(page.getByText(interviewBrief.summary)).toBeVisible();
 await expect(page.getByRole('img',{name:'Difficulty: Average, estimated'})).toBeVisible();
 const practise=page.getByRole('region',{name:'Practise these'});
 await expect(practise.getByRole('button',{expanded:true})).toHaveCount(1);
 await capture(page,'interview-collapsed');

 await practise.getByRole('button',{name:/planning skills/}).click();
 await expect(practise.getByText(interviewBrief.questions[1].prep)).toBeVisible();
 await expect(practise.getByText(interviewBrief.questions[0].prep)).toBeHidden();
 await page.keyboard.press('Enter');
 await expect(practise.getByRole('button',{expanded:true})).toHaveCount(0);
 await practise.getByRole('button',{name:/planning skills/}).click();
 await expandAll(page);
 await expect(page.getByText(/asked about themselves and past projects/)).toBeVisible();
 await citationsResolve(page,'interview',interviewBrief.sources.map(source=>source.title));
 await capture(page,'interview-expanded');

 await page.getByRole('button',{name:'Refresh research'}).click();
 await expect.poll(()=>refreshed.category).toBe('interview_intelligence');
});

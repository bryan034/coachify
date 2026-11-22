import {expect,type Page} from '@playwright/test';
import {careerFixture,test} from './career-fixture';
import {roleGoal,roleResearch,roleResearchSources} from '../fixtures/role-research';
import {interviewResearch,interviewResearchSources} from '../fixtures/interview-research';

const goal={_id:'0'.repeat(24),version:1,target_type:'specific_job',role:'GenAI Delivery Intern',field:'Health technology',company:'Example Health',location:'Singapore',employment_type:'internship',seniority_level:null,job_url:null,skills:[],non_skill_requirements:roleGoal.requirements.map((description,index)=>({requirement_id:`r${index}`,category:'qualification',description,priority:'required',evidence:description,group_id:null,group_operator:'all',origin:'employer'})),responsibilities:roleGoal.duties,summary:'Coordinate GenAI projects with delivery teams.'};

async function mockCareer(page:Page,requests:{researchWrites?:number;summaryCalls?:number}){
 const interview=structuredClone(interviewResearch);
 for(const finding of interview.findings)if(finding.round_number===2)finding.round_name='Technical interview with the hiring manager';
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:careerFixture(route.request().url(),{mode:'email',google_enabled:false})});
  if(path.endsWith('/auth/session'))return route.fulfill({json:careerFixture(route.request().url(),{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'})});
  return route.fulfill({json:careerFixture(route.request().url(),{version:1,onboarding_complete:true,occupational_status:'employed',education:{}})});
 });
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.includes('/v2/')||path.endsWith('/interview-prep')||path.endsWith('/role-summary')){requests.summaryCalls=(requests.summaryCalls||0)+1;return route.fulfill({status:503,json:{detail:'No research summary should be requested.'}});}
  if(path.endsWith('/context/assessment'))return route.fulfill({json:careerFixture(route.request().url(),{status:'evaluated',cv_uploaded:true,skills_evaluated:true})});
  if(path.endsWith('/opportunity-research/progress'))return route.fulfill({json:{status:'completed',finished:true,result_version:'v1',categories:{}}});
  if(path.endsWith('/opportunity-research')){
   if(route.request().method()==='POST')requests.researchWrites=(requests.researchWrites||0)+1;
   return route.fulfill({json:{available:true,status:'completed',finished:true,job_id:'job',career_target_id:goal._id,research_id:'research',sources:[...interviewResearchSources,...roleResearchSources],error_code:null,updated_at:'2026-11-21T08:00:00Z',
    round_previews:{'2':{expectation_id:interview.findings[2].finding_id,question_id:interview.findings[4].finding_id,preparation_id:interview.findings[5].finding_id}},round_titles:{'1':'HR call','2':'Technical interview','3':'Final interview'},categories:{interview_intelligence:interview,...roleResearch}}});
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

test('About the role displays saved findings, goal details and citations without a summary on desktop and phone',async({page})=>{
 const requests:{researchWrites?:number;summaryCalls?:number}={};
 await mockCareer(page,requests);
 await page.setViewportSize({width:1280,height:900});
 await page.goto('/career-goal/role');
 await expect(page.getByRole('region',{name:'What it is like'})).toContainText(roleResearch.internship_insights!.findings[2].value);
 await expect(page.getByRole('region',{name:'Who can apply'})).toContainText(roleGoal.requirements[0]);
 await expect(page.getByRole('region',{name:'What you would do'})).toContainText(roleGoal.duties[0]);
 await expect(page.getByRole('region',{name:'Pay and what comes after'})).toContainText('S$1,799/mo');
 await expect(page.getByRole('note')).toContainText('Researched 21 Nov 2026 from 7 public sources.');
 await capture(page,'about-role-findings');

 const pay=page.getByRole('region',{name:'Pay and what comes after'});
 await pay.getByRole('link',{name:'Source 7: Role report 7'}).first().click();
 await expect(page.locator('#role-src-7')).toHaveClass(/is-flash/);
 await expect(page.locator('#role-src-7')).toBeInViewport();
 await expect(page.locator('#role-src-7 a')).toBeFocused();
 const toggle=page.getByRole('button',{name:'Show fewer sources'});
 await toggle.focus();await page.keyboard.press('Enter');
 await expect(page.locator('#role-src-6')).toHaveCount(0);

 await expandAll(page);
 await expect(page.getByRole('region',{name:'What you would do'}).getByRole('listitem')).toHaveCount(6);
 await expect(page.getByText(/limited time to mentor/)).toBeVisible();
 await citationsResolve(page,'role',roleResearchSources.map(source=>source.title!));
 await capture(page,'about-role-expanded');

 await expect(page.getByRole('button',{name:/Refresh research|Research opportunity/})).toHaveCount(0);
 await page.reload();
 await expect(page.getByRole('region',{name:'What it is like'})).toContainText(roleResearch.internship_insights!.findings[2].value);
 expect(requests.summaryCalls||0).toBe(0);
 expect(requests.researchWrites||0).toBe(0);
});

test('Interview preparation displays saved findings and citations without a summary request on desktop and phone',async({page})=>{
 const requests:{researchWrites?:number;summaryCalls?:number}={};
 await mockCareer(page,requests);
 await page.setViewportSize({width:1280,height:900});
 await page.goto('/career-goal/interview');
 await expect(page.getByRole('region',{name:'Round 2: Technical interview'})).toContainText(interviewResearch.findings[4].value);
 await expect(page.getByRole('region',{name:'Difficulty'})).toContainText('Moderate');
 await expect(page.getByRole('region',{name:'Interview rounds',exact:true}).getByRole('heading',{level:4})).toHaveText(['HR call','Technical interview','Final interview']);
 await expect(page.getByRole('region',{name:'Round 2: Technical interview'})).toContainText('SQL joins');
 await expect(page.getByRole('region',{name:'Round 1: HR call'})).toContainText(interviewResearch.findings[8].value);
 await expect(page.getByRole('region',{name:'Round 3: Final interview'})).toContainText('Preparation guidance was not found for this round.');
 await expect(page.getByRole('region',{name:'What candidates reported'})).toContainText(interviewResearch.findings[6].value);
 await expect(page.getByRole('note')).toContainText('Researched 21 Nov 2026 from 7 public sources.');
 await expect(page.getByRole('heading',{name:'3 reported interview rounds'})).toBeVisible();
 const overview=page.getByRole('region',{name:'3 reported interview rounds'});
 await expect(overview.getByRole('heading',{level:4})).toHaveText(['1HR call','2Technical interview','3Final interview']);
 await expect(overview.getByRole('listitem').nth(0)).toContainText(interviewResearch.findings[7].value);
 await expect(overview.getByRole('listitem').nth(1)).toContainText(interviewResearch.findings[2].value);
 await expect(overview.getByRole('listitem').nth(2)).toContainText(interviewResearch.findings[9].value);
 await expect(page.locator('#interview-preparation h3').first()).toHaveText('3 reported interview rounds');
 const cardLayout=await page.locator('.brief-rounds > .brief-round').evaluateAll(cards=>cards.map(card=>({
  top:card.getBoundingClientRect().top,bottom:card.getBoundingClientRect().bottom,padding:parseFloat(getComputedStyle(card.querySelector('.brief-round-heading')!).paddingTop),
 })));
 expect(cardLayout).toHaveLength(3);
 for(let i=0;i<cardLayout.length;i++){
  expect(cardLayout[i].padding).toBeGreaterThanOrEqual(20);
  if(i>0)expect(cardLayout[i].top-cardLayout[i-1].bottom).toBeGreaterThanOrEqual(16);
 }
 const technical=page.getByRole('region',{name:'Round 2: Technical interview'});
 const details=technical.locator('details');
 await expect(details).not.toHaveAttribute('open','');
 await technical.getByText('More about this round').focus();
 await page.keyboard.press('Enter');
 await expect(details).toHaveAttribute('open','');
 await expect(details.getByText('An online call with the hiring manager.')).toBeVisible();
 await expect(details.getByText('SQL joins')).toBeVisible();
 await capture(page,'interview-findings');
 await technical.getByText('More about this round').click();
 await expect(details).not.toHaveAttribute('open','');

 await page.getByRole('region',{name:'What candidates reported'}).getByRole('link',{name:'Source 7: Interview report 7'}).click();
 await expect(page.locator('#interview-src-7')).toHaveClass(/is-flash/);
 await expect(page.locator('#interview-src-7 a')).toBeFocused();
 const toggle=page.getByRole('button',{name:'Show fewer sources'});
 await toggle.focus();await page.keyboard.press('Enter');
 await expect(page.locator('#interview-src-7')).toHaveCount(0);
 await page.getByRole('button',{name:'Show all 7 sources'}).click();
 await citationsResolve(page,'interview',[0,1,3,2,4,5,6].map(index=>interviewResearchSources[index].title!));
 await capture(page,'interview-sources-expanded');

 await expect(page.getByRole('button',{name:/Refresh research|Research opportunity/})).toHaveCount(0);
 await page.reload();
 await expect(page.getByRole('region',{name:'Round 2: Technical interview'})).toContainText(interviewResearch.findings[4].value);
 expect(requests.summaryCalls||0).toBe(0);
 expect(requests.researchWrites||0).toBe(0);
});

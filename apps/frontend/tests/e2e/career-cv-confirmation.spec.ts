import {test,expect} from '@playwright/test';

test('canonical goal confirmation is explicit, survives reload and must follow the current revision',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('coachify.access-epoch','1');sessionStorage.setItem('coachify.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-owner',name:'Synthetic reviewer',email_verified:true,provider:'email'}});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{}}});
 });
 const id='111111111111111111111111';let version=1,selection=1,confirmed=false,writes=0;
 const goal=()=>({_id:id,version,target_type:'specific_job',role:'Synthetic analyst',field:'Analytics',company:null,location:null,seniority_level:null,job_url:null,skills:[{name:'Python',category:'Technical',priority:'required',origin:'employer',evidence:'Python is required.'}],non_skill_requirements:[],responsibilities:[],interests:[],preferences:[],readiness:'ready',exploration_draft_id:null,exploration_draft_version:null});
 const status=()=>({goal_id:id,goal_version:version,selection_version:selection,confirmed,reason:null,context:confirmed?{id,version,selection_version:selection,confirmed:true}:null});
 await page.route('**/api/v1/career/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/cv-confirmation')){
   if(route.request().method()==='POST'){const body=route.request().postDataJSON();expect(body).toMatchObject({expected_goal_id:id,expected_goal_version:version,expected_selection_version:selection,mutation_id:expect.any(String)});confirmed=true;writes++;}
   return route.fulfill({json:status()});
  }
  if(path.endsWith('/context/assessment'))return route.fulfill({json:{status:'no_cv',cv_uploaded:false,skills_evaluated:false}});
  if(path.includes('/opportunity-research'))return route.fulfill({json:{available:false,availability_issues:['research_disabled'],status:'pending',categories:{},error_code:null,retry_after:null}});
  return route.fulfill({json:{session_id:null,revision:version,kind:'jd',phase:'ready',current:{goal:goal(),selection_version:selection,dependent_results_need_review:false},research_id:null,coverage:[],error:null,retry_after:null}});
 });
 await page.goto('/career-goal');const panel=page.getByRole('region',{name:'Goal confirmation for CV review'});
 await expect(panel.getByRole('button',{name:'Confirm this goal for CV review'})).toBeEnabled();expect(writes).toBe(0);await expect(page.getByText('Saved automatically',{exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'Confirm this goal for CV review'}).click();await expect(panel.getByRole('link',{name:'Review CV clarifications'})).toHaveAttribute('href','/cv');expect(writes).toBe(1);
 await page.reload();await expect(panel.getByRole('heading',{name:'Confirmed for CV review'})).toBeVisible();expect(writes).toBe(1);
 version=2;selection=2;confirmed=false;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await expect(panel.getByRole('button',{name:'Reload saved goal'})).toBeVisible();await expect(panel.getByRole('button',{name:'Confirm this goal for CV review'})).toBeDisabled();
 await panel.getByRole('button',{name:'Reload saved goal'}).click();await expect(panel.getByRole('button',{name:'Confirm this goal for CV review'})).toBeEnabled();await panel.getByRole('button',{name:'Confirm this goal for CV review'}).click();
 await expect(panel.getByRole('heading',{name:'Confirmed for CV review'})).toBeVisible();expect(writes).toBe(2);
});

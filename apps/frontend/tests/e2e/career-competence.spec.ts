import {test,expect} from '@playwright/test';
import {careerFixture} from './career-fixture';

test('role-relative skill progress stays readable on desktop and mobile',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  const value=path.endsWith('/auth-config')?{mode:'email',google_enabled:false}:path.endsWith('/auth/session')?{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}:{version:1,onboarding_complete:true,occupational_status:'employed',education:{}};
  return route.fulfill({json:careerFixture(route.request().url(),value)});
 });
 const goal={_id:'111111111111111111111111',version:1,role:'Software Engineer',field:'Software',target_type:'specific_job',skills:[{item_id:'python',name:'Python',category:'Technical coding',priority:'required',origin:'employer',evidence:'Familiar with Python',competence_target:{level:8,basis:'job_description',explanation:'Familiarity requires role-ready application at level 8.',source_urls:[]}}]};
 await page.route('**/api/v1/career/**',route=>{
  if(new URL(route.request().url()).pathname.endsWith('/cv-confirmation'))return route.fulfill({json:{goal_id:goal._id,goal_version:1,selection_version:1,confirmed:true,context:null,reason:null}});
  return route.fulfill({json:careerFixture(route.request().url(),{phase:'ready',current:{selection_version:1,goal}})});
 });
 const result={id:'synthetic-assessment',input_hash:'synthetic-input',groups:[],job_skill_gaps:[{ref:'job:python',name:'Python',match_status:'partial',components:[],competence_score:6.2,demonstrated_score:5,required_score:8,score_confidence:'medium',score_status:'estimated',score_explanation:'Independent successful project delivery.'}],interview_prep_gaps:[],constraints:[],priorities:[],research_coverage:'available'};
 await page.route('**/api/v1/assessments/**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/context')?{ready:true,model_available:true,input_hash:'synthetic-input',cv_reviewed:true,research_pending:false,issues:[]}:{version:1,operation:null,result,stale:false,ready:true,issues:[]}}));
 await page.goto('/career-goal');
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:900});
  const meter=page.getByRole('meter',{name:'Python progress towards this role'});
  await expect(meter).toBeVisible();
  await expect(meter).toHaveAttribute('aria-valuenow','6.2');
  await expect(page.getByText('Current 6.2/10')).toBeVisible();
  await expect(page.getByText('Goal 10/10')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.getByRole('button',{name:'Python',exact:true}).click();
 await expect(page.getByText('Role competence target: 8/10')).toBeVisible();
 await expect(page.getByText('You: about 5 / 10 · role needs about 8 / 10')).toBeVisible();
 await expect(page.getByText(/10\/10 means the goal is satisfied for this specific job role, based/)).toBeVisible();
});

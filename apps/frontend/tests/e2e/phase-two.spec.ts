import { test, expect } from '@playwright/test';
import { careerFixture } from './career-fixture';

test('compares saved evidence from Home without generating a roadmap', async ({ page }, testInfo) => {
 let compared = false; const commands: string[] = [];
 await page.addInitScript(() => { localStorage.setItem('elo.access-epoch','1'); sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'})); });
 await page.route('**/api/v1/**', route => {
  const path = new URL(route.request().url()).pathname;
  const method = route.request().method();
  if (method !== 'GET') commands.push(path);
  const respond = (json: Parameters<typeof careerFixture>[1]) => route.fulfill({json: careerFixture(route.request().url(),json)});
  if (path.endsWith('/auth-config')) return respond({mode:'email',google_enabled:false});
  if (path.endsWith('/auth/session')) return respond({id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'});
  if (path.endsWith('/school-categories')) return respond([]);
  if (path === '/api/v1/profile') return respond({version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false});
  if (path.endsWith('/profile/skills-profile')) return respond({version:1,status:'saved',saved_at:'2026-11-10T00:00:00Z',areas:{},entries:[]});
  if (path.endsWith('/profile/capabilities')) return respond({version:1,declarations:[],limits:{name:120,description:2000}});
  if (path === '/api/v1/cv') return respond({cvs:[],selection:{cv_id:null,version:0}});
  if (path.endsWith('/career/goals/current')) return respond({goal:{_id:'012345678901234567890123',version:1,field:'Software',company:null,location:null,seniority_level:null,job_url:null,interests:[],preferences:[],readiness:'ready',exploration_draft_id:null,exploration_draft_version:null,role:'Synthetic Developer',target_type:'specific_job',skills:[{item_id:'python',name:'Python',category:'Technical coding',priority:'required',origin:'employer'}]},selection_version:1});
  if (path.endsWith('/assessments/context')) return respond({ready:true,model_available:true,research_coverage:'unavailable',goal:{role:'Synthetic Developer'}});
  if (path === '/api/v1/assessments' && method === 'POST') {compared=true; return respond({version:2,operation:{id:'synthetic-operation',status:'succeeded'}});}
  if (path.endsWith('/assessments/current')) return respond({version:compared?2:0,stale:false,ready:true,issues:[],operation:null,result:compared?{id:'comparison',role:'Synthetic Developer',research_coverage:'unavailable',groups:[],priorities:['job:python'],job_skill_gaps:[{ref:'job:python',name:'Python',match_status:'confirmed_shortfall',components:[{status:'confirmed_shortfall',explanation:'Synthetic declared limitation.',evidence_refs:[]}]}]}:null});
  if (path.includes('/roadmaps/workspace')) return respond({version:0,messages:[],operation:null,context:{ready:true},planner:{config:{},runway:{resolved:{},calendar:null},active:null,candidate:null}});
  if (path.endsWith('/roadmaps/learning')) return respond({has_roadmap:false,steps:[]});
  if (path.endsWith('/jobs/applications')) return respond({items:[]});
  return respond({});
 });
 await page.goto('/dashboard');
 await expect(page.getByRole('heading',{name:'Welcome back, Synthetic.'})).toBeVisible();
 await page.getByRole('button',{name:'Compare with my skills'}).click();
  await expect(page.getByRole('heading',{name:'0 of 1 skill you already have'})).toBeVisible();
 await expect(page.getByText('Partial comparison: interview research is unavailable.')).toBeVisible();
 expect(commands).toEqual(['/api/v1/assessments']);
 await page.reload();
 await expect(page.getByRole('heading',{name:'0 of 1 skill you already have'})).toBeVisible();
 for (const width of [1440,390]) {
  await page.setViewportSize({width,height:1000});
  await page.screenshot({path:testInfo.outputPath(`home-${width}.png`),fullPage:true});
 }
});

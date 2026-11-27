import { test, expect, type Page } from '@playwright/test';
import type { WeekPreview, Outline, PlannedRoadmap, Workspace } from '../../src/features/roadmap/types';
import { blankPlanner, config, review, roadmap, runway, workspace } from '../fixtures/roadmap-workspace';

function initial(): Workspace { return workspace({ planner: { ...blankPlanner(), inputs: { goal: { role: 'Backend developer', target_type: 'specific_job', skills: [{ name: 'Python' }] }, cv: { id: 'synthetic-cv', name: 'synthetic-cv.docx' }, skills: [{ ref: 'cv:skill', name: 'Git', kind: 'skill', text: 'Used Git on a synthetic project.' }], experience: [{ ref: 'cv:project', name: 'Synthetic API project', kind: 'project', text: 'Built an API.' }], skill_groups: { Git: 'Tools' } } } }); }

async function signIn(page: Page) {
 await page.addInitScript(() => { localStorage.setItem('elo.access-epoch', '1'); sessionStorage.setItem('elo.session', JSON.stringify({ marker: 'synthetic-session', epoch: '1' })); });
 await page.route('**/api/v1/profile**', route => { const path = new URL(route.request().url()).pathname;
  return route.fulfill({ json: path.endsWith('/auth-config') ? { mode: 'email', google_enabled: false } : path.endsWith('/auth/session') ? { id: 'synthetic-owner', name: 'Synthetic User', email_verified: true, provider: 'email' } : { version: 1, onboarding_complete: true, occupational_status: 'employed', education: {} } }); });
}
const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

test('creates an active roadmap without review, keeps progress and settings, and works on mobile', async ({ page }) => {
 await signIn(page);
 const plan=roadmap();
 const weeks=[{week_start:'2030-01-07',start_date:'2030-01-09',end_date:'2030-01-13',objective:'Build a tested endpoint',expected_outcome:'The endpoint test passes',estimated_minutes:60,milestone_key:'m1',gap_ids:['python']},{week_start:'2030-01-14',start_date:'2030-01-14',end_date:'2030-01-20',objective:'Handle error cases',expected_outcome:'Invalid inputs are covered',estimated_minutes:180,milestone_key:'m1',gap_ids:['python']}];
 const outline:Outline={id:'outline',revision:1,summary:plan.summary,gaps:plan.gaps,milestones:plan.milestones,routine_rules:[],deadline_outcome:plan.deadline_outcome,beyond_deadline:[],exclusions:[],config:plan.config,weeks};
 const preview:WeekPreview={id:'week',week_start:'2030-01-07',start_date:'2030-01-09',end_exclusive:'2030-01-14',summary:'Start with one endpoint.',target:{weekly_minutes:300,target_minutes:60,shortfall_minutes:240,reasons:[{code:'partial_week',message:'Only part of this week remains.'}]},tasks:[{id:'a1',title:'Write one tested Python endpoint.',instructions:'Build and test it.',completion_outcome:'The endpoint test passes.',schedule:[{date:'2030-01-09',start_time:'19:00',duration_minutes:60}]}],carryover:[],objective_changes:[]};
 let state=workspace({planner:{...initial().planner,config:config(),config_saved:true,runway:runway()}});const requests:string[]=[];
 await page.route('**/api/v1/assessments/**',route=>route.fulfill({json:{version:0,stale:false,ready:true,model_available:true,result:null,operation:null,issues:[],evaluation:{freshness:'current',processing:'idle',completeness:'complete',evaluated_at:null,reasons:[]}}}));
 await page.route('**/api/v1/roadmaps/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace('/api/v1/roadmaps','');requests.push(path);
  if(route.request().method()==='GET')return route.fulfill({json:state});
  const body=route.request().postDataJSON();
  if(path==='/planner/runway')return route.fulfill({json:runway()});
  expect(body.expected_version).toBe(state.version);
  state={...state,version:state.version+1};
  if(path==='/planner/config')state={...state,planner:{...state.planner,config:body.config}};
  if(path==='/planner/outlines/generate'){expect(body.auto_accept).toBe(true);state={...state,planner:{...state.planner,outline_candidate:null,week_candidate:null,outline_active:outline,active:plan,active_review:review(plan),weeks:weeks.map((w,i)=>({...w,status:i===0?'planned':'projected'}))}};}
  if(path==='/planner/outlines/outline/accept')state={...state,planner:{...state.planner,outline_candidate:null,week_candidate:null,outline_active:outline,active:plan,active_review:review(plan),weeks:weeks.map((w,i)=>({...w,status:i===0?'planned':'projected'}))}};
  if(path==='/planner/tasks/status'){
   const active={...state.planner.active!,assignments:state.planner.active!.assignments.map(a=>({...a,status:'completed' as const,completed_at:'2030-01-09T12:00:00Z'}))};
   state={...state,planner:{...state.planner,active,active_review:review(active)}};
  }
  return route.fulfill({json:state});
 });
 await page.goto('/roadmap');await expect(page.getByLabel('Break minutes per hour of study')).toHaveValue('10');await expect(page.getByRole('link',{name:'More roadmap settings'})).toHaveCount(0);await expect(page.getByText('Backup blocks',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Create roadmap'}).click();await expect(page.getByRole('navigation',{name:'Roadmap views'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Review your roadmap'})).toHaveCount(0);
 await expect(page.getByText('Handle error cases',{exact:true})).toHaveCount(0);
 expect(state.planner.active).not.toBeNull();
 await page.setViewportSize({width:390,height:844});expect(await noOverflow(page)).toBe(true);
 for(const view of ['Today','Week','Month','Milestones','Progress']){await page.getByRole('navigation',{name:'Roadmap views'}).getByRole('button',{name:view,exact:true}).click();expect(await noOverflow(page)).toBe(true);await expect(page.getByText('Handle error cases',{exact:true})).toHaveCount(0);}
 await page.getByRole('navigation',{name:'Roadmap views'}).getByRole('button',{name:'Today',exact:true}).click();await page.getByRole('button',{name:'Mark done: Write one tested Python endpoint.'}).click();await page.reload();await expect(page.getByRole('button',{name:'Mark not done: Write one tested Python endpoint.'})).toBeVisible();
 await page.goto('/settings/roadmap');await expect(page.getByRole('heading',{name:'Roadmap settings'})).toHaveCount(0);await expect(page.getByLabel('Break minutes per hour',{exact:true})).toHaveCount(0);
 await page.goto('/roadmap');await expect(page.getByRole('link',{name:'Settings',exact:true})).toHaveCount(0);await page.goto('/settings');await expect(page.getByRole('heading',{name:'Settings',exact:true})).toHaveCount(0);await expect(page.getByLabel('Colour mode')).toHaveCount(0);
 expect(requests.some(p=>p.includes('/months')||p==='/planner/generate'||p==='/planner/roll-forward')).toBe(false);
});

test('a date field stays inside its border while editing, and a date problem shows only the field', async ({ page }) => {
 await page.setViewportSize({ width: 1280, height: 900 });
 await signIn(page);
 const state = workspace({ planner: { ...blankPlanner(), config: config({ start_date: '2030-01-09' }), runway: runway({ can_generate: false, issues: [{ code: 'start_in_past', message: 'Choose a start date from today onwards.' }] }) } });
 await page.route('**/api/v1/roadmaps/**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/planner/runway') ? state.planner.runway : state }));
 await page.goto('/roadmap');
 const field = page.getByLabel('Start date');
 const token = page.locator('.date-token').first();
 await field.focus();
 await expect(token).toHaveClass(/warn/);
 const [inner, outer] = [await field.boundingBox(), await token.boundingBox()];
 expect(inner!.x).toBeGreaterThanOrEqual(outer!.x);
 expect(inner!.y).toBeGreaterThanOrEqual(outer!.y);
 expect(inner!.x + inner!.width).toBeLessThanOrEqual(outer!.x + outer!.width + .5);
 expect(inner!.y + inner!.height).toBeLessThanOrEqual(outer!.y + outer!.height + .5);
 const content = page.locator('.road-stop[aria-current="step"] .road-content');
 if (await content.count()) await expect(content).toHaveCSS('box-shadow', 'none');
 await page.screenshot({ path: test.info().outputPath('date-focus.png') });
 await page.getByRole('button', { name: /Skills profile/ }).click();
 await page.keyboard.press('Escape');
 await expect(page.locator('.use-panel')).toHaveCount(0);
});

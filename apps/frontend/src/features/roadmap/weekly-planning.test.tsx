import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { RoadmapPlanner } from './roadmap-planner';
import type { Outline, WeekPreview, Workspace } from './types';
import { planner, review, roadmap, workspace } from '../../../tests/fixtures/roadmap-workspace';
const api = vi.hoisted(() => vi.fn());
vi.mock('@/features/profile/profile-provider', () => ({useProfile: () => ({account:{id:'owner'}, token:'synthetic'})}));
vi.mock('@/lib/api/roadmap', () => ({roadmapApi:api, RoadmapError:class extends Error {status=409;}}));
vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(),assessmentApi:vi.fn(async path => path === '/context' ? {ready:true,model_available:true} : {version:0,stale:false,ready:true,result:null,operation:null,evaluation:{freshness:'current',processing:'idle',reasons:[]}})}));
vi.mock('@/lib/api/workspace-summary', async original => ({...await original<typeof import('@/lib/api/workspace-summary')>(),loadSkills:vi.fn(async () => ({total:0,experiences:0,groups:[]}))}));
function outline(): Outline {const p=roadmap();return {id:'outline',revision:1,summary:p.summary,gaps:p.gaps,milestones:p.milestones,routine_rules:[],deadline_outcome:p.deadline_outcome,beyond_deadline:[],exclusions:[],config:p.config,weeks:[{week_start:'2030-01-07',start_date:'2030-01-09',end_date:'2030-01-13',objective:'Build an endpoint',expected_outcome:'A test passes',estimated_minutes:60,milestone_key:'m1',gap_ids:['python']},{week_start:'2030-01-14',start_date:'2030-01-14',end_date:'2030-01-20',objective:'Test edge cases',expected_outcome:'Error cases covered',estimated_minutes:180,milestone_key:'m1',gap_ids:['python']}]};}
function week(): WeekPreview {return {id:'week',week_start:'2030-01-07',start_date:'2030-01-09',end_exclusive:'2030-01-14',summary:'Begin with one endpoint.',target:{weekly_minutes:300,target_minutes:60,shortfall_minutes:240,reasons:[{code:'partial_week',message:'Only part of this week remains.'}]},tasks:[{id:'task',title:'Write an endpoint',instructions:'Implement and test it.',completion_outcome:'The test passes.',schedule:[{date:'2030-01-09',start_time:'19:00',duration_minutes:60}]}],carryover:[],objective_changes:[]};}
function serve(initial: Workspace) {let state=initial;api.mockImplementation(async (path:string,_token:string,body:Record<string,unknown>) => {
 if(path.startsWith('/workspace')) return state;
 if(path==='/planner/outlines/generate') {const plan=roadmap();state={...state,planner:planner({active:plan,active_review:review(plan),outline_active:outline(),weeks:outline().weeks})};return {version:1,operation:null};}
 if(path==='/planner/outlines/outline/accept') {const plan=roadmap();state={...state,planner:planner({active:plan,active_review:review(plan),outline_active:outline()})};return state;}
 if(path.endsWith('/discard')) {state={...state,planner:{...state.planner,week_candidate:null,outline_candidate:null}};return state;}
 if(path==='/planner/config') return {...state,planner:{...state.planner,config:body.config}};
 if(path==='/planner/runway') return state.planner.runway;
 return state;
});}
beforeEach(()=>{api.mockReset();window.history.replaceState({},'','/roadmap');});
it('creates and displays the active tasks without an outline timeline or acceptance step',async()=>{
 serve(workspace());render(<RoadmapPlanner/>);fireEvent.click(await screen.findByRole('button',{name:'Create roadmap'}));
 await screen.findByRole('navigation',{name:'Roadmap views'});
 expect(api.mock.calls.find(c=>c[0]==='/planner/outlines/generate')?.[2]).toMatchObject({auto_accept:true});
 expect(api.mock.calls.some(c=>c[0].endsWith('/accept'))).toBe(false);
 expect(screen.queryByRole('heading',{name:'Review your roadmap'})).toBeNull();
 for(const view of ['Week','Month','Milestones']) {
  fireEvent.click(screen.getByRole('button',{name:view}));
  expect(screen.queryByText('Test edge cases')).toBeNull();
  expect(screen.queryByText('Build an endpoint')).toBeNull();
  expect(screen.queryByText(/Detailed tasks not generated/)).toBeNull();
 }
 expect(api.mock.calls.some(c=>/months|roll-forward|planner\/generate$/.test(c[0]))).toBe(false);
});
it('returns from settings to tasks after updating the roadmap',async()=>{
 const plan=roadmap();serve(workspace({planner:planner({active:{...plan,id:'old'},active_review:review(plan),outline_active:outline()})}));
 render(<RoadmapPlanner/>);fireEvent.click(await screen.findByRole('button',{name:'Plan settings'}));
 fireEvent.click(await screen.findByRole('button',{name:'Update roadmap'}));
 await screen.findByRole('navigation',{name:'Roadmap views'});
 expect(screen.queryByRole('button',{name:'Update roadmap'})).toBeNull();
});
it('returns to settings and preserves the same combined preview',async()=>{
 serve(workspace({planner:planner({outline_candidate:outline(),week_candidate:week()})}));render(<RoadmapPlanner/>);
 fireEvent.click(await screen.findByRole('button',{name:'Plan settings'}));await screen.findByRole('button',{name:'Create roadmap'});fireEvent.click(screen.getByRole('button',{name:'Return to roadmap'}));await screen.findByRole('button',{name:'Accept roadmap and first week'});
});
it('discards an unaccepted preview without changing accepted work',async()=>{
 serve(workspace({planner:planner({outline_candidate:outline(),week_candidate:week()})}));render(<RoadmapPlanner/>);fireEvent.click(await screen.findByRole('button',{name:'Discard preview'}));await screen.findByRole('button',{name:'Create roadmap'});expect(api.mock.calls.filter(c=>c[0]==='/planner/outlines/outline/discard')).toHaveLength(1);
});
it('keeps a failed first-week generation reviewable and explains the recovery',async()=>{
 serve(workspace({planner:planner({outline_candidate:{...outline(),first_week_error:'Add study time and plan the first week again.'}})}));render(<RoadmapPlanner/>);expect(await screen.findByText('Add study time and plan the first week again.')).toBeVisible();expect(screen.getByRole('button',{name:'Accept weekly outline'})).toBeVisible();
});
it('opens next-week planning on the configured day and submits optional workload feedback',async()=>{
 const p=roadmap();serve(workspace({planner:planner({active:p,active_review:review(p),outline_active:outline(),week_planning:{action:'plan_next',week_start:'2030-01-14',available:true,plan_day:'2030-01-13',week_done:false,unfinished_count:1}})}));render(<RoadmapPlanner/>);
 fireEvent.change(await screen.findByLabelText('Workload'),{target:{value:'too_much'}});fireEvent.change(screen.getByLabelText('Anything to adjust?'),{target:{value:'More examples please'}});fireEvent.click(screen.getByRole('button',{name:'Plan next week'}));await waitFor(()=>expect(api.mock.calls.find(c=>c[0]==='/planner/weeks/generate')?.[2]).toMatchObject({week_start:'2030-01-14',feedback:{workload:'too_much',difficulty:null,note:'More examples please'}}));
});
it('explains when the next week opens without generating automatically',async()=>{
 const p=roadmap();serve(workspace({planner:planner({active:p,active_review:review(p),outline_active:outline(),week_planning:{action:'plan_next',week_start:'2030-01-14',available:false,plan_day:'2030-01-13',week_done:false,unfinished_count:0}})}));render(<RoadmapPlanner/>);await screen.findByText(/Available on/);expect(screen.queryByRole('button',{name:'Plan next week'})).toBeNull();expect(api.mock.calls.some(c=>c[0]==='/planner/weeks/generate')).toBe(false);
});
it('shows carry decisions and future objective changes, allowing reviewed overrides',async()=>{
 const w=week();w.carryover=[{task_id:'old',title:'Finish tests',action:'split',minutes:25,reason:'Spread the workload.',schedule:[]}];w.objective_changes=[{...outline().weeks![1],previous:outline().weeks![1],objective:'Review error cases',reason:'More practice needed.'}];
 serve(workspace({planner:planner({outline_active:outline(),week_candidate:w})}));render(<RoadmapPlanner/>);await screen.findByText('Finish tests');expect(screen.getByText(/remaining work stays/)).toBeVisible();expect(screen.getByText('Previously: Test edge cases')).toBeVisible();fireEvent.change(screen.getByLabelText('What happens next'),{target:{value:'defer'}});await waitFor(()=>expect(api.mock.calls.find(c=>c[0]==='/planner/weeks/week/carryover')?.[2]).toMatchObject({decisions:[{task_id:'old',action:'defer'}]}));
});
it('keeps acceptance disabled when tasks do not fit the reviewed schedule',async()=>{
 serve(workspace({planner:planner({outline_active:outline(),week_candidate:{...week(),unplaced:[{id:'x',title:'Too large'}]}})}));render(<RoadmapPlanner/>);expect(await screen.findByRole('button',{name:'Accept week'})).toBeDisabled();expect(screen.getByText(/Some tasks no longer fit/)).toBeVisible();
});
it('requires saving outline edits before accepting and strips read-only checkpoint progress',async()=>{
 const value=outline();value.milestones[0].checkpoints=[{key:'runs',title:'API runs',date:'2030-01-10',reached_at:'2030-01-09T00:00:00Z'}];
 serve(workspace({planner:planner({outline_candidate:value,week_candidate:week()})}));render(<RoadmapPlanner/>);fireEvent.click(await screen.findByRole('button',{name:'Edit outline'}));expect(screen.getByRole('button',{name:'Accept roadmap and first week'})).toBeDisabled();fireEvent.change(screen.getByLabelText('Title'),{target:{value:'Build a reviewed API'}});fireEvent.click(screen.getByRole('button',{name:'Save outline changes'}));
 await waitFor(()=>expect(api.mock.calls.find(c=>c[0]==='/planner/outlines/outline')?.[4]).toEqual({method:'PATCH'}));
 const body=api.mock.calls.find(c=>c[0]==='/planner/outlines/outline')![2];expect(body.outline.milestones[0].title).toBe('Build a reviewed API');expect(body.outline.milestones[0].checkpoints[0]).not.toHaveProperty('reached_at');expect(body.outline.weeks).toHaveLength(2);
});
it('blocks acceptance when the source evidence changes',async()=>{
 const state=workspace({planner:planner({outline_candidate:{...outline(),assessment_hash:'old'},week_candidate:week()})});state.context.input_hash='new';serve(state);render(<RoadmapPlanner/>);expect(await screen.findByRole('button',{name:'Accept roadmap and first week'})).toBeDisabled();expect(screen.getByText(/generate a fresh preview before accepting/)).toBeVisible();
});
it('retries a failed weekly generation using the exact saved mutation',async()=>{
 const retry={expected_version:0,mutation_id:'saved-week-request',week_start:'2030-01-14',feedback:{workload:'too_much',note:'More time'}};
 serve(workspace({operation:{id:'saved-week-request',status:'failed',stage:'writing',error:{code:'model_provider',detail:'Provider unavailable.'}},planner:planner({outline_active:outline(),retry_week:retry})}));render(<RoadmapPlanner/>);fireEvent.click(await screen.findByRole('button',{name:'Try again'}));await waitFor(()=>expect(api.mock.calls.find(c=>c[0]==='/planner/weeks/generate')?.[2]).toEqual(retry));
});
it('labels a partial roadmap and lists omissions before acceptance', async()=>{
 const partial={...outline(),partial_review:{omitted_items:[{kind:'gap',id:'bad',title:'Preferred infrastructure',reason:'Unknown assessment reference.'}],uncovered_requirements:['job:missing']}};
 serve(workspace({planner:planner({outline_candidate:partial,week_candidate:week()})}));render(<RoadmapPlanner/>);
 expect(await screen.findByRole('status',{name:'Partial roadmap'})).toHaveTextContent('Two generation attempts');
 fireEvent.click(screen.getByText('What was omitted (1)'));expect(screen.getByText('Preferred infrastructure')).toBeVisible();
 expect(screen.getByText(/1 assessment priority is not covered/)).toBeVisible();
 expect(screen.getByRole('button',{name:'Accept roadmap and first week'})).toBeEnabled();
});

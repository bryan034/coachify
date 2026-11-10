import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { HomeDashboard, journeyStates } from './home';
import { ProfileProvider } from '@/features/profile/profile-provider';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const liveData=(url:string):any=>{
 if(url.endsWith('/auth/session'))return {id:'synthetic',name:'Synthetic Person',provider:'local_test',onboarding_complete:true};
 if(url.endsWith('/auth-config'))return {mode:'local_test'};
 if(url.endsWith('/school-categories'))return [];
 if(url.endsWith('/career/goals/current'))return {goal:{_id:'g',version:1,target_type:'career_exploration',role:'Synthetic Analyst',field:'Data',employment_type:'internship',company:null,location:null,seniority_level:null,job_url:null,skills:[{name:'SQL',category:'x',priority:'required',origin:'employer'},{name:'Excel',category:'x',priority:'preferred',origin:'employer'}],interests:[],preferences:[],readiness:'ready',exploration_draft_id:null,exploration_draft_version:null},selection_version:1,dependent_results_need_review:false,skill_groups:{SQL:'Data & analytics',Excel:'Data & analytics'}};
 if(url.includes('/assessments/'))return {version:0,stale:false,ready:true,model_available:true,result:null,operation:null,issues:[]};
 if(url.endsWith('/profile/skills-profile'))return {version:0,status:'empty',saved_at:null,areas:{},entries:[]};
 if(url.endsWith('/profile/capabilities'))return {version:1,declarations:[{id:'d1',name:'Python',description:'Synthetic.',skill_id:'python',provenance:'user_declared',created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'}],limits:{name:120,description:2000},skill_groups:{Python:'Technical coding'}};
 if(url.endsWith('/api/v1/cv'))return {cvs:[],selection:{cv_id:null,version:0}};
 if(url.includes('/roadmaps/workspace'))return {version:0,messages:[],operation:null,active:null,draft:null,assessment:null,stale:false,context:{ready:true,issues:[],model_available:true},planner:{config:{weekly_minutes:600,preferred_session_minutes:120},runway:{can_generate:true,issues:[],resolved:{today:'2026-11-06',start_date:'2026-11-06',target_date:'2027-05-04',matched_duration:null},calendar:{days:179,weeks:25,extra_days:4,label:'',partial_first_week:false},study:{},weeks:[],first_planning_week:null},inputs:{},candidate:null,candidate_review:null,candidate_blockers:[],active:null,active_review:null,confirmations:{},signals:[]}};
 if(url.endsWith('/roadmaps/learning'))return {has_roadmap:true,roadmap_id:'plan',skills_total:1,skills_started:1,skills_done:0,steps:[{gap_id:'sql',name:'Synthetic SQL',status:'confirmed_gap',state:'in_progress',priority:1,rationale:'Synthetic.',milestones:['Synthetic milestone'],sessions_total:4,sessions_completed:1,sessions_missed:1,completed_minutes:60,remaining_minutes:180,next_session:{id:'a2',date:'2027-01-14',start_time:'19:00',duration_minutes:60,task:'Write a synthetic join.',completion_criterion:'It runs.'}}]};
 if(url.endsWith('/jobs/applications'))return {items:[]};
 return {version:1,occupational_status:'student',school_category:'university',current_study_year:3,education_review_required:false,education:{course:'Synthetic Course'}};
};
test('Home reads each service and names the first unfinished stop on the path',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(liveData(url)))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 expect(await screen.findByRole('heading',{level:1,name:'Welcome back, Synthetic.'})).toBeVisible();
 const match=await screen.findByRole('region',{name:/skills this role needs/});
 expect(within(match).getByText('Goal match · Synthetic Analyst')).toBeVisible();
 expect(await screen.findByText(/until your target date/)).toHaveTextContent('179 days until your target date');
 expect(await screen.findByRole('link',{name:'Compare my skills'})).toHaveAttribute('href','/career-goal');
 expect(screen.getByText('Next: compare your skills with your career goal.')).toBeVisible();
 expect(screen.getByText('3 of 5 steps done')).toBeVisible();
 expect(screen.getByRole('link',{name:'Plan your roadmap'})).toHaveAttribute('href','/roadmap');
 const skills=screen.getByRole('region',{name:'Skills Profile'});
 expect(within(skills).getByText('1 skill')).toBeVisible();
 expect(screen.getByRole('region',{name:'Coming up'})).toHaveTextContent('No deadlines or follow-ups coming up.');
 expect(screen.queryByText(/Soon/)).not.toBeInTheDocument();
});
test('Goal match counts the saved comparison and lists the top gaps, essential first',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  if(url.endsWith('/career/goals/current'))return new Response(JSON.stringify({...liveData(url),goal:{...liveData(url).goal,skills:[{item_id:'a',name:'SQL',category:'x',priority:'preferred',origin:'employer'},{item_id:'b',name:'Testing',category:'x',priority:'required',origin:'employer'},{item_id:'c',name:'Excel',category:'x',priority:'preferred',origin:'employer'}]}}));
  if(url.includes('/assessments/')&&url.endsWith('/current'))return new Response(JSON.stringify({version:1,stale:false,ready:true,model_available:true,operation:null,issues:[],result:{groups:[],job_skill_gaps:[{ref:'job:a',match_status:'confirmed_shortfall'},{ref:'job:b',match_status:'confirmed_shortfall'},{ref:'job:c',match_status:'supported'}]}}));
  return new Response(JSON.stringify(liveData(url)));
 }));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 const match=await screen.findByRole('region',{name:/skills you already have/});
 expect(within(match).getByRole('img',{name:'Have 1, partial 0, gap 2, unknown 0'})).toBeInTheDocument();
 const gaps=within(match).getAllByRole('listitem').filter(item=>item.querySelector('.home-gap-name'));
 expect(gaps.map(item=>item.querySelector('.home-gap-name')!.textContent)).toEqual(['Testing','SQL']);
 expect(within(gaps[0]).getByText('Essential')).toBeVisible();
 expect(within(match).getByRole('link',{name:'Close these gaps in your roadmap'})).toHaveAttribute('href','/roadmap');
});
test('A failed service is reported where it belongs and never counted as done or as next',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith('/career/goals/current')?new Response(JSON.stringify({detail:'Career service unavailable.'}),{status:503}):new Response(JSON.stringify(liveData(url)))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 expect(await screen.findByRole('button',{name:'Retry career goal'})).toBeVisible();
 expect(await screen.findByRole('link',{name:'Compare my skills'})).toBeVisible();
 expect(screen.queryByText(/of 5 steps done/)).not.toBeInTheDocument();
 expect(screen.getByRole('link',{name:/Career goal.*Not available/})).toHaveAttribute('href','/career-goal');
});
test('journey states wait for every stop before naming the next one',()=>{
 expect(journeyStates([true,'loading',false])).toEqual(['done','checking','checking']);
 expect(journeyStates([true,'error',false,false])).toEqual(['done','unavailable','next','later']);
 expect(journeyStates([true,true])).toEqual(['done','done']);
});
test('Coming up lists saved-job deadlines and follow-ups in date order',async()=>{
 const job=(id:string,extra:object)=>({id,posting_id:id,version:1,status:'saved',posting_status:'open',snapshot:{title:`Intern ${id}`,company:'Synthetic Co',location:'Singapore',job_type:'internship',listing_url:'https://example.test',apply_url:'https://example.test'},history:[],created_at:'2026-11-01T00:00:00Z',updated_at:'2026-11-01T00:00:00Z',...extra});
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/jobs/applications')?{items:[job('b',{status:'applied',follow_up_at:'2026-11-20'}),job('a',{deadline:'2026-11-10'}),job('c',{deadline:'2026-10-01'})]}:liveData(url)))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 const upcoming=await screen.findByRole('region',{name:'Coming up'});
 await within(upcoming).findByText('Application deadline');
 expect(within(upcoming).getAllByRole('listitem').map(item=>item.querySelector('strong')!.textContent)).toEqual(['Application deadline','Follow up']);
 expect(upcoming).toHaveTextContent('Intern a · Synthetic Co · in 4 days');
 expect(upcoming).not.toHaveTextContent('Intern c');
});

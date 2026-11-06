import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { HomeDashboard, journeyStates } from './home';
import { ProfileProvider } from '@/features/profile/profile-provider';

test.each([
 { status: 'student', currentYear: 6, expected: 'Computing & Design · Year 6' },
 { status: 'employed', currentYear: null, expected: 'Computing & Design' },
])('Home shows independent education fields for $status without inventing a current year', async ({status,currentYear,expected})=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(
  url.endsWith('/auth/session') ? {id:'synthetic',name:'Synthetic',provider:'local_test',onboarding_complete:false} : url.endsWith('/auth-config') ? {mode:'local_test'} : url.endsWith('/school-categories') ? [] : {
   version:1,occupational_status:status,school_category:'university',current_study_year:currentYear,
   education_review_required:false,education:{course:'Computing & Design',study_year:6},
  }
 ))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 const detail=await screen.findByText(expected,{exact:true});
 expect(detail).toBeInTheDocument();
 if(!currentYear) expect(screen.queryByText(/Year 6/)).not.toBeInTheDocument();
 expect(screen.queryByText('Ethan')).not.toBeInTheDocument();
});

const liveData=(url:string)=>{
 if(url.endsWith('/auth/session'))return {id:'synthetic',name:'Synthetic Person',provider:'local_test',onboarding_complete:true};
 if(url.endsWith('/auth-config'))return {mode:'local_test'};
 if(url.endsWith('/school-categories'))return [];
 if(url.endsWith('/career/goals/current'))return {goal:{_id:'g',version:1,target_type:'career_exploration',role:'Synthetic Analyst',field:'Data',employment_type:'internship',company:null,location:null,seniority_level:null,job_url:null,skills:[{name:'SQL',category:'x',priority:'required',origin:'employer'},{name:'Excel',category:'x',priority:'preferred',origin:'employer'}],interests:[],preferences:[],readiness:'ready',exploration_draft_id:null,exploration_draft_version:null},selection_version:1,dependent_results_need_review:false,skill_groups:{SQL:'Data & analytics',Excel:'Data & analytics'}};
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
 expect(await screen.findByRole('heading',{level:1,name:'Welcome to elo, Synthetic.'})).toBeVisible();
 expect(await screen.findByText('Synthetic Analyst')).toBeVisible();
 expect(screen.getByText('2 skills this role needs')).toBeVisible();
 expect((await screen.findByRole('list',{name:'Skills per category'})).textContent).toContain('Technical coding');
 expect(await screen.findByText(/days to Tue, 4 May 2027/)).toHaveTextContent('179 days to');
 expect(screen.getByText('10 hrs a week')).toBeVisible();
 expect(screen.getByText('2-hr sessions')).toBeVisible();
 expect(await screen.findByRole('link',{name:'Plan your roadmap'})).toHaveAttribute('href','/roadmap');
 expect(screen.getByText('3 of 5 steps done')).toBeVisible();
 expect(screen.getByRole('link',{name:'Generate roadmap'})).toHaveAttribute('href','/roadmap');
 const learning=await screen.findByRole('region',{name:'Learning & skills'});
 expect(within(learning).getByText('Synthetic SQL')).toBeVisible();
 expect(within(learning).getByText('1 of 4 sessions done, 1 missed')).toBeVisible();
 expect(within(learning).getByText('Next on 14 Jan: Write a synthetic join.')).toBeVisible();
 expect(within(learning).getByRole('progressbar',{name:'Synthetic SQL sessions done'})).toHaveAttribute('aria-valuenow','1');
 expect(screen.getByRole('link',{name:/Learning & skills.*1 of 1 skill started/})).toHaveAttribute('href','#home-learning');
});
test('A failed service is reported where it belongs and never counted as done or as next',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>url.endsWith('/career/goals/current')?new Response(JSON.stringify({detail:'Career service unavailable.'}),{status:503}):new Response(JSON.stringify(liveData(url)))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 expect(await screen.findByRole('button',{name:'Retry career goal'})).toBeVisible();
 expect(await screen.findByRole('link',{name:'Plan your roadmap'})).toBeVisible();
 expect(screen.queryByText(/of 5 steps done/)).not.toBeInTheDocument();
 expect(screen.getByRole('link',{name:/Career goal.*Not available/})).toHaveAttribute('href','/career-goal');
});
test('journey states wait for every stop before naming the next one',()=>{
 expect(journeyStates([true,'loading',false])).toEqual(['done','checking','checking']);
 expect(journeyStates([true,'error',false,false])).toEqual(['done','unavailable','next','later']);
 expect(journeyStates([true,true])).toEqual(['done','done']);
});
test('Learning & skills invites a roadmap until one exists',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/roadmaps/learning')?{has_roadmap:false,roadmap_id:null,skills_total:0,skills_started:0,skills_done:0,steps:[]}:liveData(url)))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 expect(await screen.findByRole('link',{name:/Learning & skills.*Personal steps appear once you have a roadmap/})).toHaveAttribute('href','/roadmap');
 expect(screen.queryByRole('region',{name:'Learning & skills'})).not.toBeInTheDocument();
});

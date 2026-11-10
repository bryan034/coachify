import {cleanup,act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CareerGoalHome,CareerGoalOverview,LearningFocus} from './career-overview';
import {CareerSessionProvider} from './career-session';
import {getCvGoalConfirmation,confirmCvGoal} from '@/lib/api/career-cv-confirmation';
import {careerApi,refreshWorkspace,type CareerWorkspace} from '@/lib/api/career';
vi.mock('@/lib/api/career-cv-confirmation',()=>({getCvGoalConfirmation:vi.fn(),confirmCvGoal:vi.fn()}));
const push=vi.fn(),params=new URLSearchParams();
vi.mock('next/navigation',()=>({useRouter:()=>({push,replace:vi.fn()}),useSearchParams:()=>params}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn(),importCareer:vi.fn(),refreshWorkspace:vi.fn()}));
const extraction={role:'Backend Software Engineer',field:'Software Engineering',company:'Example',location:'Singapore',seniority_level:'Entry level',job_url:null,summary:'Build backend services.',responsibilities:['Build APIs'],skills:[{item_id:'sql',name:'SQL',category:'Technical',priority:'required' as const,origin:'employer' as const},{item_id:'team',name:'Teamwork',category:'Transferable',priority:'preferred' as const,origin:'employer' as const}],non_skill_requirements:[{requirement_id:'degree',category:'Qualifications',description:'A relevant degree',priority:'preferred',evidence:'A relevant degree is preferred.',group_id:null,group_operator:'all' as const}]};
const workspace:CareerWorkspace={session_id:'session',revision:1,kind:'jd',phase:'ready',current:{selection_version:1,skill_groups:{SQL:'Data & analytics',Teamwork:'Communication & leadership'},goal:{...extraction,_id:'goal',version:1,target_type:'specific_job',interests:[],preferences:[],readiness:'pending',exploration_draft_id:null,exploration_draft_version:null},dependent_results_need_review:false},research_id:'research',research_version:1,coverage:[],error:null,retry_after:null,expires_at:null,exploration_id:null};

const skillRow=(name:string)=>screen.getByRole('button',{name}).closest('li')!;
function overview(value=workspace){return render(<CareerSessionProvider><CareerGoalOverview workspace={value} onReload={vi.fn()}/></CareerSessionProvider>);}
afterEach(()=>vi.useRealTimers());
beforeEach(()=>{vi.resetAllMocks();vi.mocked(refreshWorkspace).mockImplementation(async(_previous,token,signal)=>careerApi('/workspace',token,{signal}));vi.mocked(getCvGoalConfirmation).mockResolvedValue({goal_id:'goal',goal_version:1,selection_version:1,confirmed:false,context:null,reason:null});params.forEach((_,key)=>params.delete(key));vi.mocked(careerApi).mockImplementation(async(path)=>path==='/workspace'?workspace as never:{status:'no_cv',cv_uploaded:false,skills_evaluated:false} as never);});
it('shows saved skills in briefing accordions and keeps refinement and replacement',async()=>{
 overview();expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Skills this role needs'})).toBeVisible();
 expect(screen.getByRole('button',{name:'SQL'})).toHaveAttribute('aria-expanded','false');
 fireEvent.click(screen.getByRole('button',{name:'SQL'}));
 expect(screen.getByRole('button',{name:'SQL'})).toHaveAttribute('aria-expanded','true');
 expect(screen.getByRole('button',{name:'Teamwork'})).toHaveAttribute('aria-expanded','false');
 expect(screen.getByText('2 saved skills')).toBeVisible();
 // Rows sit under their category heading instead of repeating it on every row.
 expect(skillRow('SQL').closest('section')!.querySelector('h3')).toHaveTextContent('Data & analytics');expect(within(skillRow('SQL')).getByText('Essential')).toBeVisible();
 expect(skillRow('Teamwork').closest('section')!.querySelector('h3')).toHaveTextContent('Communication & leadership');expect(within(skillRow('Teamwork')).getByText('Important')).toBeVisible();
 expect(screen.getByRole('link',{name:'Refine goal'})).toHaveAttribute('href','/career-goal/chat?refine=1');
 fireEvent.click(screen.getByRole('button',{name:/Set a new goal/}));expect(push).toHaveBeenCalledWith('/career-goal?new=1');
 expect(vi.mocked(careerApi).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
it('links the three goal pages as tabs and keeps eligibility on About the role',async()=>{
 overview();
 const tabs=screen.getByRole('navigation',{name:'Career goal pages'});
 expect(within(tabs).getAllByRole('link').map(link=>[link.textContent,link.getAttribute('href')])).toEqual([['Skills needed','/career-goal'],['Interview preparation','/career-goal/interview'],['About the role','/career-goal/role']]);
 expect(within(tabs).getByRole('link',{name:'Skills needed'})).toHaveAttribute('aria-current','page');
 cleanup();
 render(<CareerSessionProvider><CareerGoalOverview view="role" workspace={workspace} onReload={vi.fn()}/></CareerSessionProvider>);
 expect(within(screen.getByRole('navigation',{name:'Career goal pages'})).getByRole('link',{name:'About the role'})).toHaveAttribute('aria-current','page');
 expect(screen.queryByRole('heading',{name:'Skills this role needs'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByText('Eligibility and commitment'));
 expect(screen.getByText('A relevant degree')).toBeVisible();
 expect(screen.getByRole('heading',{name:'About the role'})).toBeVisible();
});
it('shows goal facts as plain metadata, separate from the real actions',()=>{
 overview();
 const meta=screen.getByRole('region',{name:'Your target role'}).querySelector('.briefing-target-meta')!;
 expect(within(meta as HTMLElement).queryByRole('button')).toBeNull();
 expect(meta).toHaveTextContent('Example');expect(meta).toHaveTextContent('Singapore');
});
it('marks each needed skill from the saved comparison',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({version:0,ready:true,model_available:true,operation:null,stale:false,result:{groups:[],job_skill_gaps:[{ref:'job:sql',match_status:'supported'},{ref:'job:team',match_status:'confirmed_shortfall'}]}}))));
 overview();
 expect(await within(skillRow('SQL')).findByText('Have')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByText('Gap')).toBeVisible();
 expect(screen.getByRole('button',{name:'SQL'})).toHaveAccessibleDescription('Have');
 expect(document.querySelector('.goal-skills-summary')).toHaveTextContent('You have 1 of 2 · 1 gap');
 expect(screen.queryByText(/Not yet compared/)).not.toBeInTheDocument();
 vi.unstubAllGlobals();
});
it('leaves skills unmarked and explains how to compare when no saved comparison exists',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({version:0,ready:true,model_available:true,operation:null,stale:false,result:null}))));
 overview();
 expect(screen.getByRole('link',{name:'Compare with your skills'})).toHaveAttribute('href','/cv');
 expect(screen.queryByText('Have')).not.toBeInTheDocument();
 vi.unstubAllGlobals();
});
it('displays extracted categories while research is still running',async()=>{
 overview({...workspace,phase:'researching',research_id:null});expect(screen.getByText('SQL')).toBeVisible();
 expect(screen.getByText('Researching opportunity information. Your extracted goal is already saved.')).toBeVisible();
});
it('restores the overview after reload instead of showing a new input form',async()=>{
 render(<CareerSessionProvider><CareerGoalHome/></CareerSessionProvider>);
 expect(await screen.findByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 expect(screen.queryByRole('textbox',{name:'Job description'})).not.toBeInTheDocument();
});
it('new-goal mode keeps the saved goal untouched and opens the input methods',()=>{
 params.set('new','1');render(<CareerSessionProvider><CareerGoalHome/></CareerSessionProvider>);
 expect(screen.getByRole('textbox',{name:'Job description'})).toBeVisible();expect(careerApi).not.toHaveBeenCalled();
 expect(screen.getByRole('link',{name:'← Back to saved goal'})).toHaveAttribute('href','/career-goal');
});

it('preserves AND/OR, provenance and safe sources without inventing learning guidance',async()=>{
 const goal={...workspace.current.goal!,skills:[{...extraction.skills[0],group_id:'alternatives',group_operator:'any' as const,context:'Maintain relational data.',evidence:'SQL or another query language.',source_urls:['https://example.test/job','javascript:alert(1)']},{...extraction.skills[1],origin:'generated_guidance' as const,priority:'suggested' as const}]};
 overview({...workspace,current:{...workspace.current,goal}});
 fireEvent.click(screen.getByRole('button',{name:'SQL'}));
 expect(screen.getByText('Maintain relational data.')).toBeVisible();
 // Job-description quotes stay out of skill cards; the source link remains.
 expect(screen.queryByText('SQL or another query language.')).not.toBeInTheDocument();
 expect(screen.getByText(/Alternative requirement/)).toBeVisible();
 expect(screen.getByRole('link',{name:'example.test ↗'})).toHaveAttribute('href','https://example.test/job');
 expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
 fireEvent.click(screen.getByText('Teamwork'));
 expect(screen.getByText('AI planning suggestion')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByText('Nice to have')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByLabelText('importance inferred by elo')).toBeInTheDocument();
 expect(screen.queryByText('A way to practise')).not.toBeInTheDocument();
});
it('hides role fields with no data and never labels individual skills as assessed',()=>{
 overview({...workspace,current:{...workspace.current,goal:{...workspace.current.goal!,skills:[],responsibilities:[],non_skill_requirements:[],summary:null}}});
 expect(screen.getByText(/No skills are listed/)).toBeVisible();
 expect(screen.queryByText(/Eligibility & commitment/)).not.toBeInTheDocument();
 expect(screen.queryByText(/0 requirements/)).not.toBeInTheDocument();
 expect(screen.queryByText('What you would work on')).not.toBeInTheDocument();
});

it('retries a failed research job without replacing the saved goal',async()=>{
 const reload=vi.fn();
 render(<CareerSessionProvider><CareerGoalOverview workspace={{...workspace,phase:'research_failed'}} onReload={reload}/></CareerSessionProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Retry research'}));
 await waitFor(()=>expect(careerApi).toHaveBeenCalledWith('/workspace/retry','synthetic-token',{method:'POST'}));
 await waitFor(()=>expect(reload).toHaveBeenCalledOnce());
 expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
});

it('labels advisory or unknown importance without relabelling it as required',()=>{
 render(<LearningFocus skills={[{...extraction.skills[0],priority:'suggested'},{...extraction.skills[1],priority:'conflicting'}]}/>);
 expect(within(skillRow('SQL')).getByText('Nice to have')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByText('Conflicting requirements')).toBeVisible();
 expect(screen.queryByText('Essential')).not.toBeInTheDocument();
 expect(screen.queryByText(/Not assessed against/)).not.toBeInTheDocument();
 expect(screen.queryByText(/Evidence in CV|No evidence yet|What to review in your CV/)).not.toBeInTheDocument();
});
it('handles empty and single-skill goals',()=>{
 const {rerender}=render(<LearningFocus skills={[]}/>);
 expect(screen.getByText(/No skills are listed/)).toBeVisible();
 expect(screen.queryByRole('heading',{level:3})).not.toBeInTheDocument();
 rerender(<LearningFocus skills={[extraction.skills[0]]} categories={{SQL:'Data & analytics'}}/>);
 expect(screen.getByText('Data & analytics')).toBeVisible();
 expect(screen.queryByRole('button',{name:/more skill/})).not.toBeInTheDocument();
 expect(screen.queryByText('Sorted by priority')).not.toBeInTheDocument();
});
it('groups by the categories the backend sent, most important first within each, with Other last',()=>{
 const skills=[{...extraction.skills[1],name:'Docker',item_id:'docker'},{...extraction.skills[0],name:'Python',item_id:'python'},{...extraction.skills[0],name:'Mystery',item_id:'mystery'}];
 render(<LearningFocus skills={skills} categories={{Docker:'Technical coding',Python:'Technical coding'}}/>);
 expect(screen.getAllByRole('heading',{level:3}).map(h=>h.textContent)).toEqual(['Technical coding','Other skills']);
 const names=()=>Array.from(document.querySelectorAll('.goal-skill-row .skill-row-toggle')).map(button=>document.getElementById(button.getAttribute('aria-labelledby')!)!.textContent);
 expect(names()).toEqual(['Python','Docker','Mystery']);
});
it('starts long lists short and reveals every skill on request',()=>{
 const skills=Array.from({length:13},(_,i)=>({...extraction.skills[0],name:`Skill ${i}`,item_id:`s${i}`}));
 render(<LearningFocus skills={skills} categories={Object.fromEntries(skills.map((skill,i)=>[skill.name,i<10?'Technical coding':'Data & analytics']))}/>);
 expect(document.querySelectorAll('.goal-skill-row')).toHaveLength(10);
 fireEvent.click(screen.getByRole('button',{name:'Show 3 more skills in 1 category'}));
 expect(document.querySelectorAll('.goal-skill-row')).toHaveLength(13);
});
it('shows a planning estimate only when the comparison scored the skill',()=>{
 const outcome={ref:'job:sql',name:'SQL',match_status:'partial' as const,components:[],competence_score:5,score_status:'estimated' as const,score_explanation:'Guided evidence against an intermediate requirement.'};
 render(<LearningFocus skills={[extraction.skills[0],extraction.skills[1]]} matches={{sql:'partial',team:'uncertain'}} outcomes={{sql:outcome}}/>);
 expect(within(skillRow('SQL')).getByText('5')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByText('Unknown')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'SQL'}));
 expect(screen.getByRole('img',{name:'Your competence 5 out of 10 against the level this role needs'})).toBeInTheDocument();
 expect(screen.getByText(/Planning estimate: 5 \/ 10/)).toBeVisible();
 expect(document.querySelector('.goal-skills-summary')).toHaveTextContent('0 ready · 0 getting there · 1 to build · 1 not rated');
});
it('shows an expected level only when the job states one',()=>{
 render(<LearningFocus skills={[{...extraction.skills[0],required_proficiency:'advanced'},extraction.skills[1]]}/>);
 fireEvent.click(screen.getByRole('button',{name:'SQL'}));fireEvent.click(screen.getByRole('button',{name:'Teamwork'}));
 expect(screen.getByText('Advanced level expected')).toBeVisible();
 expect(screen.getAllByText(/level expected/)).toHaveLength(1);
});
it('retains the full title and saved content behind an independent accessible disclosure',()=>{
 const name='Ability to learn quickly, investigate failure modes, and iterate based on evidence and user feedback';
 render(<LearningFocus skills={[{...extraction.skills[0],name,context:'Investigate failed releases.',evidence:'Learn from user feedback.'},extraction.skills[1]]}/>);
 const button=screen.getByRole('button',{name});
 const panel=document.getElementById(button.getAttribute('aria-controls')!)!;
 expect(panel).not.toBeVisible();fireEvent.click(button);
 expect(panel).toBeVisible();expect(panel).toHaveTextContent('Investigate failed releases.');
 expect(panel).not.toHaveTextContent('Learn from user feedback.');
 expect(screen.getByRole('button',{name:'Teamwork'})).toHaveAttribute('aria-expanded','false');
 fireEvent.click(button);expect(panel).not.toBeVisible();
});
it('refreshes automatically when returning to a goal page updated by discovery',async()=>{
 const mounted=render(<CareerSessionProvider><CareerGoalHome/></CareerSessionProvider>);
 await screen.findByRole('heading',{name:'Backend Software Engineer'});
 const changed={...workspace,current:{...workspace.current,selection_version:2,goal:{...workspace.current.goal!,role:'Data Engineer',version:2}}};
 vi.mocked(careerApi).mockImplementation(async(path)=>path==='/workspace'?changed as never:{status:'no_cv',cv_uploaded:false,skills_evaluated:false} as never);
 fireEvent.focus(window);
 expect(await screen.findByRole('heading',{name:'Data Engineer'})).toBeInTheDocument();
 mounted.unmount();
});


it('refreshes a ready goal when Discovery completes in the background',async()=>{
 vi.useFakeTimers();
 render(<CareerSessionProvider><CareerGoalHome/></CareerSessionProvider>);
 await act(async()=>{});
 expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeInTheDocument();
 const changed={...workspace,current:{...workspace.current,selection_version:2,goal:{...workspace.current.goal!,role:'Data Engineer',version:2}}};
 vi.mocked(careerApi).mockImplementation(async(path)=>path==='/workspace'?changed as never:{status:'no_cv',cv_uploaded:false,skills_evaluated:false} as never);
 await act(async()=>{vi.advanceTimersByTime(5000);});
 expect(screen.getByRole('heading',{name:'Data Engineer'})).toBeInTheDocument();
 expect(refreshWorkspace).toHaveBeenCalled();
});
it('hides labels and charts that carry no information',()=>{
 const unspecified=[{...extraction.skills[0],priority:'unspecified' as const},{...extraction.skills[1],priority:'unspecified' as const}];
 const view=render(<LearningFocus skills={unspecified}/>);
 expect(screen.queryByText('Importance not specified')).not.toBeInTheDocument();
 expect(screen.queryByText('Sorted by priority')).not.toBeInTheDocument();
 view.unmount();
 const required=[{...extraction.skills[0],priority:'required' as const},{...extraction.skills[1],priority:'required' as const}];
 overview({...workspace,current:{...workspace.current,goal:{...workspace.current.goal!,skills:required}}});
 expect(screen.queryByRole('figure',{name:/Priority of the/})).not.toBeInTheDocument();
});

it('has no side rail: the skills fill the page and the three goal pages are one tab group',()=>{
 overview();
 expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
 expect(screen.queryByText('Explore other careers')).not.toBeInTheDocument();
 const tabs=screen.getByRole('navigation',{name:'Career goal pages'}).querySelector('.goal-tab-group')!;
 expect(within(tabs as HTMLElement).getAllByRole('link').map(link=>link.textContent)).toEqual(['Skills needed','Interview preparation','About the role']);
});

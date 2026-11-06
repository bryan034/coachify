import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
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
 fireEvent.click(screen.getByText('Eligibility & commitment'));
 expect(screen.getByText('A relevant degree')).toBeVisible();
 expect(screen.getByText('A relevant degree is preferred.')).toBeVisible();
 expect(screen.getByText('2 saved skills')).toBeVisible();
 expect(within(skillRow('SQL')).getByText('Data & analytics')).toBeVisible();expect(within(skillRow('SQL')).getByText('Required')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByText('Communication & leadership')).toBeVisible();expect(within(skillRow('Teamwork')).getByText('Preferred')).toBeVisible();
 expect(screen.getByRole('link',{name:'Refine goal'})).toHaveAttribute('href','/career-goal/chat?refine=1');
 expect(await screen.findByRole('link',{name:/Upload my CV/})).toHaveAttribute('href','/cv');
 fireEvent.click(screen.getByRole('button',{name:/Set a new goal/}));expect(push).toHaveBeenCalledWith('/career-goal?new=1');
 expect(vi.mocked(careerApi).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
it('numbers one list by priority and keeps each number when a category is filtered',()=>{
 overview();
 expect(within(screen.getByRole('heading',{name:'Skills this role needs'}).closest('section')!).getAllByRole('listitem').map(item=>within(item as HTMLElement).getByRole('button').textContent?.match(/^\d+/)?.[0])).toEqual(['1','2']);
 expect(skillRow('SQL').querySelector('.skill-rank')).toHaveTextContent('1');expect(skillRow('Teamwork').querySelector('.skill-rank')).toHaveTextContent('2');
 const filters=screen.getByRole('group',{name:'Filter skills by category'});
 expect(within(filters).getByRole('button',{name:/^All/})).toHaveAttribute('aria-pressed','true');
 fireEvent.click(within(filters).getByRole('button',{name:/Communication & leadership/}));
 expect(screen.queryByRole('button',{name:'SQL'})).not.toBeInTheDocument();
 expect(skillRow('Teamwork').querySelector('.skill-rank')).toHaveTextContent('2');
 fireEvent.click(within(filters).getByRole('button',{name:/^All/}));
 expect(screen.getByRole('button',{name:'SQL'})).toBeVisible();
});
it('marks each needed skill from the saved comparison',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({stale:false,result:{groups:[],job_skill_gaps:[{ref:'job:sql',match_status:'supported'},{ref:'job:team',match_status:'confirmed_shortfall'}]}}))));
 overview();
 expect(await within(skillRow('SQL')).findByText('In your profile')).toBeVisible();
 expect(within(skillRow('Teamwork')).getByText('To build')).toBeVisible();
 expect(screen.getByRole('button',{name:'SQL'})).toHaveAccessibleDescription('In your profile');
 const summary=screen.getByRole('list',{name:'How your saved evidence compares'});
 expect(within(summary).getAllByRole('listitem').map(item=>item.textContent)).toEqual(['1 In your profile','1 To build']);
 expect(screen.queryByText(/Not yet compared/)).not.toBeInTheDocument();
 vi.unstubAllGlobals();
});
it('leaves skills unmarked and explains how to compare when no saved comparison exists',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({stale:false,result:null}))));
 overview();
 expect(await screen.findByText(/Not yet compared with your latest Skills Profile/)).toBeVisible();
 expect(screen.getByRole('link',{name:'Generate a roadmap'})).toHaveAttribute('href','/roadmap');
 expect(screen.queryByText('In your profile')).not.toBeInTheDocument();
 await screen.findByRole('link',{name:/Upload my CV/});
 vi.unstubAllGlobals();
});
it('displays extracted categories while research is still running',async()=>{
 overview({...workspace,phase:'researching',research_id:null});expect(screen.getByText('SQL')).toBeVisible();
 expect(screen.getByText('Researching opportunity information. Your extracted goal is already saved.')).toBeVisible();
 await screen.findByRole('link',{name:/Upload my CV/});
});
it.each([
 {status:'no_cv',heading:'Add your CV background',action:'Upload my CV',description:'No saved CV was found.'},
 {status:'not_evaluated',heading:'CV skills are not available yet',action:'Review my CV',description:'A CV is saved, but no successfully extracted skills were found.'},
])('distinguishes missing CV from saved CV without available skills: $status',async({status,heading,action,description})=>{
 vi.mocked(careerApi).mockResolvedValue({status,cv_uploaded:status!=='no_cv',skills_evaluated:false});overview();
 const card=screen.getByRole('region',{name:'Your CV skills'});
 expect(await within(card).findByRole('heading',{name:heading})).toBeVisible();
 expect(within(card).getByRole('link',{name:new RegExp(action)})).toHaveAttribute('href','/cv');
 expect(card).toHaveTextContent(description);
 expect(card).not.toHaveTextContent(/assessed|assessment|evaluated/iu);
});
it('describes extracted CV skills as available without claiming an assessment was run',async()=>{
 vi.mocked(careerApi).mockResolvedValue({status:'evaluated',cv_uploaded:true,skills_evaluated:true});overview();
 const card=screen.getByRole('region',{name:'Your CV skills'});
 expect(await within(card).findByRole('heading',{name:'CV skills available'})).toBeVisible();
 expect(card).toHaveTextContent('extracted or user-clarified skills available to review');
 expect(within(card).getByRole('link',{name:/View my CV/})).toHaveAttribute('href','/cv');
 expect(card).not.toHaveTextContent(/assessed|assessment|evaluated/iu);
 expect(card).not.toHaveTextContent(/mastered|proven/iu);
});
it('does not mistake unavailable CV data for an empty database and allows retry',async()=>{
 let first=true;vi.mocked(careerApi).mockImplementation(async path=>{if(path==='/context/assessment'){if(first){first=false;throw new Error('Unavailable');}return {status:'evaluated',cv_uploaded:true,skills_evaluated:true} as never;}return {finished:true,categories:{}} as never;});overview();
 expect(await screen.findByRole('heading',{name:'CV skills status unavailable'})).toBeVisible();
 expect(screen.getByRole('region',{name:'Your CV skills'})).toHaveTextContent('We couldn’t check your saved CV.');
 expect(screen.queryByText(/No saved CV was found/)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Retry CV check'}));
 expect(await screen.findByRole('link',{name:/View my CV/})).toHaveAttribute('href','/cv');
 expect(screen.queryByRole('link',{name:/Upload my CV/})).not.toBeInTheDocument();
});
it('restores the overview after reload instead of showing a new input form',async()=>{
 render(<CareerSessionProvider><CareerGoalHome/></CareerSessionProvider>);
 expect(await screen.findByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 expect(screen.queryByRole('textbox',{name:'Job description'})).not.toBeInTheDocument();
 await waitFor(()=>expect(careerApi).toHaveBeenCalledWith('/context/assessment','synthetic-token',expect.anything()));
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
 expect(screen.getByText('SQL or another query language.')).toBeVisible();
 expect(screen.getByText(/Alternative requirement/)).toBeVisible();
 expect(screen.getByRole('link',{name:'example.test ↗'})).toHaveAttribute('href','https://example.test/job');
 expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
 fireEvent.click(screen.getByText('Teamwork'));
 expect(screen.getByText('AI planning suggestion')).toBeVisible();
 expect(screen.getByText('Suggested guidance')).toBeVisible();
 expect(screen.queryByText('A way to practise')).not.toBeInTheDocument();
 await screen.findByRole('link',{name:/Upload my CV/});
});
it('keeps empty goal sections explicit and never labels individual skills as assessed',async()=>{
 vi.mocked(careerApi).mockResolvedValue({status:'evaluated',cv_uploaded:true,skills_evaluated:true});
 overview({...workspace,current:{...workspace.current,goal:{...workspace.current.goal!,skills:[],responsibilities:[],non_skill_requirements:[],summary:null}}});
 expect(screen.getByText(/No skills are listed/)).toBeVisible();
 fireEvent.click(screen.getByText('Eligibility & commitment'));
 expect(screen.getByText(/No non-skill requirements/)).toBeVisible();
 fireEvent.click(screen.getByText('What you would work on'));
 expect(screen.getByText('No responsibilities were saved for this goal.')).toBeVisible();
 const cvSkills=screen.getByRole('region',{name:'Your CV skills'});
 expect(await within(cvSkills).findByRole('heading',{name:'CV skills available'})).toBeVisible();
 expect(cvSkills).toHaveTextContent('These are separate from your goal’s requirements.');
 expect(cvSkills).toHaveTextContent('A comparison against this goal is not available yet.');
 expect(cvSkills).not.toHaveTextContent(/assessed|assessment|evaluated|upload.*planned/iu);
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
 expect(screen.getByText('Suggested guidance')).toBeVisible();
 expect(screen.getByText('Conflicting requirements')).toBeVisible();
 expect(screen.queryByText('Required')).not.toBeInTheDocument();
 expect(screen.queryByText(/Not assessed against/)).not.toBeInTheDocument();
 expect(screen.queryByText(/Evidence in CV|No evidence yet|What to review in your CV/)).not.toBeInTheDocument();
});
it('handles empty and single-skill goals',()=>{
 const {rerender}=render(<LearningFocus skills={[]}/>);
 expect(screen.getByText(/No skills are listed/)).toBeVisible();
 expect(screen.queryByRole('heading',{level:3})).not.toBeInTheDocument();
 rerender(<LearningFocus skills={[extraction.skills[0]]} categories={{SQL:'Data & analytics'}}/>);
 expect(screen.getByText('Data & analytics')).toBeVisible();
 expect(screen.getByRole('button',{name:'SQL'}).querySelector('.skill-rank')).toHaveTextContent('1');
 expect(screen.queryByRole('group',{name:'Filter skills by category'})).not.toBeInTheDocument();
 expect(screen.queryByText('Sorted by priority')).not.toBeInTheDocument();
});
it('sorts one list by priority and filters by the categories the backend sent, with Other last',()=>{
 const skills=[{...extraction.skills[1],name:'Docker',item_id:'docker'},{...extraction.skills[0],name:'Python',item_id:'python'},{...extraction.skills[0],name:'Mystery',item_id:'mystery'}];
 render(<LearningFocus skills={skills} categories={{Docker:'Technical coding',Python:'Technical coding'}}/>);
 const filters=within(screen.getByRole('group',{name:'Filter skills by category'})).getAllByRole('button').map(button=>button.textContent);
 expect(filters).toEqual(['All3','Technical coding2','Other skills1']);
 const names=()=>Array.from(document.querySelectorAll('.skill-rank-row .skill-row-toggle')).map(button=>document.getElementById(button.getAttribute('aria-labelledby')!)!.textContent);
 expect(names()).toEqual(['Python','Mystery','Docker']);
 fireEvent.click(screen.getByRole('button',{name:'Technical coding2'}));
 expect(names()).toEqual(['Python','Docker']);
 fireEvent.click(screen.getByRole('button',{name:'Other skills1'}));
 expect(names()).toEqual(['Mystery']);
});
it('shows an expected level only when the job states one',()=>{
 render(<LearningFocus skills={[{...extraction.skills[0],required_proficiency:'advanced'},extraction.skills[1]]}/>);
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
 expect(panel).toHaveTextContent('Learn from user feedback.');
 expect(screen.getByRole('button',{name:'Teamwork'})).toHaveAttribute('aria-expanded','false');
 fireEvent.click(button);expect(panel).not.toBeVisible();
});
it('uses the confirmed banner only for the exact current goal revision',async()=>{
 const value={goal_id:'goal',goal_version:1,selection_version:1,confirmed:true,context:{id:'goal',version:1,selection_version:1,confirmed:true as const},reason:null};
 vi.mocked(getCvGoalConfirmation).mockResolvedValue(value);
 const {rerender}=overview();
 await waitFor(()=>expect(screen.getByRole('complementary',{name:'Your starting point'})).toHaveClass('briefing-context-banner'));
 expect(screen.getByRole('complementary',{name:'Your starting point'}).compareDocumentPosition(screen.getByRole('heading',{name:'Skills this role needs'}))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 rerender(<CareerSessionProvider><CareerGoalOverview workspace={{...workspace,current:{...workspace.current,goal:{...workspace.current.goal!,version:2}}}} onReload={vi.fn()}/></CareerSessionProvider>);
 await waitFor(()=>expect(screen.getByRole('complementary',{name:'Your starting point'})).not.toHaveClass('briefing-context-banner'));
});
it('updates the layout after the existing explicit confirmation succeeds',async()=>{
 vi.mocked(confirmCvGoal).mockResolvedValue({goal_id:'goal',goal_version:1,selection_version:1,confirmed:true,context:{id:'goal',version:1,selection_version:1,confirmed:true},reason:null});
 overview();const button=screen.getByRole('button',{name:'Confirm this goal for CV review'});
 await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
 await waitFor(()=>expect(screen.getByRole('complementary',{name:'Your starting point'})).toHaveClass('briefing-context-banner'));
 expect(confirmCvGoal).toHaveBeenCalledTimes(1);
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

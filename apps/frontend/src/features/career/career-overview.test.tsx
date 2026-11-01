import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {CareerGoalHome,CareerGoalOverview,LearningFocus} from './career-overview';
import {CareerSessionProvider} from './career-session';
import {getCvGoalConfirmation,confirmCvGoal} from '@/lib/api/career-cv-confirmation';
import {careerApi,type CareerWorkspace} from '@/lib/api/career';
vi.mock('@/lib/api/career-cv-confirmation',()=>({getCvGoalConfirmation:vi.fn(),confirmCvGoal:vi.fn()}));
const push=vi.fn(),params=new URLSearchParams();
vi.mock('next/navigation',()=>({useRouter:()=>({push,replace:vi.fn()}),useSearchParams:()=>params}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn(),importCareer:vi.fn()}));
const extraction={role:'Backend Software Engineer',field:'Software Engineering',company:'Example',location:'Singapore',seniority_level:'Entry level',job_url:null,summary:'Build backend services.',responsibilities:['Build APIs'],skills:[{item_id:'sql',name:'SQL',category:'Technical',priority:'required' as const,origin:'employer' as const},{item_id:'team',name:'Teamwork',category:'Transferable',priority:'preferred' as const,origin:'employer' as const}],non_skill_requirements:[{requirement_id:'degree',category:'Qualifications',description:'A relevant degree',priority:'preferred',evidence:'A relevant degree is preferred.',group_id:null,group_operator:'all' as const}]};
const workspace:CareerWorkspace={session_id:'session',revision:1,kind:'jd',phase:'ready',current:{selection_version:1,goal:{...extraction,_id:'goal',version:1,target_type:'specific_job',interests:[],preferences:[],readiness:'pending',exploration_draft_id:null,exploration_draft_version:null},dependent_results_need_review:false},research_id:'research',research_version:1,coverage:[],error:null,retry_after:null,expires_at:null,exploration_id:null};

function overview(value=workspace){return render(<CareerSessionProvider><CareerGoalOverview workspace={value} onReload={vi.fn()}/></CareerSessionProvider>);}
beforeEach(()=>{vi.resetAllMocks();vi.mocked(getCvGoalConfirmation).mockResolvedValue({goal_id:'goal',goal_version:1,selection_version:1,confirmed:false,context:null,reason:null});params.forEach((_,key)=>params.delete(key));vi.mocked(careerApi).mockImplementation(async(path)=>path==='/workspace'?workspace as never:{status:'no_cv',cv_uploaded:false,skills_evaluated:false} as never);});
it('shows saved skills in briefing accordions and keeps refinement and replacement',async()=>{
 overview();expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Your learning focus'})).toBeVisible();
 expect(screen.getByRole('button',{name:'SQL'})).toHaveAttribute('aria-expanded','false');
 fireEvent.click(screen.getByRole('button',{name:'SQL'}));
 expect(screen.getByRole('button',{name:'SQL'})).toHaveAttribute('aria-expanded','true');
 expect(screen.getByRole('button',{name:'Teamwork'})).toHaveAttribute('aria-expanded','false');
 fireEvent.click(screen.getByText('Eligibility & commitment'));
 expect(screen.getByText('A relevant degree')).toBeVisible();
 expect(screen.getByText('A relevant degree is preferred.')).toBeVisible();
 expect(screen.getByText('2 saved skills')).toBeVisible();
 expect(screen.getByRole('heading',{name:'Required · 1'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Preferred · 1'})).toBeVisible();
 expect(screen.getByRole('link',{name:'Refine goal'})).toHaveAttribute('href','/career-goal/chat?refine=1');
 expect(await screen.findByRole('link',{name:/Upload my CV/})).toHaveAttribute('href','/cv');
 fireEvent.click(screen.getByRole('button',{name:/Set a new goal/}));expect(push).toHaveBeenCalledWith('/career-goal?new=1');
 expect(vi.mocked(careerApi).mock.calls.every(call=>!call[2]?.method)).toBe(true);
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
 expect(screen.getByRole('heading',{name:'Suggested guidance · 1'})).toBeVisible();
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

it('groups without relabelling advisory or unknown importance and hides missing groups',()=>{
 render(<LearningFocus skills={[{...extraction.skills[0],priority:'suggested'},{...extraction.skills[1],priority:'conflicting'}]}/>);
 expect(screen.getByRole('heading',{name:'Suggested guidance · 1'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Conflicting requirements · 1'})).toBeVisible();
 expect(screen.queryByRole('heading',{name:/Required ·/})).not.toBeInTheDocument();
 expect(screen.queryByText(/Not assessed against/)).not.toBeInTheDocument();
 expect(screen.queryByText(/Evidence in CV|No evidence yet|What to review in your CV/)).not.toBeInTheDocument();
});
it('handles empty and single-skill goals without category filters',()=>{
 const {rerender}=render(<LearningFocus skills={[]}/>);
 expect(screen.getByText(/No skills are listed/)).toBeVisible();
 rerender(<LearningFocus skills={[extraction.skills[0]]}/>);
 expect(screen.getByRole('heading',{name:'Required · 1'})).toBeVisible();
 expect(screen.queryByRole('group',{name:'Filter skills by category'})).not.toBeInTheDocument();
});
it('filters a large goal and resets a hidden filter when its data changes',()=>{
 const skills=Array.from({length:30},(_,i)=>({...extraction.skills[i%2],item_id:`skill-${i}`,name:`Skill ${i}`}));
 const {rerender}=render(<LearningFocus skills={skills}/>);
 fireEvent.click(screen.getByRole('button',{name:'Technical'}));
 expect(screen.getByRole('heading',{name:'Required · 15'})).toBeVisible();
 expect(screen.queryByRole('heading',{name:/Preferred ·/})).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Technical'})).toHaveAttribute('aria-pressed','true');
 fireEvent.click(screen.getByRole('button',{name:'All categories'}));
 expect(screen.getByRole('heading',{name:'Preferred · 15'})).toBeVisible();
 rerender(<LearningFocus skills={[extraction.skills[1]]}/>);
 expect(screen.getByRole('button',{name:'Teamwork'})).toBeVisible();
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
 expect(screen.getByRole('complementary',{name:'Your starting point'}).compareDocumentPosition(screen.getByRole('heading',{name:'Your learning focus'}))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

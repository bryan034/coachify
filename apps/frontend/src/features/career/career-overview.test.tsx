import {cleanup,act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CareerGoalHome,CareerGoalOverview,SkillsNeeded,goalSkillLevel} from './career-overview';
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

function overview(value=workspace){return render(<CareerSessionProvider><CareerGoalOverview workspace={value} onReload={vi.fn()}/></CareerSessionProvider>);}
afterEach(()=>vi.useRealTimers());
beforeEach(()=>{vi.resetAllMocks();vi.mocked(refreshWorkspace).mockImplementation(async(_previous,token,signal)=>careerApi('/workspace',token,{signal}));vi.mocked(getCvGoalConfirmation).mockResolvedValue({goal_id:'goal',goal_version:1,selection_version:1,confirmed:false,context:null,reason:null});params.forEach((_,key)=>params.delete(key));vi.mocked(careerApi).mockImplementation(async(path)=>path==='/workspace'?workspace as never:{status:'no_cv',cv_uploaded:false,skills_evaluated:false} as never);});
const serve=(context:object,current:object={})=>vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>new Response(JSON.stringify(init?.method==='POST'?{version:1,operation:{id:'op',status:'pending'}}:String(url).endsWith('/context')?{ready:true,model_available:true,cv_reviewed:true,research_pending:false,goal:{role:'Backend Software Engineer'},...context}:{version:0,ready:true,operation:null,stale:false,result:null,issues:[],...current}),{status:init?.method==='POST'?202:200})));
const outcome=(extra:object={})=>({ref:'job:sql',name:'SQL',match_status:'partial' as const,components:[],...extra});
const sql={...extraction.skills[0],competence_target:{level:8,basis:'job_description' as const,explanation:'Write joins and window queries unaided.',source_urls:[]}};
const row=(name:string)=>screen.getByRole('button',{name:new RegExp(`^${name}`)}).closest('li')!;
it('shows the role header, skills under their category, and keeps refinement and replacement',()=>{
 overview();expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Skills needed'})).toBeVisible();
 expect(screen.getByRole('link',{name:'Refine goal'})).toHaveAttribute('href','/career-goal/chat?refine=1');
 fireEvent.click(screen.getByRole('button',{name:/Set a new goal/}));expect(push).toHaveBeenCalledWith('/career-goal?new=1');
 expect(row('SQL').closest('section')!.querySelector('h3')).toHaveTextContent('Data & analytics');expect(within(row('SQL')).getByText('Essential')).toBeVisible();
 expect(row('Teamwork').closest('section')!.querySelector('h3')).toHaveTextContent('Communication & leadership');expect(within(row('Teamwork')).getByText('Essential')).toBeVisible();
 expect(screen.getByRole('navigation',{name:'How the pages connect'})).toHaveTextContent('Career Goal→Skills Profile→Roadmap');
 expect(vi.mocked(careerApi).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
it('shows goal facts as plain chips, separate from the real actions',()=>{
 overview();
 const meta=screen.getByRole('region',{name:'Your target role'}).querySelector('.ws-meta')!;
 expect(within(meta as HTMLElement).queryByRole('button')).toBeNull();
 expect(meta).toHaveTextContent('Example');expect(meta).toHaveTextContent('Singapore');
});
it('shows each skill’s level against the role target from the saved comparison and filters by it',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({version:0,ready:true,model_available:true,operation:null,stale:false,result:{input_hash:'h',groups:[],job_skill_gaps:[{ref:'job:sql',match_status:'supported',demonstrated_score:9,required_score:8,competence_score:10},{ref:'job:team',match_status:'confirmed_shortfall',demonstrated_score:2,required_score:6,competence_score:3.3}]}}))));
 overview();
 expect(await within(row('SQL')).findByText('9')).toBeVisible();
 expect(within(row('SQL')).getByText('/ 8')).toBeVisible();
 expect(within(row('Teamwork')).getByText('2')).toBeVisible();
 expect(screen.getByRole('button',{name:/1 Ready/})).toBeVisible();expect(screen.getByRole('button',{name:/1 To build/})).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:/1 To build/}));
 expect(screen.queryByRole('button',{name:/^SQL/})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:/^Teamwork/})).toBeVisible();
 vi.unstubAllGlobals();
});
it('offers the evaluation once the goal is set and the Skills Profile is reviewed',async()=>{
 serve({});overview();
 fireEvent.click(await screen.findByRole('button',{name:'Evaluate skills'}));
 expect(screen.getByRole('heading',{name:'Evaluate skills with career goal'})).toBeVisible();
 await waitFor(()=>expect(vi.mocked(fetch).mock.calls.filter(call=>call[1]?.method==='POST')).toHaveLength(1));
 expect(JSON.parse(String(vi.mocked(fetch).mock.calls.find(call=>call[1]?.method==='POST')![1]!.body))).toMatchObject({expected_version:0,allow_partial:true,mutation_id:expect.any(String)});
 vi.unstubAllGlobals();
});
it('hides the banner once a current evaluation exists and asks again when it is stale',async()=>{
 const result={input_hash:'h',groups:[],job_skill_gaps:[{ref:'job:sql',match_status:'supported',demonstrated_score:9,required_score:8,competence_score:10}]};
 serve({input_hash:'h'},{result});const view=overview();
 expect(await within(row('SQL')).findByText('9')).toBeVisible();
 expect(screen.queryByRole('button',{name:'Evaluate skills'})).not.toBeInTheDocument();
 view.unmount();serve({},{result:{...result,input_hash:undefined},stale:true});overview();
 expect(await screen.findByRole('heading',{name:'Your goal or skills changed'})).toBeVisible();
 expect(screen.getByRole('button',{name:'Evaluate again'})).toBeEnabled();
 expect(within(row('SQL')).queryByText('9')).not.toBeInTheDocument();
 vi.unstubAllGlobals();
});
it('asks for the goal to be confirmed in one line and confirms it',async()=>{
 vi.mocked(confirmCvGoal).mockResolvedValue({goal_id:'goal',goal_version:1,selection_version:1,confirmed:true,context:{id:'goal',version:1,selection_version:1,confirmed:true},reason:null});
 overview();
 expect(await screen.findByText('Use this goal in your CV review?')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Confirm goal'}));
 await waitFor(()=>expect(confirmCvGoal).toHaveBeenCalled());
 expect(await screen.findByText('Goal confirmed.')).toBeVisible();
 expect(screen.getByRole('link',{name:'Review CV'})).toHaveAttribute('href','/cv');
});
it('keeps provenance and safe sources, and shows the job’s own words only as evidence the person opens',()=>{
 const goal={...workspace.current.goal!,skills:[{...sql,group_id:'alternatives',group_operator:'any' as const,context:'Maintain relational data.',evidence:'SQL or another query language.',source_urls:['https://example.test/job','javascript:alert(1)']},{...extraction.skills[1],origin:'generated_guidance' as const,priority:'suggested' as const}]};
 overview({...workspace,current:{...workspace.current,goal}});
 fireEvent.click(within(row('SQL')).getByRole('button',{name:/^SQL/}));
 expect(within(row('SQL')).getByText('Why the target is 8 / 10')).toBeVisible();
 expect(within(row('SQL')).getByText(/Write joins and window queries unaided\./)).toBeVisible();
 fireEvent.click(within(row('SQL')).getByRole('button',{name:'See evidence'}));
 expect(screen.getByText('Maintain relational data.')).toBeVisible();
 expect(screen.queryByText('SQL or another query language.')).not.toBeInTheDocument();
 expect(screen.getByText(/Alternative requirement/)).toBeVisible();
 expect(screen.getByRole('link',{name:/example\.test/})).toHaveAttribute('href','https://example.test/job');
 expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
 expect(within(row('Teamwork')).getByText(/Nice to have · inferred by elo/)).toBeInTheDocument();
});
it('handles a goal with no skills',()=>{
 overview({...workspace,current:{...workspace.current,goal:{...workspace.current.goal!,skills:[],responsibilities:[],non_skill_requirements:[],summary:null}}});
 expect(screen.getByText(/No skills are listed/)).toBeVisible();
 expect(screen.queryByRole('button',{name:/1 Ready/})).not.toBeInTheDocument();
});
it('labels advisory or unknown importance without relabelling it as required',()=>{
 render(<SkillsNeeded skills={[{...extraction.skills[0],priority:'suggested'},{...extraction.skills[1],priority:'conflicting'}]}/>);
 expect(within(row('SQL')).getByText('Nice to have')).toBeVisible();
 expect(within(row('Teamwork')).getByText('Conflicting requirements')).toBeVisible();
 expect(screen.queryByText('Essential')).not.toBeInTheDocument();
});
it('groups by the categories the backend sent, most important first, with Other last',()=>{
 const skills=[{...extraction.skills[1],name:'Docker',item_id:'docker',priority:'unspecified' as const},{...extraction.skills[0],name:'Python',item_id:'python'},{...extraction.skills[0],name:'Mystery',item_id:'mystery'}];
 render(<SkillsNeeded skills={skills} categories={{Docker:'Technical coding',Python:'Technical coding'}}/>);
 expect(screen.getAllByRole('heading',{level:3}).map(h=>h.textContent)).toEqual(['Technical coding','Other skills']);
 expect(Array.from(document.querySelectorAll('.ws-sk-name b')).map(node=>node.textContent)).toEqual(['Python','Docker','Mystery']);
});
it('counts skills as ready, getting there, to build or not rated against each target',()=>{
 const skills=['a','b','c','d'].map(id=>({...extraction.skills[0],name:id.toUpperCase(),item_id:id,priority:'required' as const}));
 const levels:Record<string,[number,number]>={a:[8,8],b:[6,8],c:[2,8],d:[0,0]};
 const outcomes=Object.fromEntries(['a','b','c'].map(id=>[id,outcome({ref:`job:${id}`,demonstrated_score:levels[id][0],required_score:levels[id][1]})]));
 render(<SkillsNeeded skills={skills} outcomes={outcomes}/>);
 for(const label of ['4 All','1 Ready','1 Getting there','1 To build','1 Not rated'])expect(screen.getByRole('button',{name:label})).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'1 Not rated'}));
 expect(screen.getByRole('button',{name:/^D/})).toBeVisible();expect(screen.queryByRole('button',{name:/^A/})).not.toBeInTheDocument();
});
it('shows the goal’s target beside a skill that is not rated yet',()=>{
 const target={level:7,basis:'inferred' as const,explanation:'Estimated from the role.',source_urls:[]};
 render(<SkillsNeeded skills={[{...sql,competence_target:target}]}/>);
 expect(row('SQL').querySelector('.ws-score')).toHaveTextContent('Not rated / 7');
});
it('explains a researched target by the employer’s demand, what people report and elo’s reason',()=>{
 const target={level:8,basis:'research' as const,explanation:'Interviews probe SQL hard.',rating_reason:'Interviews probe SQL hard, so elo set 8.',employer_demand:'Write the team’s reporting queries.',
  reported_examples:[{text:'Candidates wrote a window query live.',source_url:'https://www.example.test/post'},{text:'Asked to explain joins.',source_url:'javascript:alert(1)'}],source_urls:[]};
 render(<SkillsNeeded skills={[{...sql,competence_target:target}]}/>);
 fireEvent.click(screen.getByRole('button',{name:/^SQL/}));
 const why=within(row('SQL'));
 expect(why.getByText('Write the team’s reporting queries.')).toBeVisible();
 expect(why.getByText('What people report.')).toBeVisible();
 expect(why.getByRole('link',{name:/example\.test/})).toHaveAttribute('href','https://www.example.test/post');
 expect(why.getByText('Asked to explain joins.')).toBeVisible();
 expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
 expect(why.getByText('Interviews probe SQL hard, so elo set 8.')).toBeVisible();
 expect(why.getByText('From role research')).toBeVisible();
});
it('explains the target and the person’s level when a skill is opened',()=>{
 const skill={...sql,item_id:'sql'};
 const {rerender}=render(<SkillsNeeded skills={[skill]} outcomes={{sql:outcome({demonstrated_score:6,required_score:8,score_explanation:'Wrote reporting queries in one internship.'})}}/>);
 fireEvent.click(screen.getByRole('button',{name:/^SQL/}));
 expect(within(row('SQL')).getByText('Why the target is 8 / 10')).toBeVisible();
 expect(within(row('SQL')).getByText('From the job description')).toBeVisible();
 expect(within(row('SQL')).getByText('Why you’re at 6 / 10')).toBeVisible();
 expect(within(row('SQL')).getByText('Wrote reporting queries in one internship.')).toBeVisible();
 fireEvent.click(within(row('SQL')).getByRole('button',{name:'See evidence'}));
 expect(screen.getAllByText('Wrote reporting queries in one internship.')).toHaveLength(1);
 rerender(<SkillsNeeded skills={[skill]} outcomes={{sql:outcome({demonstrated_score:6,required_score:7})}}/>);
 expect(within(row('SQL')).queryByText(/Why the target/)).not.toBeInTheDocument();
});
it('reads a level from the skill’s own score, or from progress towards the target on older evaluations',()=>{
 expect(goalSkillLevel(sql,outcome({demonstrated_score:6,required_score:7}))).toEqual({level:6,target:7});
 expect(goalSkillLevel(sql,outcome({competence_score:5,required_score:8}))).toEqual({level:4,target:8});
 expect(goalSkillLevel(sql,undefined)).toEqual({level:null,target:8});
 expect(goalSkillLevel(sql,undefined,[{name:' sql ',level:4}])).toEqual({level:4,target:8});
 expect(goalSkillLevel(sql,outcome({demonstrated_score:6,required_score:7}),[{name:sql.name,level:4}])).toEqual({level:6,target:7});
 expect(goalSkillLevel(sql,undefined,[{name:'Python',level:4}])).toEqual({level:null,target:8});
});
it('lists the person’s skills that count towards a goal skill and the smaller skills it breaks down into',()=>{
 const python={...extraction.skills[0],name:'Python',item_id:'python',canonical_skill_id:'python',learning_items:[
  {item_id:'l1',name:'pytest',importance:'high' as const,importance_origin:'inferred' as const,reason:'Tests show reliable code.',source_urls:[]},
  {item_id:'l2',name:'Type hints',importance:'medium' as const,importance_origin:'inferred' as const,reason:'Readable interfaces.',source_urls:[]},
  {item_id:'l3',name:'SQL',importance:'low' as const,importance_origin:'inferred' as const,reason:'Repeats a goal skill.',source_urls:[]}]};
 const outcomes={python:outcome({ref:'job:python',name:'Python',profile_skills:[{name:'Pandas',competence_score:6,required_score:8}]})};
 render(<SkillsNeeded skills={[python,sql]} outcomes={outcomes} profileSkills={[{name:'Python',canonicalId:'python',level:5},{name:'Pandas',level:null},{name:'pytest',level:null},{name:'Docker',level:3}]}/>);
 const counted=screen.getByRole('list',{name:'Your skills that count towards Python'});
 expect(within(counted).getAllByRole('listitem').map(item=>item.textContent)).toEqual(['Python5/10','Pandas6/10','pytest']);
 const parts=screen.getByRole('list',{name:'Python breaks down into'});
 expect(within(parts).getAllByRole('listitem').map(item=>item.textContent)).toEqual(['In your skills: pytest','Type hints']);
 expect(screen.queryByRole('list',{name:/towards SQL/})).not.toBeInTheDocument();
});
it('opens Talk it through for a skill and explains its target',()=>{
 render(<CareerSessionProvider><SkillsNeeded skills={[sql]} talk={vi.fn()}/></CareerSessionProvider>);
 fireEvent.click(screen.getByRole('button',{name:/^SQL/}));
 expect(screen.getByRole('button',{name:'Rate this skill'})).toBeVisible();
 expect(screen.getByText(/hasn’t been compared with your Skills Profile yet/)).toBeVisible();
 expect(screen.getByRole('button',{name:'See evidence'})).toHaveAttribute('aria-expanded','false');
});
it('opens the drawer from a skill row on the Career Goal page',async()=>{
 overview();
 fireEvent.click(row('SQL').querySelector('button')!);
 fireEvent.click(within(row('SQL')).getByRole('button',{name:'Rate this skill'}));
 const dialog=await screen.findByRole('dialog',{name:'SQL'});
 expect(within(dialog).getByText('Without clear evidence, elo assumes you had guidance.')).toBeVisible();
 fireEvent.click(within(dialog).getByRole('button',{name:'Close chat'}));
 await waitFor(()=>expect(screen.queryByRole('dialog',{name:'SQL'})).not.toBeInTheDocument());
});
it('links the three goal pages as tabs and keeps eligibility on About the role',async()=>{
 overview();
 const tabs=screen.getByRole('navigation',{name:'Career goal pages'});
 expect(within(tabs).getAllByRole('link').map(link=>[link.textContent,link.getAttribute('href')])).toEqual([['Skills needed','/career-goal'],['Interview preparation','/career-goal/interview'],['About the role','/career-goal/role']]);
 expect(within(tabs).getByRole('link',{name:'Skills needed'})).toHaveAttribute('aria-current','page');
 cleanup();
 render(<CareerSessionProvider><CareerGoalOverview view="role" workspace={workspace} onReload={vi.fn()}/></CareerSessionProvider>);
 expect(within(screen.getByRole('navigation',{name:'Career goal pages'})).getByRole('link',{name:'About the role'})).toHaveAttribute('aria-current','page');
 expect(screen.queryByRole('heading',{name:'Skills needed'})).not.toBeInTheDocument();
 expect(within(screen.getByRole('region',{name:'Who can apply'})).getByText('A relevant degree')).toBeVisible();
 expect(screen.getByRole('heading',{name:'About the role'})).toBeInTheDocument();
});
it('displays extracted categories while research is still running',async()=>{
 overview({...workspace,phase:'researching',research_id:null});expect(screen.getByText('SQL')).toBeVisible();
 expect(screen.getByRole('progressbar',{name:'Working out the skills needed'})).toHaveAttribute('aria-valuenow','63');
 expect(screen.getByText('Checking interviews and similar roles')).toBeVisible();
 expect(screen.getByText(/You can leave this page\. elo keeps working/)).toBeVisible();
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

it('retries a failed research job without replacing the saved goal',async()=>{
 const reload=vi.fn();
 render(<CareerSessionProvider><CareerGoalOverview workspace={{...workspace,phase:'research_failed'}} onReload={reload}/></CareerSessionProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Retry research'}));
 await waitFor(()=>expect(careerApi).toHaveBeenCalledWith('/workspace/retry','synthetic-token',{method:'POST'}));
 await waitFor(()=>expect(reload).toHaveBeenCalledOnce());
 expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
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

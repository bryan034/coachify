import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {CareerGoalHome,CareerGoalOverview} from './career-overview';
import {CareerSessionProvider} from './career-session';
import {careerApi,type CareerWorkspace} from '@/lib/api/career';
const push=vi.fn(),params=new URLSearchParams();
vi.mock('next/navigation',()=>({useRouter:()=>({push,replace:vi.fn()}),useSearchParams:()=>params}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn(),importCareer:vi.fn()}));
const extraction={role:'Backend Software Engineer',field:'Software Engineering',company:'Example',location:'Singapore',seniority_level:'Entry level',job_url:null,summary:'Build backend services.',responsibilities:['Build APIs'],skills:[{item_id:'sql',name:'SQL',category:'Technical',priority:'required' as const,origin:'employer' as const},{item_id:'team',name:'Teamwork',category:'Transferable',priority:'preferred' as const,origin:'employer' as const}],non_skill_requirements:[{requirement_id:'degree',category:'Qualifications',description:'A relevant degree',priority:'preferred',evidence:'A relevant degree is preferred.',group_id:null,group_operator:'all' as const}]};
const workspace:CareerWorkspace={session_id:'session',revision:1,kind:'jd',phase:'ready',review:{review_id:'review',version:1,target_type:'specific_job',extraction,baseline:extraction,metadata_origins:{},requirements_need_review:false,is_confirmed:false,generation:{}},current:{selection_version:1,goal:null,dependent_results_need_review:false},research:{_id:'research',version:1,last_researched_at:'2026-10-26T00:00:00Z',research_status:'no_findings',skills:[],sources:[]},coverage:[],error:null,retry_after:null,expires_at:null,exploration_id:null};
function overview(value=workspace){return render(<CareerSessionProvider><CareerGoalOverview workspace={value} onReload={vi.fn()}/></CareerSessionProvider>);}
beforeEach(()=>{vi.resetAllMocks();params.forEach((_,key)=>params.delete(key));vi.mocked(careerApi).mockImplementation(async(path)=>path==='/workspace'?workspace as never:{status:'no_cv',cv_uploaded:false,skills_evaluated:false} as never);});
it('shows every saved item in its own category card and offers guided refinement and replacement',async()=>{
 overview();expect(screen.getByRole('heading',{name:'Backend Software Engineer'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Technical skills'}).closest('article')).toHaveTextContent('SQL');
 expect(screen.getByRole('heading',{name:'Transferable skills'}).closest('article')).toHaveTextContent('Teamwork');
 expect(screen.getByRole('heading',{name:'Qualifications'}).closest('article')).toHaveTextContent('A relevant degree');
 expect(screen.getByRole('link',{name:'Refine goal'})).toHaveAttribute('href','/career-goal/chat?refine=1');
 expect(await screen.findByRole('link',{name:/Assess my skills/})).toHaveAttribute('href','/cv');
 fireEvent.click(screen.getByRole('button',{name:/Set a new goal/}));expect(push).toHaveBeenCalledWith('/career-goal?new=1');
 expect(vi.mocked(careerApi).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
it('displays extracted categories while research is still running',async()=>{
 overview({...workspace,phase:'researching',research:null});expect(screen.getByText('SQL')).toBeVisible();
 expect(screen.getByRole('status')).toHaveTextContent('Researching interview expectations');
 await screen.findByRole('link',{name:/Assess my skills/});
});
it.each(['no_cv','not_evaluated'])('routes missing or unevaluated capabilities to CV upload: %s',async(status)=>{
 vi.mocked(careerApi).mockResolvedValue({status,cv_uploaded:status!=='no_cv',skills_evaluated:false});overview();
 expect(await screen.findByRole('link',{name:/Assess my skills/})).toHaveAttribute('href','/cv');
 expect(screen.queryByText('Your assessed skills are saved')).not.toBeInTheDocument();
});
it('does not mistake unavailable CV data for an empty database and allows retry',async()=>{
 vi.mocked(careerApi).mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce({status:'evaluated',cv_uploaded:true,skills_evaluated:true});overview();
 fireEvent.click(await screen.findByRole('button',{name:'Retry skill check'}));
 expect(await screen.findByRole('link',{name:/View my CV/})).toHaveAttribute('href','/cv');
 expect(screen.queryByRole('link',{name:/Assess my skills/})).not.toBeInTheDocument();
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

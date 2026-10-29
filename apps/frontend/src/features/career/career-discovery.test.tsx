import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {CareerDiscovery} from './career-discovery';
import {careerApi} from '@/lib/api/career';
const push=vi.fn();
vi.mock('next/navigation',()=>({useRouter:()=>({push})}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const scope={field:'Software Engineering',area:'Software Engineering',specificity:'field',career_stage:'entry_level',location:'Singapore'};
const decision={scope,reply:'You can keep Software Engineering broad.',action:'CONFIRM_AREA',question:null,recommendations:[]};
const extraction={role:'Software Engineering',field:'Software Engineering',company:null,job_url:null,location:'Singapore',seniority_level:'entry_level',employment_type:'unknown',summary:'A sample of real job requirements.',responsibilities:['Build APIs'],non_skill_requirements:[],skills:[{item_id:'sql',name:'SQL',category:'technical',priority:'required',origin:'market_research',evidence:'SQL required.'},{item_id:'py',name:'Python',category:'technical',priority:'preferred',origin:'market_research',evidence:'Python preferred.'}]};
const base={id:'000000000000000000000001',version:2,status:'conversation',stage:null,decision,scope,related_roles:[],sources:[],stats:[],warnings:[],listings_analysed:0,employers_analysed:0,coverage:null,error_code:null,limit_scope:null,provider:null,retry_after:null,review:null};
beforeEach(()=>{vi.clearAllMocks();});
it('opens a chat and automatically researches a clear direction without scope confirmation',async()=>{
 vi.mocked(careerApi).mockImplementation(async path=>{
  if(path==='/discoveries/current')return {available:true,session:null} as never;
  if(path==='/discoveries')return {available:true,session:{...base,version:1,decision:null}} as never;
  return {available:true,session:{...base,version:3,status:'researching',stage:'plan_research',messages:[{role:'user',content:'Software engineering, keep it broad'},{role:'assistant',content:'Researching Software Engineering.'}]}} as never;
 });
 render(<CareerDiscovery/>);await waitFor(()=>expect(screen.queryByText('Opening your saved discovery…')).toBeNull());
 expect(screen.getByRole('log',{name:'Career agent conversation'})).toBeInTheDocument();
 expect(screen.queryByLabelText(/CV attachment/i)).toBeNull();
 fireEvent.click(screen.getByRole('checkbox'));
 fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'Software engineering, keep it broad'}});
 fireEvent.click(screen.getByRole('button',{name:'Send message'}));
 expect(screen.getByRole('textbox',{name:'Message Coachify'})).toHaveValue('');
 await screen.findByText('Planning job-listing searches');
 expect(screen.queryByRole('button',{name:'Confirm area and research jobs'})).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path.endsWith('/research')||path==='/goals/confirm')).toBe(false);
 expect(screen.getByRole('textbox',{name:'Message Coachify'})).toBeEnabled();
});
it('clears immediately and preserves a new draft typed while a response is pending',async()=>{
 let respond!:(value:unknown)=>void;
 vi.mocked(careerApi).mockImplementation(async path=>{
  if(path==='/discoveries/current')return {available:true,session:{...base,status:'researching'}} as never;
  return await new Promise<unknown>(resolve=>{respond=resolve;}) as never;
 });
 render(<CareerDiscovery/>);await screen.findByText('Researching your career area');
 fireEvent.click(screen.getByRole('checkbox'));
 const input=screen.getByRole('textbox',{name:'Message Coachify'});
 fireEvent.change(input,{target:{value:'I prefer backend work'}});
 fireEvent.keyDown(input,{key:'Enter'});
 expect(input).toHaveValue('');expect(input).toBeEnabled();
 fireEvent.change(input,{target:{value:'What does that involve?'}});
 await act(async()=>respond({available:true,session:{...base,version:3,status:'researching',messages:[{role:'user',content:'I prefer backend work'},{role:'assistant',content:'I will keep that preference in mind.'}]}}));
 expect(input).toHaveValue('What does that involve?');
 expect(screen.getByRole('log')).toHaveTextContent('I prefer backend work');
});
it('retains a failed message for retry without overwriting the next draft',async()=>{
 let reject!:(error:Error)=>void;
 vi.mocked(careerApi).mockImplementation(async path=>{
  if(path==='/discoveries/current')return {available:true,session:base} as never;
  return await new Promise<unknown>((_resolve,no)=>{reject=no;}) as never;
 });
 render(<CareerDiscovery/>);await screen.findByText(decision.reply);
 fireEvent.click(screen.getByRole('checkbox'));
 const input=screen.getByRole('textbox',{name:'Message Coachify'});
 fireEvent.change(input,{target:{value:'Explore backend work'}});
 fireEvent.click(screen.getByRole('button',{name:'Send message'}));
 fireEvent.change(input,{target:{value:'My next draft'}});
 await act(async()=>reject(new Error('Synthetic connection failure')));
 expect(screen.getByRole('alert')).toHaveTextContent('Message not sent: Explore backend work');
 expect(screen.getByRole('button',{name:'Retry message'})).toBeEnabled();
 expect(input).toHaveValue('My next draft');
});
it('reviews categorized evidence, removes a skill, then uses the existing goal confirmation API',async()=>{
 const review={current:{goal:{...extraction,_id:'000000000000000000000081',version:1,target_type:'career_exploration'}}};
 const session={...base,status:'review',review,related_roles:['Software Engineer'],listings_analysed:10,employers_analysed:5,coverage:'good',stats:[{name:'SQL',requirement_type:'core',mention_count:8,sample_size:10,source_ids:[]},{name:'Python',requirement_type:'optional',mention_count:3,sample_size:10,source_ids:[]}]};
 vi.mocked(careerApi).mockImplementation(async (path,_token,options)=>{
  if(path==='/discoveries/current')return {available:true,session} as never;
  if(path.endsWith('/review'))return {current:{goal:{...review.current.goal,version:2,...JSON.parse(options!.body as string).content}}} as never;
  if(path==='/goals/current')return {selection_version:0,goal:null} as never;
  if(path==='/goals/confirm')return {selection_version:1,goal:{_id:'goal'}} as never;
  throw new Error(path);
 });
 render(<CareerDiscovery/>);await screen.findByRole('heading',{name:'Review your career target'});
 for(const title of ['Core skills','Specialisation-specific skills','Optional skills'])expect(screen.getByRole('heading',{name:title})).toBeInTheDocument();
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path==='/goals/confirm')).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Remove Python'}));
 fireEvent.click(screen.getByRole('checkbox',{name:/I have reviewed this target/}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm and save goal'}));
 await waitFor(()=>expect(push).toHaveBeenCalledWith('/career-goal'));
 const saved=vi.mocked(careerApi).mock.calls.find(([path])=>path.endsWith('/review'))!;
 expect(JSON.parse(saved[2]!.body as string).content.skills.map((s:{name:string})=>s.name)).toEqual(['SQL']);
 const confirm=vi.mocked(careerApi).mock.calls.find(([path])=>path==='/goals/confirm')!;
 expect(JSON.parse(confirm[2]!.body as string)).toMatchObject({target_type:'career_exploration',review_id:review.current.goal._id,expected_review_version:2,company:null,job_url:null});
});
it('restores provider wait with its cause while keeping saved evidence visible',async()=>{
 vi.mocked(careerApi).mockResolvedValue({available:true,session:{...base,status:'waiting',retry_after:407,limit_scope:'provider',provider:'gemini'}} as never);
 render(<CareerDiscovery/>);
 await screen.findByText('gemini is rate limiting requests');
 expect(screen.getByRole('status')).toHaveTextContent('Resuming in 407 seconds');
 expect(screen.queryByRole('button',{name:'Confirm and save goal'})).toBeNull();
});

it('shows all five suggested career directions',async()=>{
 const recommendations=Array.from({length:5},(_,index)=>({area:`Career area ${index+1}`,explanation:'A direction matching your interests.',typical_work:'Representative responsibilities.',difference:'A different kind of work.'}));
 vi.mocked(careerApi).mockResolvedValue({available:true,session:{...base,decision:{...decision,action:'SUGGEST_ROLES',scope:null,recommendations}}} as never);
 render(<CareerDiscovery/>);
 for(const recommendation of recommendations){
  expect(await screen.findByRole('heading',{name:recommendation.area})).toBeInTheDocument();
  expect(screen.getByRole('button',{name:`Choose ${recommendation.area}`})).toBeInTheDocument();
 }
});

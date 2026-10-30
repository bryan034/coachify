import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {CareerDiscovery} from './career-discovery';
import {careerApi} from '@/lib/api/career';
const push=vi.fn();
vi.mock('next/navigation',()=>({useRouter:()=>({push})}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const introduction='Welcome to Career Discovery. Tell me a field, role or work you enjoy.';
const scope={field:'Software Engineering',area:'Software Engineering',specificity:'field',career_stage:'entry_level',location:'Singapore'};
const decision={scope,reply:'You can keep Software Engineering broad.',action:'START_RESEARCH',question:null,recommendations:[]};
const extraction={role:'Software Engineering',field:'Software Engineering',company:null,job_url:null,location:'Singapore',seniority_level:'entry_level',employment_type:'unknown',summary:'A sample of real job requirements.',responsibilities:['Build APIs'],non_skill_requirements:[],skills:[{item_id:'sql',name:'SQL',category:'technical',priority:'required',origin:'market_research',evidence:'SQL required.'},{item_id:'py',name:'Python',category:'technical',priority:'preferred',origin:'market_research',evidence:'Python preferred.'}]};
const base={id:'000000000000000000000001',version:2,status:'conversation',stage:null,decision,scope,related_roles:[],sources:[],stats:[],warnings:[],listings_analysed:0,employers_analysed:0,coverage:null,error_code:null,limit_scope:null,provider:null,retry_after:null,review:null};
const empty={...base,version:1,decision:null,scope:null,messages:[]};
function configure(handler:(path:string,options?:RequestInit)=>unknown){
 vi.mocked(careerApi).mockImplementation(async(path,_token,options)=>{
  if(path==='/discoveries/current?fresh=true')return {available:true,session:null,introduction} as never;
  if(path==='/discoveries')return {available:true,session:empty} as never;
  return await handler(path,options) as never;
 });
}
async function open(){render(<CareerDiscovery/>);await screen.findByText(introduction);}
function send(message='Software engineering, keep it broad'){
 const consent=screen.getByRole('checkbox',{name:/Allow elo/});
 if(!(consent as HTMLInputElement).checked)fireEvent.click(consent);
 fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:message}});
 fireEvent.click(screen.getByRole('button',{name:'Send message'}));
}
beforeEach(()=>{vi.clearAllMocks();});

it('renders bundled clarification as questions without the repeated preface',async()=>{
 const questions=[
  'Which field and, if possible, specific role would you like to explore? You can keep it broad.',
  'What interests you about this field? You can say unsure.',
  'What other interests do you have, related or unrelated to this field? You can say unsure.',
  'What activities do you strongly want to avoid? You can say unsure.',
  'What career stage are you looking for: internship, starting out, or experienced? You can say unsure.',
  'What work preferences or constraints matter to you? You can say unsure.',
 ];
 const bundle=questions.map((question,index)=>`${index+1}. ${question}`).join('\n');
 configure(()=>({available:true,session:{...base,decision:{...decision,action:'ASK_CLARIFICATION'},messages:[{role:'user',content:'Help me explore careers'},{role:'assistant',content:bundle}]}}));
 await open();send('Help me explore careers');
 await screen.findByText(questions[0]);
 expect(within(screen.getByRole('log')).getAllByRole('listitem')).toHaveLength(6);
 expect(screen.queryByText(/Let’s clarify the remaining context/)).toBeNull();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path.endsWith('/research'))).toBe(false);
});

it('opens with only the Python-supplied introduction and makes no mutation requests',async()=>{
 vi.mocked(careerApi).mockResolvedValue({available:true,introduction,session:{...base,messages:[{role:'user',content:'Old private interests'}]}} as never);
 await open();
 expect(screen.getByRole('log').querySelectorAll('.agent-message')).toHaveLength(1);
 expect(screen.queryByText('Old private interests')).toBeNull();
 expect(screen.queryByText(decision.reply)).toBeNull();
 expect(vi.mocked(careerApi).mock.calls).toHaveLength(1);
 expect(vi.mocked(careerApi).mock.calls[0][0]).toBe('/discoveries/current?fresh=true');
});

it('starts a session and automatic research only after the user sends a message',async()=>{
 configure(()=>({available:true,session:{...base,status:'researching',stage:'plan_research',messages:[...empty.messages,{role:'user',content:'Software engineering, keep it broad'},{role:'assistant',content:'Researching Software Engineering.'}]}}));
 await open();send();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 await screen.findByText('Planning job-listing searches');
 expect(screen.getAllByText(introduction)).toHaveLength(1);
 expect(screen.queryByRole('button',{name:'Confirm area and research jobs'})).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path.endsWith('/research')||path==='/goals/confirm')).toBe(false);
 expect(screen.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
});

it('clears immediately and preserves a new draft typed while a response is pending',async()=>{
 let respond!:(value:unknown)=>void;
 configure(()=>new Promise<unknown>(resolve=>{respond=resolve;}));
 await open();send('I prefer backend work');
 const input=screen.getByRole('textbox',{name:'Message elo'});
 expect(input).toHaveValue('');expect(input).toBeEnabled();
 fireEvent.change(input,{target:{value:'What does that involve?'}});
 await waitFor(()=>expect(respond).toBeTypeOf('function'));
 await act(async()=>respond({available:true,introduction,session:{...base,status:'researching',messages:[...empty.messages,{role:'user',content:'I prefer backend work'},{role:'assistant',content:'I will keep that preference in mind.'}]}}));
 expect(input).toHaveValue('What does that involve?');
 expect(screen.getByRole('log')).toHaveTextContent('I prefer backend work');
});

it('retains a failed message for retry without overwriting the next draft',async()=>{
 let reject!:(error:Error)=>void;
 configure(()=>new Promise<unknown>((_resolve,no)=>{reject=no;}));
 await open();send('Explore backend work');
 const input=screen.getByRole('textbox',{name:'Message elo'});
 fireEvent.change(input,{target:{value:'My next draft'}});
 await waitFor(()=>expect(reject).toBeTypeOf('function'));
 await act(async()=>reject(new Error('Synthetic connection failure')));
 expect(screen.getByRole('alert')).toHaveTextContent('Message not sent: Explore backend work');
 expect(screen.getByRole('button',{name:'Retry message'})).toBeEnabled();
 expect(input).toHaveValue('My next draft');
});

it('reviews evidence, removes a skill, then uses the existing goal confirmation API',async()=>{
 const review={current:{goal:{...extraction,_id:'000000000000000000000081',version:1,target_type:'career_exploration'}}};
 const session={...base,status:'review',review,related_roles:['Software Engineer'],listings_analysed:10,employers_analysed:5,coverage:'good',stats:[{name:'SQL',requirement_type:'core',mention_count:8,sample_size:10,source_ids:[]},{name:'Python',requirement_type:'optional',mention_count:3,sample_size:10,source_ids:[]}]};
 configure((path,options)=>{
  if(path.endsWith('/messages'))return {available:true,session,introduction};
  if(path.endsWith('/review'))return {current:{goal:{...review.current.goal,version:2,...JSON.parse(options!.body as string).content}}};
  if(path==='/goals/current')return {selection_version:0,goal:null};
  if(path==='/goals/confirm')return {selection_version:1,goal:{_id:'goal'}};
  throw new Error(path);
 });
 await open();send();await screen.findByRole('heading',{name:'Review your career target'});
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

it('shows provider waits after sending without hiding the composer',async()=>{
 configure(()=>({available:true,introduction,session:{...base,status:'waiting',retry_after:407,limit_scope:'provider',provider:'gemini'}}));
 await open();send();await screen.findByText('gemini is rate limiting requests');
 expect(screen.getByRole('status')).toHaveTextContent('Resuming in 407 seconds');
 expect(screen.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
 expect(screen.queryByRole('button',{name:'Confirm and save goal'})).toBeNull();
});

it('shows all five suggested career directions',async()=>{
 const recommendations=Array.from({length:5},(_,index)=>({area:`Career area ${index+1}`,explanation:'A direction matching your interests.',typical_work:'Representative responsibilities.',difference:'A different kind of work.'}));
 configure(()=>({available:true,introduction,session:{...base,decision:{...decision,action:'SUGGEST_ROLES',scope:null,recommendations}}}));
 await open();send('I am unsure');
 for(const recommendation of recommendations){
  expect(await screen.findByRole('heading',{name:recommendation.area})).toBeInTheDocument();
  expect(screen.getByRole('button',{name:`Choose ${recommendation.area}`})).toBeInTheDocument();
 }
});

it('New chat clears history, recommendations, scope and the draft without posting',async()=>{
 configure(()=>({available:true,introduction,session:{...base,messages:[...empty.messages,{role:'user',content:'My old direction'},{role:'assistant',content:'Earlier advice'}]}}));
 await open();send('My old direction');await screen.findByText('Earlier advice');
 fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'Unsent draft'}});
 const posts=vi.mocked(careerApi).mock.calls.filter(([, ,options])=>options?.method==='POST').length;
 fireEvent.click(screen.getByRole('button',{name:'New chat'}));await screen.findByText(introduction);
 expect(screen.getByRole('log').querySelectorAll('.agent-message')).toHaveLength(1);
 expect(screen.queryByText('Earlier advice')).toBeNull();expect(screen.queryByText('My old direction')).toBeNull();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 expect(screen.getByRole('checkbox',{name:/Allow elo/})).not.toBeChecked();
 expect(vi.mocked(careerApi).mock.calls.filter(([, ,options])=>options?.method==='POST')).toHaveLength(posts);
});

it('reopening the page starts fresh instead of resuming the last conversation',async()=>{
 configure(()=>({available:true,introduction,session:{...base,messages:[{role:'assistant',content:'Previous answer'}]}}));
 const mounted=render(<CareerDiscovery/>);await screen.findByText(introduction);send();await screen.findByText('Previous answer');
 mounted.unmount();await open();
 expect(screen.queryByText('Previous answer')).toBeNull();
 expect(screen.getByRole('log').querySelectorAll('.agent-message')).toHaveLength(1);
});

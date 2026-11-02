import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CareerDiscovery} from './career-discovery';
import {careerApi} from '@/lib/api/career';
const push=vi.fn();
const profileState=vi.hoisted(()=>({token:'synthetic'}));
vi.mock('next/navigation',()=>({useRouter:()=>({push})}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>profileState}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const introduction='Welcome to Career Discovery. Tell me a field, role or work you enjoy.';
const scope={field:'Software Engineering',area:'Software Engineering',specificity:'field',career_stage:'entry_level',location:'Singapore'};
const decision={scope,reply:'You can keep Software Engineering broad.',action:'START_RESEARCH',question:null,recommendations:[]};
const extraction={role:'Software Engineering',field:'Software Engineering',company:null,job_url:null,location:'Singapore',seniority_level:'entry_level',employment_type:'unknown',summary:'A sample of real job requirements.',responsibilities:['Build APIs'],non_skill_requirements:[],skills:[{item_id:'sql',name:'SQL',category:'technical',priority:'required',origin:'market_research',evidence:'SQL required.'},{item_id:'py',name:'Python',category:'technical',priority:'preferred',origin:'market_research',evidence:'Python preferred.'}]};
const base={id:'000000000000000000000001',version:2,status:'conversation',stage:null,decision,scope,related_roles:[],sources:[],stats:[],warnings:[],listings_analysed:0,employers_analysed:0,coverage:null,error_code:null,limit_scope:null,provider:null,retry_after:null,review:null};
const empty={...base,version:1,decision:null,scope:null,messages:[]};
function configure(handler:(path:string,options?:RequestInit)=>unknown){
 let starts=0;
 vi.mocked(careerApi).mockImplementation(async(path,_token,options)=>{
  if(path==='/discoveries/current')return {available:true,session:null,introduction} as never;
  if(path==='/discoveries')return {available:true,session:{...empty,id:String(++starts).padStart(24,'0')},introduction} as never;
  return await handler(path,options) as never;
 });
}
async function open(){render(<CareerDiscovery/>);await screen.findByText(introduction);}
function send(message='Software engineering, keep it broad'){
 fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:message}});
 fireEvent.click(screen.getByRole('button',{name:'Send message'}));
}
beforeEach(()=>{vi.clearAllMocks();profileState.token='synthetic';});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

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
 await screen.findByRole('button',{name:'Show full response'});
 await waitFor(()=>expect(screen.getByRole('log')).toHaveTextContent('Which field'));
 fireEvent.click(screen.getByRole('button',{name:'Show full response'}));
 expect(screen.getByText(questions[0])).toBeInTheDocument();
 expect(within(screen.getByRole('log')).getAllByRole('listitem')).toHaveLength(6);
 expect(screen.queryByText(/Let’s clarify the remaining context/)).toBeNull();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path.endsWith('/research'))).toBe(false);
});

it('opens an empty account with the Python introduction and makes no mutation requests',async()=>{
 configure(()=>{throw new Error('Unexpected request');});
 await open();
 expect(screen.getByRole('log').querySelectorAll('.agent-message')).toHaveLength(1);
 expect(screen.queryByText(decision.reply)).toBeNull();
 expect(vi.mocked(careerApi).mock.calls).toHaveLength(1);
 expect(vi.mocked(careerApi).mock.calls[0][0]).toBe('/discoveries/current');
});

it('starts a session and automatic research only after the user sends a message',async()=>{
 configure(()=>({available:true,session:{...base,status:'researching',stage:'plan_research',messages:[...empty.messages,{role:'user',content:'Software engineering, keep it broad'},{role:'assistant',content:'Researching Software Engineering.'}]}}));
 await open();
 expect(screen.queryByRole('checkbox',{name:/Allow elo/})).toBeNull();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
 send();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 await screen.findByText('Planning job-listing searches');
 const start=vi.mocked(careerApi).mock.calls.find(([path])=>path==='/discoveries')!;
 expect(JSON.parse(start[2]!.body as string)).toEqual({consent:true});
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

it('keeps edits in chat and never requires a save or confirmation request',async()=>{
 const review={current:{goal:{...extraction,_id:'000000000000000000000081',version:1,target_type:'career_exploration'}}};
 let edited=false;
 configure((path,options)=>{
  if(path.endsWith('/messages')){
   const message=JSON.parse(options!.body as string).message;edited=message==='Remove Python';
   return {available:true,session:{...base,status:'review',version:edited?3:2,review,
    messages:[{role:'user',content:message},{role:'assistant',content:edited?'Python has been removed from your career goal.':'Your career goal has been updated.'}]}};
  }
  throw new Error(path);
 });
 await open();send();await screen.findByRole('button',{name:'Show full response'});
 fireEvent.click(screen.getByRole('button',{name:'Show full response'}));
 expect(screen.getByText('Your career goal has been updated.')).toBeInTheDocument();
 expect(screen.queryByRole('heading',{name:'Review your career target'})).toBeNull();
 expect(screen.queryByRole('button',{name:'Confirm and save goal'})).toBeNull();
 expect(screen.queryByRole('textbox',{name:'Career title'})).toBeNull();
 send('Remove Python');
 await screen.findByRole('button',{name:'Show full response'});
 fireEvent.click(screen.getByRole('button',{name:'Show full response'}));
 expect(screen.getByText('Python has been removed from your career goal.')).toBeInTheDocument();
 expect(edited).toBe(true);
 expect(vi.mocked(careerApi).mock.calls.every(([path])=>path.startsWith('/discoveries'))).toBe(true);
 expect(push).not.toHaveBeenCalled();
});

it('renders summary headings and a bold final invitation inside the conversation',async()=>{
 const closing='You can ask questions and refine your career goal through this chat.';
 vi.mocked(careerApi).mockResolvedValue({available:true,session:{...base,messages:[{role:'assistant',content:`## Your career direction\n\n**Software Engineering**\n\n### Recommended skills\n\n- **SQL** — high learning priority.\n\n**${closing}**`}]}} as never);
 render(<CareerDiscovery/>);
 expect(await screen.findByRole('heading',{name:'Your career direction'})).toBeInTheDocument();
 expect(screen.getByRole('heading',{name:'Recommended skills'})).toBeInTheDocument();
 expect(screen.getByText(closing).tagName).toBe('STRONG');
 expect(screen.getByRole('listitem')).toHaveTextContent('SQL');
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

it('New chat persists an empty session and clears history, recommendations, scope and the draft',async()=>{
 configure(()=>({available:true,introduction,session:{...base,messages:[...empty.messages,{role:'user',content:'My old direction'},{role:'assistant',content:'Earlier advice'}]}}));
 await open();send('My old direction');await screen.findByText('Earlier advice');
 fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'Unsent draft'}});
 const posts=vi.mocked(careerApi).mock.calls.filter(([, ,options])=>options?.method==='POST').length;
 fireEvent.click(screen.getByRole('button',{name:'New chat'}));await waitFor(()=>expect(screen.queryByText('Earlier advice')).toBeNull());
 expect(screen.getByRole('log').querySelectorAll('.agent-message')).toHaveLength(1);
 expect(screen.queryByText('Earlier advice')).toBeNull();expect(screen.queryByText('My old direction')).toBeNull();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 expect(screen.queryByRole('checkbox',{name:/Allow elo/})).toBeNull();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
 expect(vi.mocked(careerApi).mock.calls.filter(([, ,options])=>options?.method==='POST')).toHaveLength(posts+1);
});

it('restores the saved transcript on re-entry and continues the same session',async()=>{
 const saved={...base,messages:[{role:'user',content:'My saved interests'},{role:'assistant',content:'Previous complete answer'}]};
 vi.mocked(careerApi).mockImplementation(async(path)=>{
  if(path==='/discoveries/current')return {available:true,session:saved} as never;
  if(path.endsWith('/messages'))return {available:true,session:{...saved,version:3,messages:[...saved.messages,{role:'user',content:'Tell me more'},{role:'assistant',content:'A new response for you.'}]}} as never;
  throw new Error(path);
 });
 const mounted=render(<CareerDiscovery/>);
 await screen.findByText('Previous complete answer');
 expect(screen.queryByRole('button',{name:'Show full response'})).toBeNull();
 mounted.unmount();render(<CareerDiscovery/>);
 await screen.findByText('Previous complete answer');
 expect(screen.getByText('My saved interests')).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Show full response'})).toBeNull();
 send('Tell me more');
 await screen.findByRole('button',{name:'Show full response'});
 expect(screen.getByText('Previous complete answer')).toBeInTheDocument();
 const sent=vi.mocked(careerApi).mock.calls.find(([path])=>path.endsWith('/messages'))!;
 expect(sent[0]).toBe(`/discoveries/${base.id}/messages`);
 expect(JSON.parse(sent[2]!.body as string)).toMatchObject({expected_version:2,message:'Tell me more'});
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path==='/discoveries')).toBe(false);
});

it('refreshing after New chat restores the newly saved empty session',async()=>{
 let saved:typeof empty|undefined;
 const fresh={...empty,id:'000000000000000000000009'};
 vi.mocked(careerApi).mockImplementation(async(path)=>{
  if(path==='/discoveries/current')return {available:true,introduction,session:saved||null} as never;
  if(path==='/discoveries'){saved=fresh;return {available:true,introduction,session:fresh} as never;}
  if(path.endsWith('/messages'))return {available:true,session:{...fresh,version:2,messages:[{role:'user',content:'Hello'}]}} as never;
  throw new Error(path);
 });
 const mounted=render(<CareerDiscovery/>);await screen.findByText(introduction);
 fireEvent.click(screen.getByRole('button',{name:'New chat'}));
 await waitFor(()=>expect(screen.getByRole('button',{name:'New chat'})).toBeEnabled());
 mounted.unmount();await open();send('Hello');
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(([path])=>path===`/discoveries/${fresh.id}/messages`)).toBe(true));
 expect(vi.mocked(careerApi).mock.calls.filter(([path])=>path==='/discoveries')).toHaveLength(1);
});

it('keeps the existing conversation when New chat fails and retries its creation key',async()=>{
 let attempts=0;
 vi.mocked(careerApi).mockImplementation(async(path)=>{
  if(path==='/discoveries/current')return {available:true,session:{...base,messages:[{role:'assistant',content:'Saved advice'}]}} as never;
  if(path==='/discoveries'){
   if(++attempts===1)throw new Error('Synthetic connection failure');
   return {available:true,introduction,session:{...empty,id:'000000000000000000000009'}} as never;
  }
  throw new Error(path);
 });
 render(<CareerDiscovery/>);await screen.findByText('Saved advice');
 fireEvent.click(screen.getByRole('button',{name:'New chat'}));
 await screen.findByText('Synthetic connection failure');
 expect(screen.getByText('Saved advice')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'New chat'}));
 await screen.findByText(introduction);
 const starts=vi.mocked(careerApi).mock.calls.filter(([path])=>path==='/discoveries');
 expect(starts[0][2]!.headers).toEqual(starts[1][2]!.headers);
});

it('does not create a different session after returning to a confirmed discovery',async()=>{
 vi.mocked(careerApi).mockResolvedValue({available:true,session:{...base,status:'confirmed',messages:[{role:'assistant',content:'Your saved direction'}]}} as never);
 render(<CareerDiscovery/>);await screen.findByText('Your saved direction');send('Thanks');
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(([path])=>path===`/discoveries/${base.id}/messages`)).toBe(true));
 expect(vi.mocked(careerApi).mock.calls.some(([path])=>path==='/discoveries')).toBe(false);
});

it('blocks sends until saved progress has loaded, including after a read failure',async()=>{
 let reject!:(error:Error)=>void;
 vi.mocked(careerApi).mockImplementation(()=>new Promise((_resolve,no)=>{reject=no;}));
 render(<CareerDiscovery/>);send('A draft while loading');
 expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
 await act(async()=>reject(new Error('Synthetic connection failure')));
 expect(screen.getByRole('alert')).toHaveTextContent('Could not load your discovery');
 expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
 expect(vi.mocked(careerApi).mock.calls).toHaveLength(1);
});

it('reveals new replies progressively, preserves drafts and leaves earlier replies complete',async()=>{
 const answer='Consider backend engineering and practise building APIs.';
 let turn=0;
 configure(()=>({available:true,session:{...base,version:++turn+1,messages:[
  {role:'user',content:'Explore backend'},
  {role:'assistant',content:answer},
  ...(turn>1?[{role:'user',content:'What next?'},{role:'assistant',content:'Next build a small project.'}]:[]),
 ]}}));
 await open();send('Explore backend');
 await screen.findByRole('button',{name:'Show full response'});
 expect(screen.queryByText(answer)).toBeNull();
 expect(screen.getByRole('log')).toHaveTextContent('Explore backend');
 fireEvent.click(screen.getByRole('button',{name:'Show full response'}));
 expect(screen.getByText(answer)).toBeInTheDocument();
 send('What next?');
 await screen.findByRole('button',{name:'Show full response'});
 expect(screen.getByText(answer)).toBeInTheDocument();
 fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'My next draft'}});
 fireEvent.click(screen.getByRole('button',{name:'Show full response'}));
 expect(screen.getByText('Next build a small project.')).toBeInTheDocument();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('My next draft');
});

it('reveals decision-only replies and their question together',async()=>{
 configure(()=>({available:true,session:{...base,decision:{...decision,question:'Which work interests you?'}}}));
 await open();send();
 fireEvent.click(await screen.findByRole('button',{name:'Show full response'}));
 expect(screen.getByText(decision.reply)).toBeInTheDocument();
 expect(screen.getByText('Which work interests you?')).toBeInTheDocument();
});

it('shows discovery replies immediately for reduced motion',async()=>{
 vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
 configure(()=>({available:true,session:{...base,messages:[{role:'assistant',content:'Consider backend engineering and practise building APIs.'}]}}));
 await open();send();
 await screen.findByText('Consider backend engineering and practise building APIs.');
 expect(screen.queryByRole('button',{name:'Show full response'})).toBeNull();
});


it('clears private history on account changes and ignores an earlier account read',async()=>{
 let oldRead!:(value:unknown)=>void;
 vi.mocked(careerApi).mockImplementation(async(_path,token)=>{
  if(token==='synthetic')return await new Promise<unknown>(resolve=>{oldRead=resolve;}) as never;
  return {available:true,session:{...base,id:'000000000000000000000099',messages:[{role:'assistant',content:'New account conversation'}]}} as never;
 });
 const mounted=render(<CareerDiscovery/>);
 await waitFor(()=>expect(oldRead).toBeTypeOf('function'));
 fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'Private draft'}});
 profileState.token='other-account';mounted.rerender(<CareerDiscovery/>);
 await screen.findByText('New account conversation');
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');
 await act(async()=>oldRead({available:true,session:{...base,messages:[{role:'assistant',content:'Old private conversation'}]}}));
 expect(screen.queryByText('Old private conversation')).toBeNull();
 expect(screen.getByText('New account conversation')).toBeInTheDocument();
});

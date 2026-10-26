import {useState} from 'react';
import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {CareerChat} from './career-chat';
import {CareerSessionProvider,useCareerSession} from './career-session';
import {careerApi,importExplorationCV,type CareerWorkspace,type GoalDraft} from '@/lib/api/career';
const push=vi.fn(),replace=vi.fn(),search=new URLSearchParams();
vi.mock('next/navigation',()=>({useRouter:()=>({push,replace}),useSearchParams:()=>search}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-session'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn(),importExplorationCV:vi.fn()}));
const draft:GoalDraft={_id:'000000000000000000000001',version:1,answers:{},turns:[],interests:[],preferences:[],suggestions:[],next_question:'aspirations',question_text:'What would you like to achieve?',context_complete:false,cv:{mode:'none',filename:null,cv_id:null,version:null,extraction_version:null}};
function initial():CareerWorkspace{return {session_id:'000000000000000000000071',revision:1,kind:'jd',phase:'ready',
 review:{review_id:'000000000000000000000081',version:1,target_type:'specific_job',extraction:{role:'Engineer',field:'Software',company:null,location:'Singapore',seniority_level:'Junior',job_url:null,summary:'Build backend services.',responsibilities:['Build APIs'],non_skill_requirements:[],skills:[{item_id:'python',name:'Python',category:'Technical',priority:'required',origin:'employer',evidence:'Python required.'}]},baseline:{role:'Engineer',field:'Software',company:null,location:null,seniority_level:null,job_url:null,summary:null,responsibilities:[],skills:[],non_skill_requirements:[]},metadata_origins:{},requirements_need_review:false,is_confirmed:false,generation:{}},
 current:{selection_version:1,goal:null,dependent_results_need_review:false},research:{_id:'000000000000000000000091',version:1,last_researched_at:'2026-01-01T00:00:00Z',research_status:'succeeded',skills:[{skill_id:null,name:'Coding',category:'Technical',interview_stage:'Technical interview',assessment_type:'Coding exercise',difficulty:'unknown',question_patterns:[],independent_report_count:0,source_ids:['s1']}],sources:[{source_id:'s1',platform:'reddit',url:'https://example.test/interview',title:'Interview report',evidence:'Reported coding exercise.',published_date:null,reported_date:null,role_match:'unknown',reliability:'anecdotal',report_group:null}]},coverage:[],error:null,retry_after:null,expires_at:null,exploration_id:null};}
let active:CareerWorkspace,empty:CareerWorkspace,failChat=false;
beforeEach(()=>{
 vi.resetAllMocks();Object.defineProperty(window,'matchMedia',{configurable:true,value:()=>({matches:true,addEventListener(){},removeEventListener(){}})});search.forEach((_,key)=>search.delete(key));active=initial();empty={...active,session_id:null,kind:null,phase:'empty',review:null,research:null};failChat=false;
 vi.mocked(careerApi).mockImplementation(async(path,_token,options)=>{
  if(path==='/workspace/jd')return active as never;
  if(path==='/workspace/messages'){
   if(failChat)throw new Error('Provider unavailable');
   return {reply:'Practise Python for the reported coding exercise.',proposed_skills:null} as never;
  }
  if(path==='/workspace')return active as never;
  if(path==='/context')return {cvs:[],cv_service_available:true,ai_available:true} as never;
  if(path==='/goals/current')return active.current as never;
  if(path==='/explorations')return draft as never;
  if(path.endsWith('/messages'))return {...draft,version:2,turns:[{question:'aspirations',answer:{value:'I enjoy data'},reply:'What appeals to you about data?'}]} as never;
  return draft as never;
 });
});
function Import(){const session=useCareerSession(),[show,setShow]=useState(false);return show?<CareerChat/>:<button onClick={()=>{session.chooseJD({text:'Private synthetic Python JD',kind:'text',name:'Pasted description'});setShow(true);}}>Import test JD</button>;}
function mount(){return render(<CareerSessionProvider><CareerChat/></CareerSessionProvider>);}
async function chat(){mount();await screen.findByText(/Let’s look at Engineer/);}
describe('single career conversation',()=>{
 it('extracts a new JD into the only workspace and opens research-backed explanation',async()=>{
  render(<CareerSessionProvider><Import/></CareerSessionProvider>);fireEvent.click(screen.getByRole('button',{name:'Import test JD'}));
  await screen.findByText(/Let’s look at Engineer/);
  const call=vi.mocked(careerApi).mock.calls.find(v=>v[0]==='/workspace/jd')!;
  expect(JSON.parse(call[2]!.body as string)).toMatchObject({text:'Private synthetic Python JD'});
  expect(screen.getByRole('log')).toHaveTextContent('Python');expect(screen.getByRole('log')).toHaveTextContent('Technical interview');
  expect(screen.queryByRole('button',{name:/Confirm.*goal/})).toBeNull();
  for(const name of ['Your career goal','Skills for this role','Interview process'])expect(screen.getByRole('heading',{name})).toBeInTheDocument();
  expect(screen.getByRole('log').querySelector('strong')).toBeInTheDocument();
 });
 it('loads the latest workspace regardless of an old review query parameter',async()=>{
  search.set('review','old-review');await chat();
  expect(vi.mocked(careerApi).mock.calls.some(v=>v[0].includes('old-review'))).toBe(false);
  expect(screen.queryByText('Previous conversations')).toBeNull();
 });
 it('sends session/version and bounded turns without resending raw JD',async()=>{
  await chat();fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'How should I prepare?'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByText('Practise Python for the reported coding exercise.');
  const body=JSON.parse(vi.mocked(careerApi).mock.calls.find(v=>v[0]==='/workspace/messages')![2]!.body as string);
  expect(body).toMatchObject({session_id:active.session_id,expected_version:1});expect(body).not.toHaveProperty('context');expect(body).not.toHaveProperty('text');
 });
 it('holds the composer until both extraction and interview research finish',async()=>{
  active={...active,phase:'waiting_quota',research:null,retry_after:60};mount();
  await screen.findByText('Waiting for the AI token budget');expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
  expect(screen.queryByText(/Let’s look at Engineer/)).toBeNull();
 });
 it('edits the career goal through guided chat and refreshes the saved summary without an edit form',async()=>{
  await chat();expect(screen.queryByRole('button',{name:'Edit career goal'})).toBeNull();
  const api=vi.mocked(careerApi),original=api.getMockImplementation()!;let followup=false;
  api.mockImplementation(async(path,token,options)=>{
   if(path==='/workspace/messages'){
    if(!followup)return {reply:'Which detail would you like to change: role, location or a skill?',edit_status:'clarifying'} as never;
    active={...active,revision:2,review:{...active.review!,version:2,extraction:{...active.review!.extraction,location:'London'}}};
    return {reply:'Updated your goal location to London.',edit_status:'saved',workspace:active} as never;
   }
   return original(path,token,options);
  });
  const box=screen.getByRole('textbox',{name:'Message Coachify'});
  fireEvent.change(box,{target:{value:'Change my goal'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByText('Which detail would you like to change: role, location or a skill?');
  followup=true;fireEvent.change(box,{target:{value:'Change the location to London'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByText('Updated your goal location to London.');
  expect(screen.getByRole('log')).toHaveTextContent('London');
  expect(screen.queryByRole('button',{name:'Apply skill changes'})).toBeNull();
  expect(api.mock.calls.filter(c=>c[0]==='/workspace/review')).toHaveLength(0);
 });
 it('reuses the same message key after a failed conversational edit',async()=>{
  failChat=true;await chat();const box=screen.getByRole('textbox',{name:'Message Coachify'});
  fireEvent.change(box,{target:{value:'Change my company to Example'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByRole('button',{name:'Retry'});
  expect(box).toHaveValue('Change my company to Example');
  expect(screen.queryByRole('alert')).toBeNull();expect(screen.queryByText('Provider unavailable')).toBeNull();
  const first=vi.mocked(careerApi).mock.calls.filter(c=>c[0]==='/workspace/messages')[0][2]?.headers;
  failChat=false;fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByText('Practise Python for the reported coding exercise.');
  expect(vi.mocked(careerApi).mock.calls.filter(c=>c[0]==='/workspace/messages')[1][2]?.headers).toEqual(first);
 });
 it('shows an explicit empty JD state instead of silently changing to exploration',async()=>{
  active=empty;search.set('source','jd');mount();await screen.findByText(/No job description is available/);expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
 });
 it('starts separate exploration without a session chooser or goal confirmation',async()=>{
  active=empty;mount();await screen.findByText(/Hi, I’m your career agent/);fireEvent.click(screen.getByRole('checkbox',{name:/Allow Coachify/}));fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'I enjoy data'}});await waitFor(()=>expect(screen.getByRole('button',{name:'Send message'})).toBeEnabled());fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByText('What appeals to you about data?');expect(screen.queryByText('Previous conversations')).toBeNull();
 });
 it('keeps a pending-context goal current and explains that its requirements need review',async()=>{
  active.review!.requirements_need_review=true;await chat();
  expect(screen.getByRole('log')).toHaveTextContent('The role context changed');
  fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'Which requirements need review?'}});
  expect(screen.getByRole('button',{name:'Send message'})).toBeEnabled();
  expect(screen.queryByRole('button',{name:/Confirm.*goal/})).toBeNull();
 });
 it('keeps temporary CV content out of browser storage',async()=>{
  active=empty;vi.mocked(importExplorationCV).mockResolvedValue({kind:'document',source_name:'cv.txt',text:'Synthetic private CV',notices:[]});const storage=vi.spyOn(Storage.prototype,'setItem');mount();await screen.findByText(/Hi, I’m your career agent/);fireEvent.click(screen.getByText('CV optional · add or choose a CV'));fireEvent.change(screen.getByLabelText('Temporary CV attachment'),{target:{files:[new File(['Synthetic private CV'],'cv.txt',{type:'text/plain'})]}});await screen.findByText('Temporary CV: cv.txt');expect(storage).not.toHaveBeenCalled();
 });
});


it('waits for the quota retry time instead of polling every two seconds',async()=>{
 vi.useFakeTimers();let view:ReturnType<typeof render>|undefined;
 try{
  active={...active,phase:'waiting_quota',research:null,retry_after:60};
  await act(async()=>{view=mount();});
  const calls=()=>vi.mocked(careerApi).mock.calls.filter(v=>v[0]==='/workspace').length;
  const initialCalls=calls();expect(initialCalls).toBeGreaterThan(0);
  await act(async()=>{await vi.advanceTimersByTimeAsync(59_000);});
  expect(calls()).toBe(initialCalls);
  active=initial();
  await act(async()=>{await vi.advanceTimersByTimeAsync(1_000);});
  expect(calls()).toBe(initialCalls+1);
  expect(screen.getByRole('log')).toHaveTextContent('Let’s look at Engineer');
  await act(async()=>{await vi.advanceTimersByTimeAsync(60_000);});
  expect(calls()).toBe(initialCalls+1);
 }finally{view?.unmount();vi.useRealTimers();}
});


it('counts down a per-user token wait and retains the unsent message',async()=>{
 await chat();
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation(async(path,token,options)=>{
  if(path==='/workspace/messages')throw Object.assign(new Error('Your 7,000-token rolling-minute allowance has been reached. Retry after 3 seconds.'),{code:'rate_limited',retryAt:Date.now()+3000});
  return original(path,token,options);
 });
 const box=screen.getByRole('textbox',{name:'Message Coachify'});
 fireEvent.change(box,{target:{value:'Explain Python'}});
 vi.useFakeTimers();
 try{
  await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Send message'}));});
  expect(box).toHaveValue('Explain Python');
  expect(screen.getByRole('alert')).toHaveTextContent('Try again in 3 seconds.');
  expect(screen.getByRole('button',{name:'Retry'})).toBeDisabled();
  await act(async()=>{await vi.advanceTimersByTimeAsync(3000);});
  expect(screen.getByRole('alert')).toHaveTextContent('You can retry now.');
  expect(screen.getByRole('button',{name:'Send message'})).toBeEnabled();
 }finally{vi.useRealTimers();}
});


it('labels AI findings without provider branding and exposes source links',async()=>{
 active.research!.summaries=[{summary_id:'answer1',provider:'brave',text:'Candidates report coding assessments.',source_ids:['s1'],claims:[{text:'Candidates report coding assessments.',source_ids:['s1']}]}];
 active.research!.skills[0]={...active.research!.skills[0],evidence_origin:'brave_summary',summary_id:'answer1'};
 await chat();
 expect(screen.getByRole('log')).toHaveTextContent('AI synthesis linked to sources');
 expect(screen.getByRole('log')).not.toHaveTextContent('Brave');
 fireEvent.click(screen.getByRole('button',{name:'Role and research details'}));
 expect(screen.getByText('AI interview summary')).toBeInTheDocument();
 expect(screen.getByText('Candidates report coding assessments.')).toBeInTheDocument();
 expect(screen.getAllByText(/not a direct website quotation/).length).toBeGreaterThan(0);
 expect(screen.getByRole('link',{name:'View source'})).toHaveAttribute('href','https://example.test/interview');
});

it('shows activity inside the pending reply and replaces it with formatted output',async()=>{
 await chat();
 let resolve!:(value:never)=>void;
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation((path,token,options)=>path==='/workspace/messages'?new Promise(done=>{resolve=done;}):original(path,token,options));
 fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'Explain SQL'}});
 fireEvent.click(screen.getByRole('button',{name:'Send message'}));
 const status=screen.getByRole('status');
 expect(screen.getByRole('log')).toContainElement(status);
 expect(status).toHaveTextContent('Preparing your answer');
 expect(screen.getByText('Explain SQL',{selector:'p'})).toBeInTheDocument();
 await act(async()=>resolve({reply:'Learn **SQL**.\n\n- Practise joins',proposed_skills:null} as never));
 expect(screen.queryByText('Preparing your answer…')).toBeNull();
 expect(screen.getByText('SQL',{selector:'strong'})).toBeInTheDocument();
 expect(screen.getByText('Practise joins',{selector:'li'})).toBeInTheDocument();
 expect(screen.getAllByText('Explain SQL')).toHaveLength(1);
});

it('shows initial research activity in the chat and replaces it when research is ready',async()=>{
 vi.useFakeTimers();let view:ReturnType<typeof render>|undefined;
 try{
  active={...active,phase:'researching',research:null};
  await act(async()=>{view=mount();});
  const log=screen.getByRole('log');
  expect(log).toContainElement(screen.getByRole('status'));
  expect(log).toHaveTextContent('Researching interview expectations');
  expect(log).not.toHaveTextContent('Brave');
  active=initial();
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000);});
  expect(log).toHaveTextContent('Let’s look at Engineer');
  expect(screen.queryByText('Researching interview expectations…')).toBeNull();
 }finally{view?.unmount();vi.useRealTimers();}
});

it('summarises saved round counts and stage names without an extra generation call',async()=>{
 active.research!.process={round_count:3,stages:[{name:'Recruiter screen',assessment_type:null}]};
 await chat();
 expect(screen.getByRole('log')).toHaveTextContent('Reported interview rounds: 3.');
 expect(screen.getByRole('log')).toHaveTextContent('Recruiter screen');
 expect(vi.mocked(careerApi).mock.calls.some(v=>v[0]==='/workspace/messages')).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Role and research details'}));
 expect(screen.getByText('Reported rounds: 3')).toBeInTheDocument();
});

it('keeps background research diagnostics out of the UI and offers resume',async()=>{
 active={...active,phase:'research_failed',research:null,error_code:'research_unavailable',error:'PRIVATE Brave OPTION_NOT_IN_PLAN diagnostic'};
 mount();await screen.findByRole('button',{name:'Resume research'});
 expect(screen.queryByText(/PRIVATE/)).toBeNull();
 expect(screen.queryByRole('alert')).toBeNull();
});

it('shows background input-token limits but not other failure details',async()=>{
 active={...active,phase:'research_failed',research:null,error_code:'input_limit',error:'The AI input exceeds 4,000 tokens.'};
 mount();expect(await screen.findByRole('alert')).toHaveTextContent('4,000 tokens');
});

it('automatically resumes initial JD extraction after a quota wait without another submission',async()=>{
 vi.useFakeTimers();let view:ReturnType<typeof render>|undefined;
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation(async(path,token,options)=>{
  if(path==='/workspace/jd')return {operation_id:'a'.repeat(32),status:'waiting_quota',retry_after:3,result:null} as never;
  if(path.startsWith('/workspace/operations/'))return {operation_id:'a'.repeat(32),status:'succeeded',retry_after:null,result:active} as never;
  return original(path,token,options);
 });
 try{
  view=render(<CareerSessionProvider><Import/></CareerSessionProvider>);
  await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Import test JD'}));});
  expect(screen.getByRole('status')).toHaveTextContent('Waiting for the AI token budget');
  expect(screen.queryByRole('button',{name:'Retry'})).toBeNull();
  await act(async()=>{await vi.advanceTimersByTimeAsync(2999);});
  expect(api.mock.calls.filter(c=>c[0].startsWith('/workspace/operations/'))).toHaveLength(0);
  await act(async()=>{await vi.advanceTimersByTimeAsync(1);});
  expect(screen.getByRole('log')).toHaveTextContent('Let’s look at Engineer');
  const submissions=api.mock.calls.filter(c=>c[0]==='/workspace/jd');
  expect(submissions).toHaveLength(1);
  expect(submissions[0][2]?.headers).toMatchObject({prefer:'respond-async'});
 }finally{view?.unmount();vi.useRealTimers();}
});

it('keeps the JD receipt across chat remounts and reconnects to its pending operation',async()=>{
 function Journey(){
  const session=useCareerSession(),[opened,setOpened]=useState(false);
  return <><button onClick={()=>{if(!session.jd)session.chooseJD({text:'Synthetic SQL JD',kind:'text',name:'Pasted description'});setOpened(true);}}>Open extraction</button><button onClick={()=>setOpened(false)}>Leave extraction</button>{opened&&<CareerChat/>}</>;
 }
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation(async(path,token,options)=>path==='/workspace/jd'?{operation_id:'d'.repeat(32),status:'waiting_quota',retry_after:600,result:null} as never:original(path,token,options));
 const view=render(<CareerSessionProvider><Journey/></CareerSessionProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Open extraction'}));
 await screen.findByText('Waiting for the AI token budget');
 fireEvent.click(screen.getByRole('button',{name:'Leave extraction'}));
 fireEvent.click(screen.getByRole('button',{name:'Open extraction'}));
 await screen.findByText('Waiting for the AI token budget');
 const calls=api.mock.calls.filter(call=>call[0]==='/workspace/jd');
 expect(calls).toHaveLength(2);
 expect(calls[0][2]?.headers).toEqual(calls[1][2]?.headers);
 expect(calls[0][2]?.body).toEqual(calls[1][2]?.body);
 view.unmount();
});

it('explains extraction conflicts without displaying provider diagnostics',async()=>{
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation(async(path,token,options)=>{
  if(path==='/workspace/jd')throw Object.assign(new Error('PRIVATE diagnostic'),{code:'operation_in_progress'});
  return original(path,token,options);
 });
 render(<CareerSessionProvider><Import/></CareerSessionProvider>);
 fireEvent.click(screen.getByRole('button',{name:'Import test JD'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Another request is still being processed.');
 expect(screen.queryByText('PRIVATE diagnostic')).toBeNull();
});

it('keeps a chat turn pending and delivers the reply automatically when its quota resets',async()=>{
 await chat();
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation(async(path,token,options)=>{
  if(path==='/workspace/messages')return {operation_id:'b'.repeat(32),status:'waiting_quota',retry_after:2,result:null} as never;
  if(path.startsWith('/workspace/operations/'))return {operation_id:'b'.repeat(32),status:'succeeded',retry_after:null,result:{reply:'Automatic reply',proposed_skills:null}} as never;
  return original(path,token,options);
 });
 vi.useFakeTimers();
 try{
  fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'Explain Python'}});
  await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Send message'}));});
  expect(screen.getByRole('status')).toHaveTextContent('Resuming automatically in 2 seconds');
  expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
  expect(screen.queryByRole('button',{name:'Retry'})).toBeNull();
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000);});
  expect(screen.getByRole('log')).toHaveTextContent('Automatic reply');
  expect(screen.getByRole('textbox',{name:'Message Coachify'})).toHaveValue('');
  expect(api.mock.calls.filter(c=>c[0]==='/workspace/messages')).toHaveLength(1);
 }finally{vi.useRealTimers();}
});


it('keeps schema correction details in the operation response and displays the recovered answer',async()=>{
 await chat();
 const api=vi.mocked(careerApi),original=api.getMockImplementation()!;
 api.mockImplementation(async(path,token,options)=>{
  if(path==='/workspace/messages')return {operation_id:'c'.repeat(32),status:'repairing',retry_after:null,result:null,
   validation_feedback:{reason:'schema_validation',fields:['reply'],violations:[{field:'reply',issue:'missing'}]}} as never;
  if(path.startsWith('/workspace/operations/'))return {operation_id:'c'.repeat(32),status:'succeeded',retry_after:null,result:{reply:'A valid grounded answer',proposed_skills:null}} as never;
  return original(path,token,options);
 });
 vi.useFakeTimers();
 try{
  fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'Explain Python'}});
  await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Send message'}));});
  expect(screen.getByRole('status')).toHaveTextContent('Refining the response');
  expect(screen.queryByRole('alert')).toBeNull();expect(screen.queryByRole('button',{name:'Retry'})).toBeNull();
  expect(screen.queryByText('schema_validation')).toBeNull();expect(screen.queryByText('missing')).toBeNull();
  await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
  expect(screen.getByRole('log')).toHaveTextContent('A valid grounded answer');
  expect(screen.queryByText('Refining the response…')).toBeNull();
  expect(api.mock.calls.filter(c=>c[0]==='/workspace/messages')).toHaveLength(1);
 }finally{vi.useRealTimers();}
});


it('restores the latest guided edit question from the saved workspace',async()=>{
 active={...active,edit_question:'Which city or country should the job be based in?'};
 await chat();expect(screen.getByRole('log')).toHaveTextContent('Which city or country should the job be based in?');
 expect(screen.getByRole('textbox',{name:'Message Coachify'})).toBeEnabled();
 expect(screen.queryByRole('button',{name:'Edit career goal'})).toBeNull();
});


it.each([0,1,3])('shows assessed source coverage honestly for %i useful sources',async(count)=>{
 active.coverage=[{platform:'brave',status:count?'succeeded':'no_findings',round:5,
  useful_sources:count,target_sources:3,limit_reached:count<3}];
 await chat();const log=screen.getByRole('log');
 expect(log).toHaveTextContent(`${count} distinct sources`);
 expect(log.textContent?.includes('Findings remain limited.')).toBe(count<3);
 expect(log).not.toHaveTextContent('Brave');
});

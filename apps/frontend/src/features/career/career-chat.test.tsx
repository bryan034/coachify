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
let active:CareerWorkspace,empty:CareerWorkspace,failSave=false,failChat=false;
beforeEach(()=>{
 vi.resetAllMocks();Object.defineProperty(window,'matchMedia',{configurable:true,value:()=>({matches:true,addEventListener(){},removeEventListener(){}})});search.forEach((_,key)=>search.delete(key));active=initial();empty={...active,session_id:null,kind:null,phase:'empty',review:null,research:null};failSave=false;failChat=false;
 vi.mocked(careerApi).mockImplementation(async(path,_token,options)=>{
  if(path==='/workspace/jd')return active as never;
  if(path==='/workspace/review'){
   if(failSave)throw new Error('Storage unavailable');
   const body=JSON.parse(options!.body as string);active={...active,revision:2,review:{...active.review!,version:2,extraction:body.content}};return active as never;
  }
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
 it('retains a failed message for retry',async()=>{
  failChat=true;await chat();const box=screen.getByRole('textbox',{name:'Message Coachify'});fireEvent.change(box,{target:{value:'Explain Python'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByRole('button',{name:'Retry'});expect(screen.queryByRole('alert')).toBeNull();expect(screen.queryByText('Provider unavailable')).toBeNull();expect(box).toHaveValue('Explain Python');failChat=false;fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByText('Practise Python for the reported coding exercise.');
 });
 it('automatically updates the goal from saved edits and keeps the same retry key',async()=>{
  await chat();fireEvent.click(screen.getByRole('button',{name:'Edit career goal'}));fireEvent.change(screen.getByRole('textbox',{name:'Company'}),{target:{value:'Example Company'}});fireEvent.click(screen.getByRole('checkbox',{name:/I have reviewed/}));
  failSave=true;fireEvent.click(screen.getByRole('button',{name:'Save review'}));await screen.findByRole('button',{name:'Retry'});expect(screen.queryByText('Storage unavailable')).toBeNull();expect(screen.getByRole('textbox',{name:'Company'})).toHaveValue('Example Company');
  const first=vi.mocked(careerApi).mock.calls.find(v=>v[0]==='/workspace/review')![2]!.headers;
  failSave=false;fireEvent.click(screen.getByRole('button',{name:'Save review'}));await waitFor(()=>expect(screen.queryByRole('button',{name:'Save review'})).toBeNull());
  expect(vi.mocked(careerApi).mock.calls.filter(v=>v[0]==='/workspace/review')[1][2]!.headers).toEqual(first);
  expect(active.review!.extraction.company).toBe('Example Company');expect(screen.queryByRole('button',{name:/Confirm.*goal/})).toBeNull();
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


it('labels Brave AI findings and exposes the summary with source links',async()=>{
 active.research!.summaries=[{summary_id:'answer1',provider:'brave',text:'Candidates report coding assessments.',source_ids:['s1'],claims:[{text:'Candidates report coding assessments.',source_ids:['s1']}]}];
 active.research!.skills[0]={...active.research!.skills[0],evidence_origin:'brave_summary',summary_id:'answer1'};
 await chat();
 expect(screen.getByRole('log')).toHaveTextContent('Brave AI synthesis linked to sources');
 fireEvent.click(screen.getByRole('button',{name:'Role and research details'}));
 expect(screen.getByText('Brave AI interview summary')).toBeInTheDocument();
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
  expect(log).toHaveTextContent('Researching interview expectations with Brave');
  active=initial();
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000);});
  expect(log).toHaveTextContent('Let’s look at Engineer');
  expect(screen.queryByText('Researching interview expectations with Brave…')).toBeNull();
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

it('formats the initial JD overview with headings and skill lists',async()=>{
 await chat();const log=screen.getByRole('log');
 expect(screen.getByRole('heading',{name:'Your career goal'})).toBeInTheDocument();
 expect(screen.getByRole('heading',{name:'Skills for this role'})).toBeInTheDocument();
 expect(screen.getByRole('heading',{name:'Interview process'})).toBeInTheDocument();
 expect(log.querySelector('strong')).toBeInTheDocument();
});

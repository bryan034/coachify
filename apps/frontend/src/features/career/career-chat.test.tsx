import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {CareerChat} from './career-chat';
import {CareerSessionProvider,useCareerSession} from './career-session';
import {careerApi,importExplorationCV,type GoalDraft} from '@/lib/api/career';
const push=vi.fn();const search=new URLSearchParams();
vi.mock('next/navigation',()=>({useRouter:()=>({push}),useSearchParams:()=>search}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-session'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn(),importExplorationCV:vi.fn()}));
const base:GoalDraft={_id:'000000000000000000000001',version:1,answers:{},turns:[],interests:[],preferences:[],suggestions:[],
 next_question:'aspirations',question_text:'What would you like to achieve?',context_complete:false,
 cv:{mode:'none',filename:null,cv_id:null,version:null,extraction_version:null}};
const calls:{path:string;body:Record<string,unknown>}[]=[];
let fail=false;let selected=false;
beforeEach(()=>{
 search.delete('source');search.delete('exploration');calls.length=0;fail=false;selected=false;vi.mocked(careerApi).mockClear();vi.mocked(importExplorationCV).mockClear();
 vi.mocked(careerApi).mockImplementation(async(path,_token,options)=>{
  if(path==='/jd/extract')return {extraction:{role:'Engineer',field:'Software',company:null,skills:[{name:'Python',category:'Technical',priority:'required',origin:'employer',evidence:'Python'}]},generation:{}} as never;
  if(path==='/jd/messages')return {reply:'Python is a programming language.',proposed_skills:null} as never;
  if(options?.method==='POST'){
   const body=JSON.parse(options.body as string);calls.push({path,body});
   if(path==='/explorations')return base as never;
   if(path.endsWith('/messages')){
    if(fail)throw new Error('The provider is unavailable.');
    return {...base,version:2,answers:{aspirations:{status:'partial',value:body.answer}},
     turns:[{question:'aspirations',answer:{status:'answered',value:body.answer},reply:'What appeals to you about that direction?'}]} as never;
   }
   return {selection_version:1,goal:{_id:'g',role:'Analyst',field:'Data',version:1,readiness:'pending'},dependent_results_need_review:false} as never;
  }
  if(path.includes('/explorations/'))return {...base,context_complete:true,next_question:null,suggestions:[{role:'Analyst',field:'Data',rationale:'A possible fit.',uncertainty:'Skills remain unknown.'}]} as never;
  return (path==='/context'?{cvs:[],cv_service_available:true,ai_available:true}:path==='/goals/current'?{selection_version:selected?3:0,goal:selected?{role:'Existing goal'}:null}:{goals:[],explorations:[]}) as never;
 });
});
afterEach(()=>vi.restoreAllMocks());
function ShowJD(){const session=useCareerSession();return <><button onClick={()=>session.chooseJD({text:'Python backend engineer requirements.',kind:'text',name:'Pasted description'})}>Select test JD</button><CareerChat/></>;}
const mount=()=>render(<CareerSessionProvider><CareerChat/></CareerSessionProvider>);
describe('shared career agent chat',()=>{
 it('starts with a conversational agent and sends an open-ended message after consent',async()=>{
  mount();await screen.findByText(/Hi, I’m your career agent/);
  expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
  expect(screen.getByText(/No CV is required to start/)).toBeVisible();
  fireEvent.click(screen.getByRole('checkbox',{name:/Allow Coachify/}));
  fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'I enjoy data but I am not sure what work I want.'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send message'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByText('What appeals to you about that direction?');
  expect(calls.at(-1)?.body).toMatchObject({answer:'I enjoy data but I am not sure what work I want.',skip:false,expected_version:1});
  expect(calls.some(c=>c.path==='/goals/confirm')).toBe(false);
  expect(screen.queryByText(/5 topics/)).not.toBeInTheDocument();
 });
 it('keeps the message and the same request key on provider failure and retry',async()=>{
  fail=true;mount();await screen.findByText(/Hi, I’m your career agent/);
  fireEvent.click(screen.getByRole('checkbox',{name:/Allow Coachify/}));
  fireEvent.change(screen.getByRole('textbox',{name:'Message Coachify'}),{target:{value:'I want to build useful software.'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send message'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByRole('alert');
  expect(screen.getByRole('textbox',{name:'Message Coachify'})).toHaveValue('I want to build useful software.');
  const initial=vi.mocked(careerApi).mock.calls.find(c=>c[0].endsWith('/messages'))![2]?.headers;
  fail=false;fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByText('What appeals to you about that direction?');
  expect(vi.mocked(careerApi).mock.calls.filter(c=>c[0].endsWith('/messages'))[1][2]?.headers).toEqual(initial);
 });
 it('extracts JD skills on the shared chat page and supports clarification messages',async()=>{
  search.set('source','jd');render(<CareerSessionProvider><ShowJD/></CareerSessionProvider>);
  fireEvent.click(screen.getByRole('button',{name:'Select test JD'}));
  expect(await screen.findByRole('heading',{name:'Skills to review'})).toBeVisible();
  const composer=screen.getByRole('textbox',{name:'Message Coachify'});
  fireEvent.change(composer,{target:{value:'What is Python?'}});
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  expect(await screen.findByText('Python is a programming language.')).toBeVisible();
  expect(vi.mocked(careerApi).mock.calls.some(c=>c[0]==='/goals/confirm')).toBe(false);
 });
 it('does not silently switch to exploration when a temporary JD is lost',()=>{
  search.set('source','jd');mount();
  expect(screen.getByText(/Your selected job description was temporary/)).toBeVisible();
  expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
 });
 it('requires explicit replacement when reviewing a suggested role',async()=>{
  search.set('exploration',base._id);selected=true;mount();
  fireEvent.click(await screen.findByRole('button',{name:'Review this direction'}));
  expect(screen.getByRole('button',{name:'Confirm and save goal'})).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox',{name:/Replace Existing goal/}));
  fireEvent.click(screen.getByRole('button',{name:'Confirm and save goal'}));
  await screen.findByText(/Career goal saved/);
  expect(calls.at(-1)?.body).toMatchObject({company:null,role:'Analyst',replace_current:true,expected_selection_version:3});
 });
 it('keeps a CV attachment out of browser storage and the draft-creation request',async()=>{
  vi.mocked(importExplorationCV).mockResolvedValue({kind:'document',source_name:'cv.txt',text:'Private synthetic CV',notices:[]});
  const storage=vi.spyOn(Storage.prototype,'setItem');mount();
  await screen.findByText(/Hi, I’m your career agent/);
  fireEvent.click(screen.getByText('CV optional · add or choose a CV'));
  fireEvent.change(screen.getByLabelText('Temporary CV attachment'),{target:{files:[new File(['Private synthetic CV'],'cv.txt',{type:'text/plain'})]}});
  await screen.findByText('Temporary CV: cv.txt');
  expect(storage).not.toHaveBeenCalled();
 });
});

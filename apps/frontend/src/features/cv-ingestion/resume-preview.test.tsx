import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {ResumePreview} from './resume-preview';
import {CvReview} from './cv-review';
import {CapabilityDeclarations} from './capability-declarations';
import {cvApi,CvApiError} from '@/lib/api/cv';
import {policy,savedCv,emptyDeclarations,clarificationState,confirmedTarget} from '../../../tests/fixtures/cv';
import type {CvDetail,CvConversation,CvList} from './types';
const session=vi.hoisted(()=>({token:'synthetic-session' as string|undefined,account:{id:'owner-a'}}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>session}));
vi.mock('@/lib/api/cv',async importOriginal=>{const actual=await importOriginal<typeof import('@/lib/api/cv')>();return {...actual,cvApi:Object.fromEntries(Object.keys(actual.cvApi).map(key=>[key,vi.fn()]))};});
const emptyConversation:CvConversation={id:'conversation',cv_id:null,revision:1,read_only:false,previous_conversation_id:null,active_question:null,context:null,messages:[],next_before:null,limits:{max_message_chars:4000,max_messages:500}};
function renderWorkspace(){const view=render(<ResumePreview/>);fireEvent.click(screen.getByText('CV files',{selector:'summary span'}));fireEvent.click(screen.getByText('Your CV summary',{selector:'summary span'}));return view;}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(cvApi.openConversation).mockImplementation(async body=>({...emptyConversation,cv_id:body.cv_id}));session.token='synthetic-session';session.account={id:'owner-a'};vi.mocked(cvApi.policy).mockResolvedValue(policy);vi.mocked(cvApi.list).mockResolvedValue({cvs:[],selection:{cv_id:null,version:0}});vi.mocked(cvApi.declarations).mockResolvedValue(emptyDeclarations);vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(savedCv()));vi.mocked(cvApi.get).mockImplementation(async id=>savedCv(id));});
describe('saved CV workspace',()=>{
 it('opens a selected CV outside page one and keeps loaded pages and drafts through retry and refresh',async()=>{
  const recent=savedCv('recent-cv'),older=savedCv('older-cv');recent.file_name='recent.pdf';older.file_name='selected-older.pdf';let fail=true;
  vi.mocked(cvApi.list).mockImplementation(async(_token,_signal,cursor)=>{
   if(!cursor)return {cvs:[recent],selection:{cv_id:older.id,version:1},next_cursor:'older-page'};
   if(fail){fail=false;throw new Error('Page connection interrupted.');}
   return {cvs:[recent,older],selection:{cv_id:older.id,version:1},next_cursor:null};
  });
  vi.mocked(cvApi.get).mockImplementation(async id=>id===older.id?older:recent);
  vi.mocked(cvApi.questions).mockImplementation(async()=>clarificationState(older));
  renderWorkspace();await waitFor(()=>expect(screen.getByLabelText('Selected CV')).toHaveTextContent('selected-older.pdf'));
  expect(screen.queryByLabelText('CV older-cv')).not.toBeInTheDocument();expect(cvApi.get).toHaveBeenCalledWith(older.id,'synthetic-session',expect.any(AbortSignal));
  const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());fireEvent.change(input,{target:{value:'A draft while browsing.'}});
  fireEvent.click(screen.getByRole('button',{name:'Show more saved CVs'}));expect(await screen.findByRole('alert')).toHaveTextContent('Page connection interrupted.');expect(screen.getByLabelText('CV recent-cv')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Show more saved CVs'}));await screen.findByLabelText('CV older-cv');expect(screen.getAllByLabelText('CV recent-cv')).toHaveLength(1);expect(screen.queryByRole('button',{name:'Show more saved CVs'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Refresh saved status'}));await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(5));
  expect(screen.getByLabelText('CV older-cv')).toBeVisible();expect(input).toHaveValue('A draft while browsing.');expect(cvApi.select).not.toHaveBeenCalled();
 });
 it('ignores a delayed older page after a new saved-status refresh',async()=>{
  const recent=savedCv('recent-cv'),obsolete=savedCv('obsolete-page-cv');let resolve!:(value:CvList)=>void;
  vi.mocked(cvApi.list).mockImplementation(async(_token,_signal,cursor)=>cursor?new Promise(done=>resolve=done):{cvs:[recent],selection:{cv_id:null,version:0},next_cursor:'older-page'});
  renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'Show more saved CVs'}));await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole('button',{name:'Refresh saved status'}));await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(3));
  await act(async()=>resolve({cvs:[obsolete],selection:{cv_id:null,version:0},next_cursor:null}));
  expect(screen.queryByLabelText('CV obsolete-page-cv')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Show more saved CVs'})).toBeEnabled();
 });
 it('prepares the selected target context and reloads the new CV version before answering',async()=>{
  const detail=savedCv();let prepared=false;
  const updated={...detail,version:4,clarifications:[{id:'question-python',item_id:detail.items[0].id,kind:'project' as const,question:'Which Python work was yours?',uncertainty_key:'contribution',status:'unanswered' as const,answer:null,career_target_id:confirmedTarget.id,career_target_version:confirmedTarget.version}]};
  vi.mocked(cvApi.list).mockResolvedValue({cvs:[detail],selection:{cv_id:detail.id,version:1}});
  vi.mocked(cvApi.get).mockImplementation(async()=>prepared?updated:detail);
  vi.mocked(cvApi.questions).mockImplementation(async()=>clarificationState(prepared?updated:detail,confirmedTarget,prepared));
  vi.mocked(cvApi.prepare).mockImplementation(async()=>{prepared=true;return clarificationState(updated,confirmedTarget,true);});
  vi.mocked(cvApi.answer).mockResolvedValue({...updated,version:5,clarifications:[{...updated.clarifications[0],status:'answered',answer:'I cleaned data in Python.'}]});
  renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'Prepare relevant questions'}));
  const input=await screen.findByRole('textbox',{name:'Your explanation'});await waitFor(()=>expect(input).toBeEnabled());
  expect(vi.mocked(cvApi.prepare).mock.calls[0][1]).toMatchObject({expected_version:1,career_target_id:confirmedTarget.id,career_target_version:1,career_target_selection_version:1});
  fireEvent.change(input,{target:{value:'I cleaned data in Python.'}});fireEvent.click(screen.getByRole('button',{name:'Save explanation'}));
  await waitFor(()=>expect(cvApi.answer).toHaveBeenCalled());expect(vi.mocked(cvApi.answer).mock.calls[0][2]).toMatchObject({expected_version:4,answer:'I cleaned data in Python.'});
 });
 it('ignores a delayed prepare after the user reviews another CV',async()=>{
  const first=savedCv('cv-one'),second=savedCv('cv-two');second.items[0].title='Second project';
  vi.mocked(cvApi.list).mockResolvedValue({cvs:[first,second],selection:{cv_id:first.id,version:1}});
  vi.mocked(cvApi.get).mockImplementation(async id=>id===first.id?first:second);
  vi.mocked(cvApi.questions).mockImplementation(async id=>clarificationState(id===first.id?first:second,confirmedTarget));
  let finish!:(value:ReturnType<typeof clarificationState>)=>void;vi.mocked(cvApi.prepare).mockImplementation(()=>new Promise(done=>finish=done));
  renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'Prepare relevant questions'}));
  fireEvent.click(within(screen.getByLabelText('CV cv-two')).getByRole('button',{name:'Review CV'}));await screen.findByRole('heading',{name:'Second project'});
  await act(async()=>finish(clarificationState({...first,version:2},confirmedTarget,true)));
  expect(within(screen.getByLabelText('CV review')).getByRole('heading',{name:'Second project'})).toBeVisible();
  expect(within(screen.getByLabelText('CV review')).queryByRole('heading',{name:'Team dashboard'})).not.toBeInTheDocument();
 });
 it('retains the preparation identity after a response is interrupted',async()=>{
  const detail=savedCv();vi.mocked(cvApi.list).mockResolvedValue({cvs:[detail],selection:{cv_id:detail.id,version:1}});vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(detail,confirmedTarget));vi.mocked(cvApi.prepare).mockRejectedValue(new Error('Response interrupted.'));
  renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'Prepare relevant questions'}));await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'Prepare relevant questions'}));await waitFor(()=>expect(cvApi.prepare).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.prepare).mock.calls[0][1]).toEqual(vi.mocked(cvApi.prepare).mock.calls[1][1]);
 });
 it('keeps unavailable context distinct from having no confirmed target',async()=>{
  const detail=savedCv();vi.mocked(cvApi.list).mockResolvedValue({cvs:[detail],selection:{cv_id:detail.id,version:1}});vi.mocked(cvApi.questions).mockRejectedValue(new Error('Career unavailable'));
  renderWorkspace();expect(await screen.findByRole('button',{name:'Retry clarification context'})).toBeEnabled();expect(screen.queryByRole('button',{name:'Prepare relevant questions'})).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Team dashboard'})).toBeVisible();
  vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(detail));fireEvent.click(screen.getByRole('button',{name:'Retry clarification context'}));await screen.findByText(/Confirm and select a career target before preparing/);expect(screen.queryByRole('button',{name:'Retry clarification context'})).not.toBeInTheDocument();
 });
 it('does not replace a newly viewed CV with a late save from another source',async()=>{
  const first=savedCv('cv-one'),second=savedCv('cv-two');second.items[0].title='Independent project';
  vi.mocked(cvApi.list).mockResolvedValue({cvs:[first,second],selection:{cv_id:first.id,version:1}});
  vi.mocked(cvApi.get).mockImplementation(async id=>id===first.id?first:second);
  let resolve!:(value:CvDetail)=>void;vi.mocked(cvApi.edit).mockImplementation(()=>new Promise(done=>resolve=done));
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
  try{
   renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'Edit or remove Team dashboard'}));
   fireEvent.change(screen.getByRole('textbox',{name:'Description'}),{target:{value:'My saved contribution'}});
   fireEvent.click(screen.getByRole('button',{name:'Save correction'}));
   await waitFor(()=>expect(cvApi.edit).toHaveBeenCalled());
   fireEvent.click(within(screen.getByLabelText('CV cv-two')).getByRole('button',{name:'Review CV'}));
   await screen.findByRole('heading',{name:'Independent project'});
   await act(async()=>resolve({...first,version:2,items:first.items.map(item=>({...item,description:'My saved contribution'}))}));
   expect(within(screen.getByLabelText('CV review')).getByRole('heading',{name:'Independent project'})).toBeVisible();
   expect(screen.getByLabelText('Selected CV')).toHaveTextContent('cv-one');
  }finally{confirm.mockRestore();}
 });
 it('allows manual capability entry with no CV and no invented readiness',async()=>{renderWorkspace();await screen.findByRole('heading',{name:'No saved CV yet'});expect(screen.getByRole('textbox',{name:'Capability name'})).toBeEnabled();expect(screen.getByText('No CV selected. Uploading a file does not select it. Choose a ready CV below.')).toBeVisible();expect(screen.queryByText('Readiness')).not.toBeInTheDocument();expect(cvApi.select).not.toHaveBeenCalled();});
 it('shows policy limits and rejects unsupported or oversized files before uploading',async()=>{renderWorkspace();const input=await screen.findByLabelText('CV document');fireEvent.change(input,{target:{files:[new File(['text'],'resume.txt')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));expect(await screen.findByRole('alert')).toHaveTextContent('PDF or DOCX');fireEvent.change(input,{target:{files:[new File([new Uint8Array(policy.max_file_bytes+1)],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));expect(screen.getByRole('alert')).toHaveTextContent('10 MiB');expect(cvApi.upload).not.toHaveBeenCalled();});
 it('accepts exactly the policy limit and retains a request identity after an interrupted upload',async()=>{vi.mocked(cvApi.upload).mockRejectedValue(new Error('Connection interrupted.'));renderWorkspace();fireEvent.change(await screen.findByLabelText('CV document'),{target:{files:[new File([new Uint8Array(policy.max_file_bytes)],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'Retry upload'}));await waitFor(()=>expect(cvApi.upload).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.upload).mock.calls[0][0].get('mutation_id')).toBe(vi.mocked(cvApi.upload).mock.calls[1][0].get('mutation_id'));expect(cvApi.select).not.toHaveBeenCalled();});
 it('distinguishes identical filenames and preserves selection on a new upload',async()=>{const first=savedCv('cv-one'),second=savedCv('cv-two');vi.mocked(cvApi.list).mockResolvedValue({cvs:[first,second],selection:{cv_id:first.id,version:3}});vi.mocked(cvApi.upload).mockResolvedValue(second);renderWorkspace();await screen.findByLabelText('CV cv-one');expect(within(screen.getByLabelText('CV cv-one')).getByRole('button',{name:'Selected'})).toBeDisabled();expect(within(screen.getByLabelText('CV cv-two')).getByRole('button',{name:'Select for analysis'})).toBeEnabled();fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));await waitFor(()=>expect(cvApi.upload).toHaveBeenCalled());expect(cvApi.select).not.toHaveBeenCalled();expect(screen.getByLabelText('Selected CV')).toHaveTextContent('cv-one');});
 it('keeps an unsent chat draft and avoids upload when discard confirmation is cancelled',async()=>{
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  try{renderWorkspace();const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());fireEvent.change(input,{target:{value:'My unsent experience.'}});fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));expect(confirm).toHaveBeenCalledWith('Upload this CV and discard unsaved CV or capability drafts?');expect(cvApi.upload).not.toHaveBeenCalled();expect(input).toHaveValue('My unsent experience.');expect(cvApi.openConversation).toHaveBeenCalledTimes(1);}finally{confirm.mockRestore();}
 });
 it('keeps draft discard protection while viewing chat history and restores the draft after cancelling navigation',async()=>{
  const first=savedCv('cv-one'),second=savedCv('cv-two'),current={...emptyConversation,cv_id:first.id,previous_conversation_id:'older-chat'};
  vi.mocked(cvApi.list).mockResolvedValue({cvs:[first,second],selection:{cv_id:first.id,version:1}});
  vi.mocked(cvApi.openConversation).mockResolvedValue(current);
  vi.mocked(cvApi.conversation).mockImplementation(async id=>id==='older-chat'?{...emptyConversation,id,cv_id:first.id,read_only:true}:current);
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  try{
   renderWorkspace();const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
   fireEvent.change(input,{target:{value:'My unsent experience.'}});fireEvent.click(screen.getByRole('button',{name:'Previous conversation'}));
   await screen.findByRole('button',{name:'Return to current conversation'});expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
   fireEvent.click(within(screen.getByLabelText('CV cv-two')).getByRole('button',{name:'Review CV'}));
   expect(confirm).toHaveBeenCalledTimes(1);
   expect(fireEvent.click(within(screen.getByRole('region',{name:'CV conversation'})).getByRole('link',{name:'Open Career Goal'}))).toBe(false);
   expect(confirm).toHaveBeenCalledTimes(2);expect(cvApi.openConversation).toHaveBeenCalledTimes(1);
   fireEvent.click(screen.getByRole('button',{name:'Return to current conversation'}));expect(await screen.findByRole('textbox',{name:'Message elo'})).toHaveValue('My unsent experience.');
  }finally{confirm.mockRestore();}
 });
 it('uploads and opens the new CV conversation only after draft discard is confirmed',async()=>{
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);vi.mocked(cvApi.upload).mockResolvedValue(savedCv('new-cv'));
  try{renderWorkspace();const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());fireEvent.change(input,{target:{value:'My old unsent experience.'}});fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));await waitFor(()=>expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:'new-cv'}),'synthetic-session',expect.any(AbortSignal)));expect(confirm).toHaveBeenCalledTimes(1);expect(cvApi.upload).toHaveBeenCalledTimes(1);expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('');}finally{confirm.mockRestore();}
 });
 it('clears private drafts and ignores late results across accounts',async()=>{const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);try{let resolve!:(value:CvDetail)=>void;vi.mocked(cvApi.upload).mockImplementation(()=>new Promise(r=>resolve=r));const view=renderWorkspace();fireEvent.change(await screen.findByRole('textbox',{name:'Capability name'}),{target:{value:'Private owner A'}});fireEvent.change(await screen.findByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));session.account={id:'owner-b'};session.token='owner-b-token';view.rerender(<ResumePreview/>);fireEvent.click(screen.getByText('Your CV summary',{selector:'summary span'}));await act(async()=>resolve(savedCv('owner-a-cv')));expect(await screen.findByRole('textbox',{name:'Capability name'})).toHaveValue('');expect(screen.queryByText(/owner-a-cv/)).not.toBeInTheDocument();}finally{confirm.mockRestore();}});
 it('reuploads an expired source using its exact CV and version while retaining the previous result',async()=>{const failed={...savedCv(),status:'failed' as const,source_available:false,error:{code:'expired',message:'Original expired.',retryable:false}};vi.mocked(cvApi.list).mockResolvedValue({cvs:[failed],selection:{cv_id:failed.id,version:1}});vi.mocked(cvApi.get).mockResolvedValue(failed);vi.mocked(cvApi.upload).mockResolvedValue({...failed,status:'queued'});renderWorkspace();await screen.findByRole('heading',{name:'Previous saved extraction'});expect(screen.getByRole('button',{name:'Edit or remove Team dashboard'})).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'Re-upload this source'}));fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Re-upload same source'}));await waitFor(()=>expect(cvApi.upload).toHaveBeenCalled());const form=vi.mocked(cvApi.upload).mock.calls[0][0];expect(form.get('cv_id')).toBe(failed.id);expect(form.get('expected_version')).toBe(String(failed.version));expect(cvApi.select).not.toHaveBeenCalled();});
 it('keeps manual capability entry available when CV service fails',async()=>{vi.mocked(cvApi.policy).mockRejectedValue(new Error('CV unavailable'));vi.mocked(cvApi.list).mockRejectedValue(new Error('CV unavailable'));renderWorkspace();expect(await screen.findByRole('textbox',{name:'Capability name'})).toBeEnabled();expect(await screen.findByRole('button',{name:'Retry saved CVs'})).toBeEnabled();});
});
describe('effective review and corrections',()=>{
 function review(detail=savedCv(),onSaved=vi.fn(),refresh=vi.fn().mockResolvedValue(undefined)){return <CvReview detail={detail} policy={policy} questions={clarificationState(detail,confirmedTarget,true)} token="token" signal={new AbortController().signal} onSaved={onSaved} refresh={refresh}/>;}
 it('shows provenance, unknown values, evidence and neutral missing sections',()=>{const detail=savedCv();detail.items.push({...detail.items[0],id:'removed',title:'Removed claim',removed:true});render(review(detail));expect(screen.getAllByText('Not found in this CV.')).toHaveLength(2);expect(screen.getByText('Inferred · uncertain')).toBeVisible();expect(screen.getByText('Proficiency: Unknown · Experience: Unknown')).toBeVisible();expect(screen.queryByText('Removed claim')).not.toBeInTheDocument();expect(screen.getAllByText('Page 1')).toHaveLength(2);});
 it('preserves failed correction drafts and retries with the same mutation ID',async()=>{vi.mocked(cvApi.edit).mockRejectedValue(new Error('Save interrupted'));render(review());fireEvent.click(screen.getByRole('button',{name:'Edit or remove Team dashboard'}));fireEvent.change(screen.getByRole('textbox',{name:'Description'}),{target:{value:'I cleaned the data only.'}});fireEvent.click(screen.getByRole('button',{name:'Save correction'}));await screen.findByRole('alert');expect(screen.getByRole('textbox',{name:'Description'})).toHaveValue('I cleaned the data only.');fireEvent.click(screen.getByRole('button',{name:'Save correction'}));await waitFor(()=>expect(cvApi.edit).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.edit).mock.calls[0][2].mutation_id).toBe(vi.mocked(cvApi.edit).mock.calls[1][2].mutation_id);});
 it('holds stale drafts until the user explicitly reconciles refreshed evidence',async()=>{vi.mocked(cvApi.edit).mockRejectedValue(new CvApiError('Source changed',409));const detail=savedCv(),refresh=vi.fn().mockResolvedValue(undefined);const view=render(review(detail,vi.fn(),refresh));fireEvent.click(screen.getByRole('button',{name:'Edit or remove Team dashboard'}));fireEvent.change(screen.getByRole('textbox',{name:'Description'}),{target:{value:'My safe draft'}});fireEvent.click(screen.getByRole('button',{name:'Save correction'}));await screen.findByRole('alert');expect(refresh).toHaveBeenCalled();view.rerender(review({...detail,version:2},vi.fn(),refresh));expect(screen.getByRole('button',{name:'Save correction'})).toBeDisabled();expect(screen.getByRole('textbox',{name:'Description'})).toHaveValue('My safe draft');fireEvent.click(screen.getByRole('button',{name:'Keep draft against refreshed version'}));expect(screen.getByRole('button',{name:'Save correction'})).toBeEnabled();});
 it('does not mutate when cancelling an edit',()=>{render(review());fireEvent.click(screen.getByRole('button',{name:'Edit or remove Team dashboard'}));fireEvent.change(screen.getByRole('textbox',{name:'Name'}),{target:{value:'Changed'}});fireEvent.click(screen.getByRole('button',{name:'Cancel edit'}));expect(cvApi.edit).not.toHaveBeenCalled();expect(screen.getByRole('heading',{name:'Team dashboard'})).toBeVisible();});
 it('defers unanswered questions without usable confirmed context and marks changed support uncertain',()=>{const detail=savedCv();detail.items[1].support_uncertain=true;detail.clarifications=[{id:'q',item_id:detail.items[0].id,kind:'project',question:'What did you build?',uncertainty_key:'contribution',status:'unanswered',answer:null,career_target_id:'old-target',career_target_version:1}];render(<CvReview detail={detail} policy={policy} questions={clarificationState(detail)} token="token" signal={new AbortController().signal} onSaved={vi.fn()} refresh={vi.fn()}/>);expect(screen.queryByRole('button',{name:'Skip and continue'})).not.toBeInTheDocument();expect(screen.getByText('Supporting contribution is uncertain or changed. This claim is not treated as demonstrated capability.')).toBeVisible();});
 it('allows blank clarification skip without treating uncertainty as absent',async()=>{const detail=savedCv();detail.clarifications=[{id:'q',item_id:detail.items[0].id,kind:'project',question:'What did you personally build?',uncertainty_key:'contribution',status:'unanswered',answer:null,career_target_id:'target',career_target_version:1}];vi.mocked(cvApi.answer).mockResolvedValue({...detail,version:2,clarifications:[{...detail.clarifications[0],status:'skipped'}]});const onSaved=vi.fn();render(review(detail,onSaved));expect(screen.getByRole('button',{name:'Save explanation'})).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'Skip and continue'}));await waitFor(()=>expect(onSaved).toHaveBeenCalled());expect(vi.mocked(cvApi.answer).mock.calls[0][2]).toMatchObject({action:'skip',expected_version:1});expect(vi.mocked(cvApi.answer).mock.calls[0][2]).not.toHaveProperty('answer');});
 it('filters pending questions by current target while keeping answered and skipped history',()=>{
  const detail=savedCv(),base={item_id:detail.items[0].id,kind:'project' as const,uncertainty_key:'contribution',career_target_id:'old-target',career_target_version:1};detail.clarifications=[{...base,id:'active',question:'Relevant Python work?',status:'unanswered',answer:null},{...base,id:'irrelevant',question:'Old unrelated work?',status:'unanswered',answer:null},{...base,id:'answered',question:'Previous explanation?',status:'answered',answer:'I cleaned the data.'},{...base,id:'skipped',question:'Previous uncertainty?',status:'skipped',answer:null}];
  const props={detail,policy,token:'token',signal:new AbortController().signal,onSaved:vi.fn(),refresh:vi.fn()};
  const view=render(<CvReview {...props} questions={{...clarificationState(detail,confirmedTarget,true),questions:[detail.clarifications[0]]}}/>);
  expect(screen.getByRole('heading',{name:'Relevant Python work?'})).toBeVisible();expect(screen.queryByRole('heading',{name:'Old unrelated work?'})).not.toBeInTheDocument();expect(screen.getByText('I cleaned the data.')).toBeVisible();expect(screen.getByRole('button',{name:'Answer voluntarily'})).toBeVisible();
  view.rerender(<CvReview {...props} questions={{...clarificationState(detail,{...confirmedTarget,id:'different-target',role:'Design researcher',selection_version:2},true),questions:[]}}/>);
  expect(screen.queryByRole('heading',{name:'Relevant Python work?'})).not.toBeInTheDocument();expect(screen.getByText('I cleaned the data.')).toBeVisible();expect(screen.getByText(/No relevant clarification questions are pending for this target/)).toBeVisible();expect(screen.getByRole('button',{name:'Answer voluntarily'})).toBeVisible();
 });
 it('disables clarification writes until the CV and question versions agree',()=>{
  const detail=savedCv();detail.clarifications=[{id:'q',item_id:detail.items[0].id,kind:'project',question:'What did you build?',uncertainty_key:'contribution',status:'unanswered',answer:null,career_target_id:confirmedTarget.id,career_target_version:1}];
  render(<CvReview detail={detail} policy={policy} questions={{...clarificationState(detail,confirmedTarget,true),cv_version:2}} token="token" signal={new AbortController().signal} onSaved={vi.fn()} refresh={vi.fn()}/>);
  expect(screen.getByRole('textbox',{name:'Your explanation'})).toBeDisabled();expect(screen.getByRole('button',{name:'Skip and continue'})).toBeDisabled();
 });
 it('retains a clarification draft while unavailable context is retried',()=>{
  const detail=savedCv();detail.clarifications=[{id:'q',item_id:detail.items[0].id,kind:'project',question:'What did you build?',uncertainty_key:'contribution',status:'unanswered',answer:null,career_target_id:confirmedTarget.id,career_target_version:1}];
  const props={detail,policy,token:'token',signal:new AbortController().signal,onSaved:vi.fn(),refresh:vi.fn()};const questions=clarificationState(detail,confirmedTarget,true);
  const view=render(<CvReview {...props} questions={questions}/>);fireEvent.change(screen.getByRole('textbox',{name:'Your explanation'}),{target:{value:'My unsaved contribution'}});
  view.rerender(<CvReview {...props} questions={null}/>);expect(screen.queryByRole('textbox',{name:'Your explanation'})).not.toBeInTheDocument();
  view.rerender(<CvReview {...props} questions={questions}/>);expect(screen.getByRole('textbox',{name:'Your explanation'})).toHaveValue('My unsaved contribution');
 });
});
describe('manual capability matches',()=>{
 it('holds an attachment draft when the selected CV evidence changes',()=>{const cv=savedCv(),props={data:emptyDeclarations,token:'token',signal:new AbortController().signal,onSaved:vi.fn(),refresh:vi.fn()};const view=render(<CapabilityDeclarations {...props} selectedCv={cv}/>);fireEvent.change(screen.getByRole('textbox',{name:'Capability name'}),{target:{value:'Python'}});fireEvent.change(screen.getByRole('textbox',{name:'Capability description'}),{target:{value:'My own data cleaning work'}});fireEvent.click(screen.getByRole('radio',{name:/Attach to CV evidence/}));view.rerender(<CapabilityDeclarations {...props} selectedCv={{...cv,version:2}}/>);expect(screen.getByRole('button',{name:'Add capability'})).toBeDisabled();expect(screen.getByRole('textbox',{name:'Capability description'})).toHaveValue('My own data cleaning work');fireEvent.click(screen.getByRole('button',{name:'Keep capability draft against refreshed version'}));expect(screen.getByRole('button',{name:'Add capability'})).toBeDisabled();fireEvent.click(screen.getByRole('radio',{name:/Attach to CV evidence/}));expect(screen.getByRole('button',{name:'Add capability'})).toBeEnabled();});
 it('requires an explicit attach or distinct choice for same-name CV evidence',async()=>{const cv=savedCv();vi.mocked(cvApi.addDeclaration).mockResolvedValue({...emptyDeclarations,version:1});render(<CapabilityDeclarations data={emptyDeclarations} selectedCv={cv} token="token" signal={new AbortController().signal} onSaved={vi.fn()} refresh={vi.fn()}/>);fireEvent.change(screen.getByRole('textbox',{name:'Capability name'}),{target:{value:'  python  '}});fireEvent.change(screen.getByRole('textbox',{name:'Capability description'}),{target:{value:'I used pandas for cleaning.'}});expect(screen.getByRole('button',{name:'Add capability'})).toBeDisabled();fireEvent.click(screen.getByRole('radio',{name:/Attach to CV evidence/}));fireEvent.click(screen.getByRole('button',{name:'Add capability'}));await waitFor(()=>expect(cvApi.addDeclaration).toHaveBeenCalled());expect(vi.mocked(cvApi.addDeclaration).mock.calls[0][0]).toMatchObject({mode:'attach',cv_match:{cv_id:cv.id,item_id:cv.items[1].id,cv_version:1}});});
});

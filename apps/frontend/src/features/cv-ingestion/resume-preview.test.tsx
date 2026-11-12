vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: vi.fn(async (path: string) => path === '/context' ? {ready:false,model_available:true,issues:[]} : {version:0,stale:false,result:null,operation:null,ready:false,issues:[]})}));
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
function renderWorkspace(){const view=render(<ResumePreview/>);return view;}
beforeEach(()=>{window.history.replaceState(null,'','/cv');vi.clearAllMocks();vi.mocked(cvApi.select).mockImplementation(async body=>({cv_id:body.cv_id,version:body.expected_version+1}));vi.mocked(cvApi.skillsProfile).mockResolvedValue({version:0,status:'empty',saved_at:null,areas:{},entries:[]});vi.mocked(cvApi.openConversation).mockImplementation(async body=>({...emptyConversation,cv_id:body.cv_id}));vi.mocked(cvApi.sendMessage).mockImplementation(async(id)=>({...emptyConversation,id,revision:2,active_question:{id:'start',item_id:'work',title:'Work',question:'Tell me about your experience.'}}));session.token='synthetic-session';session.account={id:'owner-a'};vi.mocked(cvApi.policy).mockResolvedValue(policy);vi.mocked(cvApi.list).mockResolvedValue({cvs:[],selection:{cv_id:null,version:0}});vi.mocked(cvApi.declarations).mockResolvedValue(emptyDeclarations);vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(savedCv()));vi.mocked(cvApi.get).mockImplementation(async id=>savedCv(id));});
describe('saved CV workspace',()=>{
 it('opens the extracted results page from View extracted results and offers no corrections section',async()=>{
  const cv=savedCv('cv-one');vi.mocked(cvApi.list).mockResolvedValue({cvs:[cv],selection:{cv_id:cv.id,version:1}});vi.mocked(cvApi.get).mockResolvedValue(cv);
  renderWorkspace();expect(screen.queryByText('CV details and corrections')).toBeNull();
  fireEvent.click(await screen.findByRole('button',{name:'View extracted results'}));
  expect(await screen.findByRole('heading',{name:'Extracted results'})).toBeInTheDocument();
  expect(window.location.search).toContain('cv=cv-one');
  fireEvent.click(screen.getByRole('button',{name:'Skills Profile'}));
  await waitFor(()=>expect(screen.queryByRole('heading',{name:'Extracted results'})).toBeNull());
  expect(window.location.search).not.toContain('cv=');
 });
 it('deletes the confirmed selected CV and clears its review while retaining other files and manual capabilities',async()=>{
  const first=savedCv('cv-one'),second=savedCv('cv-two');let deleted=false;
  vi.mocked(cvApi.list).mockImplementation(async()=>({cvs:deleted?[second]:[first,second],selection:{cv_id:deleted?null:first.id,version:deleted?2:1}}));
  vi.mocked(cvApi.delete).mockImplementation(async()=>{deleted=true;return {cv_id:first.id,deleted:true,selection:{cv_id:null,version:2}};});
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
  try{
   renderWorkspace();const row=await screen.findByLabelText('CV cv-one');
   fireEvent.click(within(row).getByRole('button',{name:'Delete CV'}));
   await waitFor(()=>expect(screen.queryByLabelText('CV cv-one')).not.toBeInTheDocument());
   expect(screen.queryByText('Manage saved CVs')).toBeNull();expect(screen.getByLabelText('CV cv-two')).toBeVisible();expect(screen.getByLabelText('Selected CV')).toHaveTextContent('No active CV yet');
   expect(cvApi.delete).toHaveBeenCalledWith(first.id,expect.objectContaining({expected_version:first.version,mutation_id:expect.any(String)}),'synthetic-session',expect.any(AbortSignal));
   expect(confirm).toHaveBeenCalledWith(expect.stringContaining('CV cv-one'));
   await waitFor(()=>expect(cvApi.select).toHaveBeenCalledWith(expect.objectContaining({cv_id:'cv-two'}),'synthetic-session',expect.any(AbortSignal)));
   expect(cvApi.openConversation).not.toHaveBeenCalled();
  }finally{confirm.mockRestore();}
 });
 it('does not delete when confirmation is cancelled',async()=>{
  const cv=savedCv();vi.mocked(cvApi.list).mockResolvedValue({cvs:[cv],selection:{cv_id:null,version:0}});
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  try{renderWorkspace();fireEvent.click(within(await screen.findByLabelText(`CV ${cv.id}`)).getByRole('button',{name:'Delete CV'}));expect(cvApi.delete).not.toHaveBeenCalled();expect(screen.getByLabelText(`CV ${cv.id}`)).toBeVisible();}finally{confirm.mockRestore();}
 });
 it('retains a deletion request identity after an interrupted response',async()=>{
  const cv=savedCv();let deleted=false;
  vi.mocked(cvApi.list).mockImplementation(async()=>({cvs:deleted?[]:[cv],selection:{cv_id:deleted?null:cv.id,version:deleted?2:1}}));
  vi.mocked(cvApi.delete).mockRejectedValueOnce(new Error('Deletion response interrupted.')).mockImplementationOnce(async()=>{deleted=true;return {cv_id:cv.id,deleted:true,selection:{cv_id:null,version:0}};});
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
  try{renderWorkspace();fireEvent.click(within(await screen.findByLabelText(`CV ${cv.id}`)).getByRole('button',{name:'Delete CV'}));await screen.findByRole('alert');fireEvent.click(within(screen.getByLabelText(`CV ${cv.id}`)).getByRole('button',{name:'Delete CV'}));await waitFor(()=>expect(cvApi.delete).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.delete).mock.calls[0][1]).toEqual(vi.mocked(cvApi.delete).mock.calls[1][1]);await screen.findByRole('heading',{name:'Upload your CV'});}finally{confirm.mockRestore();}
 });
 it('refreshes a stale CV before another confirmed deletion attempt',async()=>{
  const cv=savedCv();let changed=false;
  vi.mocked(cvApi.list).mockImplementation(async()=>({cvs:[{...cv,version:changed?cv.version+1:cv.version}],selection:{cv_id:cv.id,version:1}}));
  vi.mocked(cvApi.delete).mockImplementation(async()=>{changed=true;throw new CvApiError('This CV changed; review it again.',409);});
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);
  try{renderWorkspace();fireEvent.click(within(await screen.findByLabelText(`CV ${cv.id}`)).getByRole('button',{name:'Delete CV'}));await screen.findByRole('alert');await waitFor(()=>expect(within(screen.getByLabelText(`CV ${cv.id}`)).getByRole('button',{name:'Delete CV'})).toBeEnabled());fireEvent.click(within(screen.getByLabelText(`CV ${cv.id}`)).getByRole('button',{name:'Delete CV'}));await waitFor(()=>expect(cvApi.delete).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.delete).mock.calls[1][1].expected_version).toBe(cv.version+1);}finally{confirm.mockRestore();}
 });
 it('opens a selected CV outside page one and keeps loaded pages and drafts through retry and refresh',async()=>{
  const recent=savedCv('recent-cv'),older=savedCv('older-cv');recent.file_name='recent.pdf';recent.status='failed';older.file_name='selected-older.pdf';let fail=true;
  vi.mocked(cvApi.list).mockImplementation(async(_token,_signal,cursor)=>{
   if(!cursor)return {cvs:[recent],selection:{cv_id:older.id,version:1},next_cursor:'older-page'};
   if(fail){fail=false;throw new Error('Page connection interrupted.');}
   return {cvs:[recent,older],selection:{cv_id:older.id,version:1},next_cursor:null};
  });
  vi.mocked(cvApi.get).mockImplementation(async id=>id===older.id?older:recent);
  vi.mocked(cvApi.questions).mockImplementation(async()=>clarificationState(older));
  renderWorkspace();await waitFor(()=>expect(screen.getByLabelText('Selected CV')).toHaveTextContent('selected-older.pdf'));
  expect(screen.queryByLabelText('CV older-cv')).not.toBeInTheDocument();expect(cvApi.get).toHaveBeenCalledWith(older.id,'synthetic-session',expect.any(AbortSignal));
  fireEvent.click(screen.getByRole('button',{name:/Build through chat|Add skills by chat/}));const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());fireEvent.change(input,{target:{value:'A draft while browsing.'}});fireEvent.click(screen.getByRole('button',{name:'Back to Skills Profile'}));
  fireEvent.click(screen.getByRole('button',{name:'Show more saved CVs'}));expect(await screen.findByRole('alert')).toHaveTextContent('Page connection interrupted.');expect(screen.getByLabelText('CV recent-cv')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Show more saved CVs'}));await screen.findByLabelText('CV older-cv');expect(screen.getAllByLabelText('CV recent-cv')).toHaveLength(1);expect(screen.queryByRole('button',{name:'Show more saved CVs'})).not.toBeInTheDocument();
  fireEvent(window,new Event('focus'));await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(5));
  expect(screen.getByLabelText('CV older-cv')).toBeVisible();expect(input).toHaveValue('A draft while browsing.');expect(cvApi.select).not.toHaveBeenCalled();
 });
 it('ignores a delayed older page after a new saved-status refresh',async()=>{
  const recent=savedCv('recent-cv'),obsolete=savedCv('obsolete-page-cv');let resolve!:(value:CvList)=>void;
  vi.mocked(cvApi.list).mockImplementation(async(_token,_signal,cursor)=>cursor?new Promise(done=>resolve=done):{cvs:[recent],selection:{cv_id:recent.id,version:1},next_cursor:'older-page'});
  renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'Show more saved CVs'}));await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(2));
  fireEvent(window,new Event('focus'));await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(3));
  await act(async()=>resolve({cvs:[obsolete],selection:{cv_id:null,version:0},next_cursor:null}));
  expect(screen.queryByLabelText('CV obsolete-page-cv')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Show more saved CVs'})).toBeEnabled();
 });
 it('turns the upload panel into a clear selected state once a file is chosen',async()=>{renderWorkspace();expect(await screen.findByRole('heading',{name:'Upload your CV'})).toBeVisible();fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['text'],'my-resume.pdf')]}});expect(screen.getByRole('heading',{name:'CV selected'})).toBeVisible();expect(screen.getByText('my-resume.pdf')).toBeVisible();expect(screen.queryByRole('heading',{name:'Upload your CV'})).toBeNull();});
 it('makes the most recent ready upload the active CV without asking',async()=>{const older={...savedCv('older-cv'),created_at:'2000-01-01T00:00:00Z'},newest={...savedCv('newest-cv'),created_at:'2099-01-01T00:00:00Z'};vi.mocked(cvApi.list).mockResolvedValue({cvs:[older,newest],selection:{cv_id:older.id,version:4}});const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);try{renderWorkspace();await waitFor(()=>expect(cvApi.select).toHaveBeenCalledWith(expect.objectContaining({cv_id:'newest-cv',expected_version:4}),'synthetic-session',expect.any(AbortSignal)));expect(cvApi.select).toHaveBeenCalledTimes(1);expect(confirm).not.toHaveBeenCalled();}finally{confirm.mockRestore();}});
 it('shows policy limits and rejects unsupported or oversized files before uploading',async()=>{renderWorkspace();const input=await screen.findByLabelText('CV document');fireEvent.change(input,{target:{files:[new File(['text'],'resume.txt')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));expect(await screen.findByRole('alert')).toHaveTextContent('PDF or DOCX');fireEvent.change(input,{target:{files:[new File([new Uint8Array(policy.max_file_bytes+1)],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));expect(screen.getByRole('alert')).toHaveTextContent('10 MiB');expect(cvApi.upload).not.toHaveBeenCalled();});
 it('accepts exactly the policy limit and retains a request identity after an interrupted upload',async()=>{vi.mocked(cvApi.upload).mockRejectedValue(new Error('Connection interrupted.'));renderWorkspace();fireEvent.change(await screen.findByLabelText('CV document'),{target:{files:[new File([new Uint8Array(policy.max_file_bytes)],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'Retry upload'}));await waitFor(()=>expect(cvApi.upload).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.upload).mock.calls[0][0].get('mutation_id')).toBe(vi.mocked(cvApi.upload).mock.calls[1][0].get('mutation_id'));expect(cvApi.select).not.toHaveBeenCalled();});
 it('distinguishes identical filenames and preserves selection on a new upload',async()=>{const first=savedCv('cv-one'),second=savedCv('cv-two');vi.mocked(cvApi.list).mockResolvedValue({cvs:[first,second],selection:{cv_id:first.id,version:3}});vi.mocked(cvApi.upload).mockResolvedValue(second);renderWorkspace();await screen.findByLabelText('CV cv-one');expect(within(screen.getByLabelText('CV cv-one')).getByText('Active CV')).toBeVisible();expect(within(screen.getByLabelText('CV cv-one')).queryByRole('button',{name:'Make active'})).not.toBeInTheDocument();expect(within(screen.getByLabelText('CV cv-two')).getByRole('button',{name:'Make active'})).toBeEnabled();fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));await waitFor(()=>expect(cvApi.upload).toHaveBeenCalled());expect(cvApi.select).not.toHaveBeenCalled();fireEvent.click(await screen.findByRole('button',{name:'Save and review later'}));expect(screen.getByLabelText('Selected CV')).toHaveTextContent('cv-one');});
 it('keeps an unsent chat draft and avoids upload when discard confirmation is cancelled',async()=>{
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  try{window.history.replaceState(null,'','/cv?review=manual');renderWorkspace();const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());fireEvent.change(input,{target:{value:'My unsent experience.'}});fireEvent.click(screen.getByRole('button',{name:'Back to Skills Profile'}));fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));expect(confirm).toHaveBeenCalledWith('Upload this CV and discard unsaved CV or capability drafts?');expect(cvApi.upload).not.toHaveBeenCalled();expect(input).toHaveValue('My unsent experience.');expect(cvApi.openConversation).toHaveBeenCalledTimes(1);}finally{confirm.mockRestore();}
 });
 it('keeps draft discard protection while viewing chat history and restores the draft after cancelling navigation',async()=>{
  const first=savedCv('cv-one'),second=savedCv('cv-two'),current={...emptyConversation,cv_id:first.id,previous_conversation_id:'older-chat',active_question:{id:'existing',item_id:first.items[0].id,title:'Existing topic',question:'What did you do?'}};
  vi.mocked(cvApi.list).mockResolvedValue({cvs:[first,second],selection:{cv_id:first.id,version:1}});
  vi.mocked(cvApi.openConversation).mockResolvedValue(current);
  vi.mocked(cvApi.conversation).mockImplementation(async id=>id==='older-chat'?{...emptyConversation,id,cv_id:first.id,read_only:true}:current);
  const confirm=vi.spyOn(window,'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true).mockReturnValue(false);
  try{
   renderWorkspace();fireEvent.click(within(await screen.findByLabelText('CV cv-one')).getByRole('button',{name:'Review CV'}));const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
   fireEvent.change(input,{target:{value:'My unsent experience.'}});fireEvent.click(screen.getByRole('button',{name:'Previous conversation'}));
   await screen.findByRole('button',{name:'Return to current conversation'});expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
   fireEvent.click(screen.getByRole('button',{name:'Save and review later'}));
   expect(screen.getByRole('region',{name:'CV conversation'})).toBeVisible();
   fireEvent.click(screen.getByRole('button',{name:'Save and review later'}));
   fireEvent.click(within(screen.getByLabelText('CV cv-two')).getByRole('button',{name:'Review CV'}));
   fireEvent.click(within(screen.getByLabelText('CV cv-one')).getByRole('button',{name:'Review CV'}));
   expect(confirm).toHaveBeenCalledTimes(3);
   expect(within(screen.getByRole('region',{name:'CV conversation'})).queryByRole('link',{name:'Open Career Goal'})).not.toBeInTheDocument();
   expect(cvApi.openConversation).toHaveBeenCalledTimes(1);
   fireEvent.click(screen.getByRole('button',{name:'Return to current conversation'}));expect(await screen.findByRole('textbox',{name:'Message elo'})).toHaveValue('My unsent experience.');
  }finally{confirm.mockRestore();}
 });
 it('uploads after draft discard is confirmed and opens its review automatically',async()=>{
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(true);vi.mocked(cvApi.upload).mockResolvedValue(savedCv('new-cv'));
  try{
   window.history.replaceState(null,'','/cv?review=manual');renderWorkspace();
   const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
   fireEvent.change(input,{target:{value:'My old unsent experience.'}});fireEvent.click(screen.getByRole('button',{name:'Back to Skills Profile'}));
   fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});
   fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));
   await waitFor(()=>expect(cvApi.upload).toHaveBeenCalledTimes(1));
   await waitFor(()=>expect(cvApi.openConversation).toHaveBeenLastCalledWith(expect.objectContaining({cv_id:'new-cv',purpose:'skills_profile'}),'synthetic-session',expect.any(AbortSignal)));
   expect(confirm).toHaveBeenCalledTimes(1);expect(cvApi.select).not.toHaveBeenCalled();
   expect(await screen.findByRole('textbox',{name:'Message elo'})).toHaveValue('');
  }finally{confirm.mockRestore();}
 });
 it('reuploads an expired source using its exact CV and version while retaining the previous result',async()=>{const failed={...savedCv(),status:'failed' as const,source_available:false,error:{code:'expired',message:'Original expired.',retryable:false}};vi.mocked(cvApi.list).mockResolvedValue({cvs:[failed],selection:{cv_id:failed.id,version:1}});vi.mocked(cvApi.get).mockResolvedValue(failed);vi.mocked(cvApi.upload).mockResolvedValue({...failed,status:'queued'});renderWorkspace();fireEvent.click(await screen.findByRole('button',{name:'View processing status'}));fireEvent.click(await screen.findByRole('button',{name:'Re-upload this source'}));fireEvent.change(screen.getByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Re-upload same source'}));await waitFor(()=>expect(cvApi.upload).toHaveBeenCalled());const form=vi.mocked(cvApi.upload).mock.calls[0][0];expect(form.get('cv_id')).toBe(failed.id);expect(form.get('expected_version')).toBe(String(failed.version));expect(cvApi.select).not.toHaveBeenCalled();});
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

it('opens the uploaded CV review immediately and starts questions only when extraction is ready',async()=>{
 const source={...savedCv('processing-upload'),status:'processing' as const};let complete=false;
 vi.mocked(cvApi.upload).mockResolvedValue(source);
 vi.mocked(cvApi.get).mockImplementation(async()=>complete?{...source,status:'ready'}:source);
 renderWorkspace();fireEvent.change(await screen.findByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));
 await screen.findByRole('progressbar',{name:'Reading your CV'});
 expect(window.location.search).toBe('?review=processing-upload');expect(screen.getByRole('progressbar',{name:'Reading your CV'})).toBeVisible();expect(cvApi.openConversation).not.toHaveBeenCalled();expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Check progress'})).not.toBeInTheDocument();complete=true;
 await waitFor(()=>expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:source.id,purpose:'skills_profile'}),'synthetic-session',expect.any(AbortSignal)),{timeout:6000});
 await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('conversation',expect.objectContaining({command:'review'}),'synthetic-session',expect.any(AbortSignal)));expect(cvApi.select).not.toHaveBeenCalled();
});
it('warns before selecting an unreviewed baseline and respects cancellation',async()=>{
 const current={...savedCv('current'),created_at:'2099-01-01T00:00:00Z',profile_reviewed_effective_version:1};current.profile_reviewed_effective_version=current.effective_version;const source={...savedCv('unreviewed'),created_at:'2000-01-01T00:00:00Z'};vi.mocked(cvApi.list).mockResolvedValue({cvs:[current,source],selection:{cv_id:current.id,version:1}});vi.mocked(cvApi.select).mockResolvedValue({cv_id:source.id,version:2});
 const confirm=vi.spyOn(window,'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
 try{renderWorkspace();const button=within(await screen.findByLabelText(`CV ${source.id}`)).getByRole('button',{name:'Make active'});fireEvent.click(button);expect(confirm).toHaveBeenCalledWith(expect.stringContaining('If any roles or responsibilities are not clearly stated in your CV details'));expect(cvApi.select).not.toHaveBeenCalled();fireEvent.click(button);await waitFor(()=>expect(cvApi.select).toHaveBeenCalledTimes(1));}finally{confirm.mockRestore();}
});
it('selects a currently reviewed baseline without a warning',async()=>{
 const source={...savedCv('reviewed'),profile_reviewed_effective_version:1};source.profile_reviewed_effective_version=source.effective_version;
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[source],selection:{cv_id:null,version:1}});vi.mocked(cvApi.select).mockResolvedValue({cv_id:source.id,version:2});
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
 try{renderWorkspace();fireEvent.click(within(await screen.findByLabelText(`CV ${source.id}`)).getByRole('button',{name:'Make active'}));await waitFor(()=>expect(cvApi.select).toHaveBeenCalled());expect(confirm).not.toHaveBeenCalled();}finally{confirm.mockRestore();}
});
it('warns again when a saved review belongs to an older effective CV version',async()=>{
 const current={...savedCv('current'),created_at:'2099-01-01T00:00:00Z',profile_reviewed_effective_version:1};current.profile_reviewed_effective_version=current.effective_version;const source={...savedCv('changed'),created_at:'2000-01-01T00:00:00Z',effective_version:3,profile_reviewed_effective_version:2};vi.mocked(cvApi.list).mockResolvedValue({cvs:[current,source],selection:{cv_id:current.id,version:1}});
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
 try{renderWorkspace();fireEvent.click(within(await screen.findByLabelText(`CV ${source.id}`)).getByRole('button',{name:'Make active'}));expect(confirm).toHaveBeenCalledTimes(1);expect(cvApi.select).not.toHaveBeenCalled();}finally{confirm.mockRestore();}
});

it('does not start an interview in a hidden review after processing finishes',async()=>{
 const source={...savedCv('hidden-review'),status:'processing' as const};let accepted=false,complete=false;
 vi.mocked(cvApi.list).mockImplementation(async()=>({cvs:accepted?[{...source,status:complete?'ready':'processing'}]:[],selection:{cv_id:null,version:0}}));
 vi.mocked(cvApi.upload).mockImplementation(async()=>{accepted=true;return source;});
 vi.mocked(cvApi.get).mockImplementation(async()=>({...source,status:complete?'ready':'processing'}));
 vi.mocked(cvApi.conversation).mockResolvedValue({...emptyConversation,cv_id:source.id});
 renderWorkspace();fireEvent.change(await screen.findByLabelText('CV document'),{target:{files:[new File(['synthetic'],'resume.pdf')]}});fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));
 await screen.findByRole('progressbar',{name:'Reading your CV'});
 fireEvent.click(screen.getByRole('button',{name:'Save and review later'}));
 complete=true; // Skills Profile checks processing CVs again on its own every few seconds.
 await waitFor(()=>expect(cvApi.openConversation).toHaveBeenCalled(),{timeout:5000});
 expect(cvApi.sendMessage).not.toHaveBeenCalled();
 fireEvent.click(within(screen.getByRole('article',{name:`CV ${source.id}`})).getByRole('button',{name:'Review CV'}));
 await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('conversation',expect.objectContaining({command:'review'}),'synthetic-session',expect.any(AbortSignal)));
});

it('reopens the exact older CV and checks its current question before accepting another answer',async()=>{
 const recent={...savedCv('recent-baseline'),file_name:'Recent baseline.pdf'};
 const older={...savedCv('older-reviewed'),file_name:'Earlier review.pdf'};
 const question={id:'older-question',item_id:older.items[0].id,title:'Older experience',question:'How did you verify the report?'};
 const conversation={...emptyConversation,cv_id:older.id,purpose:'skills_profile' as const,active_question:question};
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[recent,older],selection:{cv_id:recent.id,version:1}});
 vi.mocked(cvApi.get).mockImplementation(async id=>id===older.id?older:recent);
 vi.mocked(cvApi.openConversation).mockResolvedValue(conversation);
 let refresh!: (value:CvConversation)=>void;
 vi.mocked(cvApi.conversation).mockImplementationOnce(async()=>new Promise(resolve=>{refresh=resolve;}));
 renderWorkspace();
 // An unfinished active CV offers its review on the Skills screen; the library still reaches older CVs.
 expect(await screen.findByRole('button',{name:/(Continue|Start) review/})).toBeVisible();
 fireEvent.click(within(screen.getByRole('article',{name:`CV ${older.id}`})).getByRole('button',{name:'Review CV'}));
 await screen.findByText(question.question);
 fireEvent.click(screen.getByRole('button',{name:'Save and review later'}));
 expect(screen.getByLabelText('Selected CV')).toHaveTextContent(recent.file_name);
 expect(screen.getByText('Review not finished')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:/(Continue|Start) review/}));
 expect(screen.getByText(question.question)).toBeVisible();
 expect(screen.getByRole('textbox',{name:'Message elo'})).toBeDisabled();
 expect(screen.getByRole('button',{name:'Skip this question'})).toBeDisabled();
 await waitFor(()=>expect(refresh).toBeTypeOf('function'));
 await act(async()=>refresh(conversation));
 expect(screen.getByRole('textbox',{name:'Message elo'})).toBeEnabled();
 expect(window.location.search).toBe(`?review=${older.id}`);
 expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:older.id}),'synthetic-session',expect.any(AbortSignal));
 expect(cvApi.sendMessage).not.toHaveBeenCalled();
 expect(cvApi.select).not.toHaveBeenCalled();
});

it.each([false,true])('keeps the answer draft and any retry identity during reprocessing (interrupted=%s)',async interrupted=>{
 const source=savedCv('reprocessing-chat');let processing=false;
 const current={...emptyConversation,cv_id:source.id,active_question:{id:'existing',item_id:source.items[0].id,title:'Existing topic',question:'What did you do?'}};
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[source],selection:{cv_id:source.id,version:1}});
 vi.mocked(cvApi.get).mockImplementation(async()=>({...source,status:processing?'processing':'ready'}));
 vi.mocked(cvApi.openConversation).mockResolvedValue(current);
 vi.mocked(cvApi.conversation).mockResolvedValue(current);
 renderWorkspace();fireEvent.click(within(await screen.findByRole('article',{name:`CV ${source.id}`})).getByRole('button',{name:'Review CV'}));
 const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
 fireEvent.change(input,{target:{value:'I wrote the import script.'}});
 if(interrupted){
  vi.mocked(cvApi.sendMessage).mockRejectedValueOnce(new TypeError('Response lost.')).mockResolvedValueOnce({...current,revision:2});
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByRole('button',{name:'Try again'});
 }
 processing=true;fireEvent(window,new Event('focus'));
 await screen.findByRole('progressbar',{name:'Reading your CV'});
 expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
 processing=false;
 await waitFor(()=>expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('I wrote the import script.'),{timeout:6000});
 if(interrupted){
  const retry=await screen.findByRole('button',{name:'Try again'});
  await waitFor(()=>expect(retry).toBeEnabled());
  fireEvent.click(retry);
  await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledTimes(2));
  expect(vi.mocked(cvApi.sendMessage).mock.calls[1][1]).toEqual(vi.mocked(cvApi.sendMessage).mock.calls[0][1]);
 }
});

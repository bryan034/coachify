vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: vi.fn(async (path: string) => path === '/context' ? {ready:false,model_available:true,issues:[]} : {version:0,stale:false,result:null,operation:null,ready:false,issues:[]})}));
import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {ResumePreview} from './resume-preview';
import {cvApi} from '@/lib/api/cv';
import {policy,savedCv,emptyDeclarations,clarificationState} from '../../../tests/fixtures/cv';
import type {CvConversation,SkillsProfile} from './types';

vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token',account:{id:'synthetic-owner'}})}));
vi.mock('@/lib/api/cv',async original=>{const actual=await original<typeof import('@/lib/api/cv')>();return {...actual,cvApi:Object.fromEntries(Object.keys(actual.cvApi).map(key=>[key,vi.fn()]))};});
const empty:SkillsProfile={version:0,status:'empty',saved_at:null,areas:{},entries:[]};
const chat:CvConversation={id:'chat',cv_id:null,revision:1,read_only:false,previous_conversation_id:null,active_question:null,context:null,messages:[],next_before:null,limits:{max_message_chars:4000,max_messages:500}};
beforeEach(()=>{window.history.replaceState(null,'','/cv');
 vi.clearAllMocks();
 vi.mocked(cvApi.policy).mockResolvedValue(policy);
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[],selection:{cv_id:null,version:0}});
 vi.mocked(cvApi.declarations).mockResolvedValue(emptyDeclarations);
 vi.mocked(cvApi.skillsProfile).mockResolvedValue(empty);
 vi.mocked(cvApi.get).mockImplementation(async id=>savedCv(id));
 vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(savedCv()));
 vi.mocked(cvApi.openConversation).mockImplementation(async body=>({...chat,cv_id:body.cv_id}));
 vi.mocked(cvApi.sendMessage).mockResolvedValue({...chat,revision:2,active_question:{id:'work',item_id:'work',title:'Work and internships',question:'Tell me about a work or internship experience.'}});
});

it('starts with an informative summary and two intake choices without opening chat',async()=>{
 render(<ResumePreview/>);
 expect(await screen.findByRole('region',{name:'Skills profile summary'})).toBeVisible();
 expect(screen.getByRole('button',{name:/Upload new CV/})).toBeEnabled();
 expect(screen.getByRole('button',{name:/Build through chat/})).toBeEnabled();
 await screen.findByText(/Start with your CV or a conversation/);
 expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
 expect(cvApi.openConversation).not.toHaveBeenCalled();
 expect(cvApi.sendMessage).not.toHaveBeenCalled();
});

it('opens manual intake explicitly and preserves the unsent draft when returning to the summary',async()=>{
 render(<ResumePreview/>);fireEvent.click(await screen.findByRole('button',{name:/Build through chat/}));
 const input=await screen.findByRole('textbox',{name:'Message elo'});
 await waitFor(()=>expect(input).toBeEnabled());
 expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:null,purpose:'skills_profile'}),'synthetic-token',expect.any(AbortSignal));
 await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('chat',expect.objectContaining({command:'review'}),'synthetic-token',expect.any(AbortSignal)));
 fireEvent.change(input,{target:{value:'A contribution I have not sent yet.'}});
 fireEvent.click(screen.getByRole('button',{name:'Back to Skills Profile'}));
 expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:/Build through chat/}));
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('A contribution I have not sent yet.');
 expect(cvApi.openConversation).toHaveBeenCalledTimes(1);
});

it('accepts a dropped CV and starts guided review automatically',async()=>{
 const cv=savedCv('uploaded');vi.mocked(cvApi.upload).mockResolvedValue(cv);vi.mocked(cvApi.get).mockResolvedValue(cv);
 render(<ResumePreview/>);fireEvent.click(await screen.findByRole('button',{name:/Upload new CV/}));
 await screen.findByLabelText('CV document');
 fireEvent.drop(screen.getByText('Drop your CV here, or choose a file below.').parentElement!,{dataTransfer:{files:[new File(['synthetic CV'],'profile.pdf')]}});
 fireEvent.click(screen.getByRole('button',{name:'Upload CV'}));
 await screen.findByRole('heading',{name:'Review your CV'});
 await waitFor(()=>expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:cv.id,purpose:'skills_profile'}),'synthetic-token',expect.any(AbortSignal)));
 await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('chat',expect.objectContaining({command:'review'}),'synthetic-token',expect.any(AbortSignal)));
 expect(cvApi.select).not.toHaveBeenCalled();
});

it('shows a saved partial profile and its uncertainty without inventing a skill level',async()=>{
 vi.mocked(cvApi.skillsProfile).mockResolvedValue({...empty,version:3,status:'saved',saved_at:'2026-11-02T00:00:00Z',areas:{work:'not_applicable'},entries:[{
  id:'synthetic-entry',kind:'project',title:'Weekly reports',fields:{description:{status:'answered',value:'Combined sales spreadsheets',evidence:[{message_id:'turn',quote:'I combined sales spreadsheets.'}]}},
  skills:[{name:'Data processing',description:'Combined sales spreadsheets.',evidence:[{message_id:'turn',quote:'I combined sales spreadsheets.'}],dimensions:{independence:{status:'unknown',value:null,evidence:[]}}}]}]});
 render(<ResumePreview/>);
 expect(await screen.findByText('Saved profile')).toBeVisible();
 expect(screen.getByRole('heading',{name:'Weekly reports'})).toBeVisible();
 // The CV review owns the named regions for these kinds, so the summary columns must not add a second one.
 expect(screen.queryByRole('region',{name:'Work and internships'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:/^Data processing/}));
 // The skill panel shows one competence state instead of raw dimension fields; nothing is invented.
 expect(within(screen.getByRole('complementary',{name:'Data processing'})).getByText(/Compare with your Career Goal|Competence not recorded yet/)).toBeVisible();
 expect(screen.queryByText('Advanced')).not.toBeInTheDocument();
 expect(cvApi.openConversation).not.toHaveBeenCalled();
});

it('saves a reviewed manual draft from the summary and retains retry identity on failure',async()=>{
 const draft={...empty,version:2,status:'draft' as const,areas:{work:'skipped' as const}};
 vi.mocked(cvApi.skillsProfile).mockResolvedValue(draft);
 vi.mocked(cvApi.saveSkillsProfile).mockRejectedValueOnce(new Error('Save interrupted.')).mockResolvedValueOnce({...draft,version:3,status:'saved',saved_at:'2026-11-02T00:00:00Z'});
 render(<ResumePreview/>);
 fireEvent.click(await screen.findByRole('button',{name:'Save profile'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Save interrupted.');
 fireEvent.click(screen.getByRole('button',{name:'Save profile'}));
 await screen.findByText('Saved profile');
 expect(vi.mocked(cvApi.saveSkillsProfile).mock.calls[0][0]).toEqual(vi.mocked(cvApi.saveSkillsProfile).mock.calls[1][0]);
 expect(cvApi.openConversation).not.toHaveBeenCalled();
});

it('withholds final saving while a conversation update needs attention',async()=>{
 vi.mocked(cvApi.skillsProfile).mockResolvedValue({...empty,version:1,status:'draft'});
 const failed={id:'failed-turn',kind:'route' as const,status:'failed' as const,title:'Check answer',summary:'Retry this saved answer.',changes:[],choices:[]};
 vi.mocked(cvApi.openConversation).mockResolvedValue({...chat,purpose:'skills_profile',messages:[{id:'message',sequence:1,role:'assistant',text:'Your answer needs attention.',created_at:'2026-11-02T00:00:00Z',actions:[failed]}]});
 render(<ResumePreview/>);
 fireEvent.click(await screen.findByRole('button',{name:/Continue building your profile/}));
 await screen.findByRole('button',{name:'Try again'});
 fireEvent.click(screen.getByRole('button',{name:'Back to Skills Profile'}));
 expect(screen.getByRole('button',{name:'Save profile'})).toBeDisabled();
 expect(screen.getByText(/Finish or cancel the pending conversation updates/)).toBeVisible();
 expect(cvApi.saveSkillsProfile).not.toHaveBeenCalled();
});

it('opens Skills Profile with repeated source-block IDs without key collisions or lost evidence',async()=>{
 const source=savedCv('shared-evidence');
 source.items[0].evidence=[
  {id:'b1',excerpt:'Cleaned the synthetic dataset.',location:'Page 1'},
  {id:'b2',excerpt:'Wrote the synthetic report.',location:'Page 2'},
  {id:'b1',excerpt:'Checked the synthetic dataset.',location:'Page 1'},
  {id:'b2',excerpt:'Presented the synthetic report.',location:'Page 2'},
 ];
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[source],selection:{cv_id:source.id,version:1}});
 vi.mocked(cvApi.get).mockResolvedValue(source);
 vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(source));
 const error=vi.spyOn(console,'error').mockImplementation(()=>{});
 try{
  render(<ResumePreview/>);
  await waitFor(()=>expect(document.querySelectorAll('.cv-evidence blockquote')).toHaveLength(5));
  for(const evidence of source.items[0].evidence)expect(screen.getByText(evidence.excerpt)).toBeInTheDocument();
  fireEvent(window,new Event('focus'));
  await waitFor(()=>expect(cvApi.list).toHaveBeenCalledTimes(2));
  await waitFor(()=>expect(document.querySelectorAll('.cv-evidence blockquote')).toHaveLength(5));
  for(const evidence of source.items[0].evidence)expect(screen.getByText(evidence.excerpt)).toBeInTheDocument();
  expect(error).not.toHaveBeenCalled();
 }finally{error.mockRestore();}
});

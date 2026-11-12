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

it('starts with an upload-first screen and a chat alternative without opening chat',async()=>{
 render(<ResumePreview/>);
 expect(await screen.findByRole('heading',{name:'Upload your CV'})).toBeVisible();
 expect(screen.getByLabelText('CV document')).toBeEnabled();
 expect(screen.getByRole('button',{name:'Add skills by chat'})).toBeEnabled();
 expect(screen.getByRole('heading',{name:'What happens next'})).toBeVisible();
 expect(screen.getByText(/Until you add a CV, elo can’t generate a roadmap/)).toBeVisible();
 expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
 expect(cvApi.openConversation).not.toHaveBeenCalled();
 expect(cvApi.sendMessage).not.toHaveBeenCalled();
});

it('opens manual intake explicitly and preserves the unsent draft when returning to the summary',async()=>{
 render(<ResumePreview/>);fireEvent.click(await screen.findByRole('button',{name:'Add skills by chat'}));
 const input=await screen.findByRole('textbox',{name:'Message elo'});
 await waitFor(()=>expect(input).toBeEnabled());
 expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:null,purpose:'skills_profile'}),'synthetic-token',expect.any(AbortSignal));
 await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('chat',expect.objectContaining({command:'review'}),'synthetic-token',expect.any(AbortSignal)));
 fireEvent.change(input,{target:{value:'A contribution I have not sent yet.'}});
 fireEvent.click(screen.getByRole('button',{name:'Back to Skills Profile'}));
 expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Add skills by chat'}));
 expect(screen.getByRole('textbox',{name:'Message elo'})).toHaveValue('A contribution I have not sent yet.');
 expect(cvApi.openConversation).toHaveBeenCalledTimes(1);
});

it('accepts a dropped CV and starts guided review automatically',async()=>{
 const cv=savedCv('uploaded');vi.mocked(cvApi.upload).mockResolvedValue(cv);vi.mocked(cvApi.get).mockResolvedValue(cv);
 render(<ResumePreview/>);
 await screen.findByLabelText('CV document');
 fireEvent.drop(screen.getByText('Drag a file here, or choose one from your device.').parentElement!,{dataTransfer:{files:[new File(['synthetic CV'],'profile.pdf')]}});
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
 expect(within(screen.getByRole('complementary',{name:'Data processing'})).getByText(/Evaluate your skills with your Career Goal|Competence not recorded yet/)).toBeVisible();
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


it('shows a page-level reading screen with real progress while the only CV is processing',async()=>{
 const reading={...savedCv('reading'),status:'processing' as const,processing_progress:{stage:'model_request' as const,percent:55,message:'Finding your experiences'}};
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[reading],selection:{cv_id:null,version:0}});vi.mocked(cvApi.get).mockResolvedValue(reading);
 render(<ResumePreview/>);
 expect(await screen.findByRole('heading',{name:'resume.pdf',level:2})).toBeVisible();
 expect(screen.getByRole('progressbar',{name:'Reading your CV'})).toHaveAttribute('aria-valuenow','55');
 expect(screen.getByText('Finding your experiences',{selector:'strong'}).closest('li')).toHaveAttribute('aria-current','step');
 expect(screen.getByText(/You can leave this page/)).toBeVisible();
 expect(await screen.findByText('Team dashboard',{selector:'strong'})).toBeVisible();
 expect(screen.getByRole('heading',{name:'Upload your CV'})).toBeInTheDocument();
});

it('says the review is complete and points at the roadmap and jobs once the active CV is reviewed',async()=>{
 const reviewed={...savedCv('done'),profile_reviewed_effective_version:1};
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[reviewed],selection:{cv_id:'done',version:1}});vi.mocked(cvApi.get).mockResolvedValue(reviewed);
 render(<ResumePreview/>);
 const banner=await screen.findByRole('region',{name:'Your CV review is complete'});
 expect(within(banner).getByRole('link',{name:'Generate roadmap'})).toHaveAttribute('href','/roadmap');
 expect(within(banner).getByRole('link',{name:'Search jobs'})).toHaveAttribute('href','/jobs');
});

it('reports what the review changed and shows the review note in the skill panel, from the backend summary',async()=>{
 const reviewed={...savedCv('done'),profile_reviewed_effective_version:1,review_summary:{answered_questions:21,experiences:8,skills_added:3,skills_corrected:2,skills_removed:1,added_skill_ids:[],skill_notes:{python:'You wrote the ETL scripts yourself.'}}};
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[reviewed],selection:{cv_id:'done',version:1}});vi.mocked(cvApi.get).mockResolvedValue(reviewed);
 render(<ResumePreview/>);
 const banner=await screen.findByRole('region',{name:'Your CV review is complete'});
 expect(banner).toHaveTextContent('You answered 21 questions across 8 experiences. From your answers, elo added 3 skills, corrected 2 and removed 1.');
 fireEvent.click(await screen.findByRole('button',{name:'Python'}));
 const panel=screen.getByRole('complementary',{name:'Python'});
 expect(within(panel).getByText('From your review')).toBeVisible();
 expect(within(panel).getByText('You wrote the ETL scripts yourself.')).toBeVisible();
});

it('shows where an unfinished review stands, read from the saved conversation, and holds back skills',async()=>{
 const cv={...savedCv('half'),profile_reviewed_effective_version:null};
 vi.mocked(cvApi.list).mockResolvedValue({cvs:[cv],selection:{cv_id:'half',version:1}});vi.mocked(cvApi.get).mockResolvedValue(cv);
 vi.mocked(cvApi.conversations).mockResolvedValue({conversations:[{id:'old',cv_id:'half',updated_at:'2026-11-01T00:00:00Z',read_only:true,message_count:9},{id:'now',cv_id:'half',updated_at:'2026-11-12T00:00:00Z',read_only:false,message_count:4}]});
 vi.mocked(cvApi.conversation).mockResolvedValue({...chat,id:'now',cv_id:'half',purpose:'skills_profile',interview:{status:'reviewing',reviewed_items:2,total_items:3,estimates:[],topics:[{id:'a',title:'First job',status:'reviewed'},{id:'b',title:'Side project',status:'deferred'},{id:'c',title:'Club role',status:'current'}]}});
 render(<ResumePreview/>);
 expect(await screen.findByRole('heading',{name:'Finish your CV review to build your profile'})).toBeVisible();
 expect(await screen.findByText('2 of 3 topics covered')).toBeVisible();
 expect(screen.getByText('1 reviewed, 1 skipped')).toBeVisible();
 expect(screen.getByText(/1 topic left\./).parentElement).toHaveTextContent('Next up: Club role');
 expect(screen.getByText('Skipped, CV used as written')).toBeVisible();
 expect(vi.mocked(cvApi.conversation)).toHaveBeenCalledWith('now','synthetic-token',expect.any(AbortSignal));
 expect(cvApi.openConversation).not.toHaveBeenCalled();
 expect(screen.getByRole('heading',{name:'Waiting for your review'})).toBeVisible();
 expect(screen.queryByRole('heading',{name:'Skills by category'})).not.toBeInTheDocument();
});

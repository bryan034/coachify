import {act, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {CvConversationPanel} from './cv-conversation';
import {cvApi, CvApiError} from '@/lib/api/cv';
import {savedCv, confirmedTarget} from '../../../tests/fixtures/cv';
import type {ConversationAction, ConversationMessage, CvConversation} from './types';

vi.mock('@/lib/api/cv', async importOriginal => {const actual = await importOriginal<typeof import('@/lib/api/cv')>(); return {...actual, cvApi: Object.fromEntries(Object.keys(actual.cvApi).map(key => [key, vi.fn()]))};});
const message = (id: string, text: string, actions: ConversationAction[] = [], role: 'user' | 'assistant' = 'assistant'): ConversationMessage => ({id, text, actions, role, sequence: Number(id.replace(/\D/g, '')) || 1, created_at: '2026-10-28T09:00:00Z'});
const conversation = (overrides: Partial<CvConversation> = {}): CvConversation => ({id:'chat-one', cv_id:'cv-one', revision:1, read_only:false, previous_conversation_id:null, active_question:null, context:confirmedTarget, messages:[], next_before:null, limits:{max_message_chars:4000,max_messages:500}, ...overrides});
const action = (overrides: Partial<ConversationAction> = {}): ConversationAction => ({id:'action-one', kind:'correct', status:'awaiting_confirmation', title:'Update React experience', summary:'Change the reported duration for ShopTrack.', changes:[{field:'experience_months',before:'5',after:'3'}], choices:[], ...overrides});
const props = () => ({cvId:'cv-one', detail:savedCv('cv-one'), token:'synthetic-session', onChanged:vi.fn().mockResolvedValue(undefined), onOpenSummary:vi.fn()});
beforeEach(() => {vi.clearAllMocks(); vi.mocked(cvApi.openConversation).mockResolvedValue(conversation()); vi.mocked(cvApi.conversation).mockResolvedValue(conversation());});

describe('saved CV conversation', () => {
 it('restores the transcript without inventing messages or starting review automatically', async () => {
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({messages:[message('m1','I built the React screens.',[],'user'),message('m2','Your explanation is saved.')]}));
  render(<CvConversationPanel {...props()}/>);
  expect(await screen.findByText('I built the React screens.')).toBeVisible();
  expect(screen.getByText('Your explanation is saved.')).toBeVisible();
  expect(cvApi.sendMessage).not.toHaveBeenCalled();
  expect(cvApi.openConversation).toHaveBeenCalledWith(expect.objectContaining({cv_id:'cv-one'}),'synthetic-session',expect.any(AbortSignal));
 });
 it('offers skip and continue after a failed next-step decision without an active question', async () => {
  const failed=action({id:'route-failed',kind:'route',status:'failed',title:'Continue review',summary:'Could not continue.',changes:[],error:'The interview could not choose a valid next step. Its proposed next steps did not pass the review checks.'});
  const current=conversation({purpose:'skills_profile',active_question:null,interview:{status:'reviewing',reviewed_items:0,total_items:2,estimates:[],topics:[{id:'one',title:'First project',status:'current'},{id:'two',title:'Next project',status:'pending'}]},messages:[message('m1','My original contribution is saved.',[],'user'),message('m2','Could not continue.',[failed])]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(current);
  vi.mocked(cvApi.sendMessage).mockResolvedValue({...current,revision:2,active_question:{id:'q2',item_id:'two',title:'Next project',question:'What did you handle in the next project?'},interview:{...current.interview!,reviewed_items:1,topics:[{id:'one',title:'First project',status:'deferred'},{id:'two',title:'Next project',status:'current'}]},messages:[current.messages[0],message('m2','Skipped remaining questions.',[{...failed,status:'cancelled',error:null}]),message('m3','What did you handle in the next project?')]});
  render(<CvConversationPanel {...props()} purpose="skills_profile"/>);
  fireEvent.click(await screen.findByRole('button',{name:'Skip and continue'}));
  await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('chat-one',expect.objectContaining({command:'skip',text:'Skip remaining questions for this experience.'}),'synthetic-session',expect.any(AbortSignal)));
  expect(await screen.findByText('What did you handle in the next project?')).toBeVisible();
  expect(screen.getByText('My original contribution is saved.')).toBeVisible();
  expect(screen.queryByRole('button',{name:'Skip and continue'})).not.toBeInTheDocument();
 });
 it('hides insufficient-evidence estimates in restored conversations from older servers', async () => {
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({purpose:'skills_profile',interview:{status:'reviewing',reviewed_items:0,total_items:1,topics:[],estimates:[
   {item_id:'project-one',skill_name:'Python',level:'guided_application',explanation:'Used personally with guidance.',evidence_refs:['internal-ref']},
   {item_id:'project-one',skill_name:'SQL',level:'insufficient_evidence',explanation:'Internal missing-field diagnostic.',evidence_refs:['internal-ref']},
  ]},messages:[message('m1','Which part of the pipeline did you implement?')]}));
  render(<CvConversationPanel {...props()} purpose="skills_profile"/>);
  await screen.findByText('Which part of the pipeline did you implement?');
  expect(screen.getByText(/Python · .* · guided application/)).toBeVisible();
  expect(screen.queryByText(/insufficient evidence|Internal missing-field diagnostic|SQL ·/)).not.toBeInTheDocument();
 });
 it('hides internal references in restored assistant messages while preserving the user transcript', async () => {
  const source='12b476847583f093b7e8aaf5dac8d5d5';
  const restored=conversation({purpose:'skills_profile',messages:[message('m1',`Regarding your Product Manager role [${source}], what tools did you use?`),message('m2',`My original reference was [${source}].`,[],'user')]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(restored);
  render(<CvConversationPanel {...props()} purpose="skills_profile"/>);
  expect(await screen.findByText('Regarding your Product Manager role, what tools did you use?')).toBeVisible();
  expect(screen.getByText(`My original reference was [${source}].`)).toBeVisible();
  expect(restored.messages[0].text).toContain(source);
 });
 it('keeps successful routing machinery out of the visible conversation but retains retry for a routing failure',async()=>{
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({messages:[message('m1','Let’s focus on your own contribution.',[action({kind:'route',status:'saved',title:'Understand your message',summary:'Message understood.',changes:[]}),action({id:'route-failed',kind:'route',status:'failed',title:'Try understanding again',summary:'Your message is saved.',changes:[],error:'Provider unavailable.'})])]}));
  render(<CvConversationPanel {...props()}/>);await screen.findByText('Let’s focus on your own contribution.');expect(screen.queryByText('Understand your message')).not.toBeInTheDocument();expect(screen.queryByText('Message understood.')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Retry this action'})).toBeEnabled();
 });
 it('starts a guided review explicitly and refreshes the evidence after the accepted response', async () => {
  const options=props();
  vi.mocked(cvApi.sendMessage).mockResolvedValue(conversation({revision:2, active_question:{id:'q1',item_id:'project-one',title:'ShopTrack',question:'What was your contribution?'},messages:[message('m1','What was your contribution?')]}));
  render(<CvConversationPanel {...options}/>); fireEvent.click(await screen.findByRole('button',{name:'Review with me'}));
  await waitFor(() => expect(cvApi.sendMessage).toHaveBeenCalledWith('chat-one',expect.objectContaining({command:'review',expected_revision:1}),'synthetic-session',expect.any(AbortSignal)));
  expect(await screen.findByRole('button',{name:'Skip this question'})).toBeEnabled(); expect(options.onChanged).toHaveBeenCalled();
 });
 it('automatically resumes an opened paused review without a continue button', async () => {
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({purpose:'skills_profile',interview:{status:'paused',reviewed_items:0,total_items:1,estimates:[]},messages:[message('m1','We can continue later.'),message('m2','Stop here.',[],'user')]}));
  vi.mocked(cvApi.sendMessage).mockResolvedValue(conversation({purpose:'skills_profile',revision:2,active_question:{id:'q1',item_id:'project-one',title:'Project',question:'What did you build?'},messages:[message('m3','What did you build?')]}));
  render(<CvConversationPanel {...props()} purpose="skills_profile" autoReview/>);
  await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledWith('chat-one',expect.objectContaining({command:'review'}),'synthetic-session',expect.any(AbortSignal)));
  expect(await screen.findByText('What did you build?')).toBeVisible();
  expect(screen.queryByRole('button',{name:'Continue review'})).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Review profile summary'})).not.toBeInTheDocument();
 });
 it('shows topic progress and the profile button only after completion', async () => {
  const options=props();
  const reviewing=conversation({purpose:'skills_profile',interview:{status:'reviewing',reviewed_items:1,total_items:2,estimates:[],topics:[{id:'one',title:'First experience',status:'reviewed'},{id:'two',title:'Second experience',status:'current'}]},active_question:{id:'q1',item_id:'two',title:'Second experience',question:'What did you do?'},messages:[message('m1','What did you do?')]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(reviewing);
  vi.mocked(cvApi.sendMessage).mockResolvedValue({...reviewing,revision:2,active_question:null,interview:{...reviewing.interview!,status:'reviewed_with_gaps',reviewed_items:2,topics:[{id:'one',title:'First experience',status:'reviewed'},{id:'two',title:'Second experience',status:'reviewed_with_gaps'}]},messages:[message('m2','Your review is complete.')]});
  render(<CvConversationPanel {...options} purpose="skills_profile" autoReview/>);
  expect(await screen.findByRole('progressbar',{name:'Review progress'})).toHaveAttribute('aria-valuenow','1');
  expect(screen.getByText('50% · Experience review')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Review profile'})).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'I handled reporting.'}});
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  const button=await screen.findByRole('button',{name:'Review profile'});
  await waitFor(()=>expect(button).toBeEnabled());
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow','2');
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuemax','2');
  expect(screen.getByText('100% · Review complete')).toBeInTheDocument();
  fireEvent.click(button);expect(options.onOpenSummary).toHaveBeenCalledOnce();
 });
 it('keeps topic progress visible and unchanged through followups until a topic transition', async () => {
  const reviewing=conversation({purpose:'skills_profile',interview:{status:'reviewing',reviewed_items:0,total_items:2,estimates:[],topics:[{id:'one',title:'First experience',status:'current'},{id:'two',title:'Second experience',status:'pending'}]},active_question:{id:'q1',item_id:'one',title:'First experience',question:'What did you do?'},messages:[message('m1','What did you do?')]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(reviewing);
  vi.mocked(cvApi.sendMessage).mockResolvedValueOnce({...reviewing,revision:2,active_question:{...reviewing.active_question!,id:'q2',question:'What was the task scope?'},messages:[message('m2','What was the task scope?')]}).mockResolvedValueOnce({...reviewing,revision:3,interview:{...reviewing.interview!,reviewed_items:1,topics:[{id:'one',title:'First experience',status:'reviewed_with_gaps'},{id:'two',title:'Second experience',status:'current'}]},active_question:{id:'q3',item_id:'two',title:'Second experience',question:'Moving to your second experience: what did you do?'},messages:[message('m3','Moving to your second experience: what did you do?')]});
  render(<CvConversationPanel {...props()} purpose="skills_profile" autoReview/>);
  const bar=await screen.findByRole('progressbar',{name:'Review progress'});
  expect(bar).toHaveAttribute('aria-valuenow','0');
  fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'I implemented the reporting API.'}});
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  expect(screen.getByRole('progressbar')).toBe(bar);
  await screen.findByText('What was the task scope?');
  await waitFor(()=>expect(screen.getByRole('textbox',{name:'Message elo'})).toBeEnabled());
  expect(screen.getByRole('progressbar')).toBe(bar);
  expect(bar).toHaveAttribute('aria-valuenow','0');
  expect(screen.getByText('0% · Experience review')).toBeVisible();
  fireEvent.change(screen.getByRole('textbox',{name:'Message elo'}),{target:{value:'It generated weekly reports.'}});
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByText('Moving to your second experience: what did you do?');
  expect(screen.getByRole('progressbar')).toBe(bar);
  expect(bar).toHaveAttribute('aria-valuenow','1');
  expect(screen.getByText('50% · Experience review')).toBeVisible();
 });
 it('does not restart a completed review when reopened', async () => {
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({purpose:'skills_profile',interview:{status:'reviewed',reviewed_items:1,total_items:1,estimates:[]},messages:[message('m1','Your review is complete.')]}));
  render(<CvConversationPanel {...props()} purpose="skills_profile" autoReview/>);
  expect(await screen.findByRole('button',{name:'Review profile'})).toBeEnabled();
  expect(cvApi.sendMessage).not.toHaveBeenCalled();
 });
 it('automatically recovers one old evidence-alignment failure', async () => {
  const failed=action({kind:'clarify',status:'failed',error:'Some interpreted skill details are not supported by your answer. Your answer is saved; clarify or retry interpretation.'});
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({purpose:'skills_profile',messages:[message('m1','Your answer is saved.',[failed])]}));
  vi.mocked(cvApi.conversationAction).mockResolvedValue(conversation({purpose:'skills_profile',revision:2,active_question:{id:'q1',item_id:'project-one',title:'Project',question:'What happened next?'},messages:[message('m2','What happened next?')]}));
  render(<CvConversationPanel {...props()} purpose="skills_profile" autoReview/>);
  await waitFor(()=>expect(cvApi.conversationAction).toHaveBeenCalledWith('chat-one',failed.id,expect.objectContaining({decision:'retry'}),'synthetic-session',expect.any(AbortSignal)));
  expect(await screen.findByText('What happened next?')).toBeVisible();
  expect(cvApi.conversationAction).toHaveBeenCalledOnce();
 });
 it('retains an interrupted draft and retries the same message identity', async () => {
  vi.mocked(cvApi.sendMessage).mockRejectedValue(new Error('Connection interrupted.'));
  render(<CvConversationPanel {...props()}/>);
  const input=await screen.findByRole('textbox',{name:'Message elo'}); await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'Also, five months using React.'}}); fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await screen.findByRole('alert'); expect(input).toHaveValue('Also, five months using React.');
  fireEvent.click(screen.getByRole('button',{name:'Send message'})); await waitFor(()=>expect(cvApi.sendMessage).toHaveBeenCalledTimes(2));
  expect(vi.mocked(cvApi.sendMessage).mock.calls[0][1]).toEqual(vi.mocked(cvApi.sendMessage).mock.calls[1][1]);
 });
 it('does not duplicate an accepted message after a lost response and a saved-history refresh',async()=>{
  const accepted=new Set<string>(); let server=conversation(); let routed=0;
  vi.mocked(cvApi.sendMessage).mockImplementation(async(_id,body)=>{if(accepted.has(body.mutation_id))return server;accepted.add(body.mutation_id);routed++;server=conversation({revision:3,messages:[message('m1',body.text,[],'user'),message('m2','Your contribution is saved.')]});throw new TypeError('Network response lost.');});
  vi.mocked(cvApi.conversation).mockImplementation(async()=>server);
  render(<CvConversationPanel {...props()}/>);const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'I built the React screens.'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button',{name:'Check saved messages'}));await screen.findByText('Your contribution is saved.');
  expect(input).toHaveValue('I built the React screens.');fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  await waitFor(()=>expect(input).toHaveValue(''));expect(routed).toBe(1);expect(screen.getAllByText('I built the React screens.')).toHaveLength(1);
  expect(vi.mocked(cvApi.sendMessage).mock.calls[1][1].expected_revision).toBe(1);
 });
 it('keeps a correction retry bound to its original request after a history refresh',async()=>{
  const proposal=action(),initial=conversation({messages:[message('m1','Review the change.',[proposal])]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(initial);vi.mocked(cvApi.conversation).mockResolvedValue({...initial,revision:4});vi.mocked(cvApi.conversationAction).mockRejectedValueOnce(new TypeError('Response lost.')).mockResolvedValue({...initial,revision:5,messages:[message('m1','Review the change.',[{...proposal,status:'saved'}])]});
  render(<CvConversationPanel {...props()}/>);fireEvent.click(await screen.findByRole('button',{name:'Save change'}));await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'Check saved messages'}));await waitFor(()=>expect(screen.queryByRole('alert')).not.toBeInTheDocument());fireEvent.click(screen.getByRole('button',{name:'Save change'}));await screen.findByText('Saved',{selector:'.cv-chat-action-status'});
  expect(vi.mocked(cvApi.conversationAction).mock.calls[1][2]).toEqual(vi.mocked(cvApi.conversationAction).mock.calls[0][2]);
 });
 it('retains each unresolved send identity while another draft or side question is sent',async()=>{
  const initial=conversation({active_question:{id:'q1',item_id:'project-one',title:'ShopTrack',question:'What did you build?'},messages:[message('m1','What did you build?')]});
  let server=initial;const accepted=new Set<string>();let routed=0;
  vi.mocked(cvApi.openConversation).mockResolvedValue(initial);
  vi.mocked(cvApi.conversation).mockImplementation(async()=>server);
  vi.mocked(cvApi.sendMessage).mockImplementation(async(_id,body)=>{
   if(accepted.has(body.mutation_id))return server;
   accepted.add(body.mutation_id);routed++;
   server={...server,revision:server.revision+1,messages:[...server.messages,message(`m${server.messages.length+1}`,body.text,[],'user')]};
   if(body.text!=='Why are you asking this question?')throw new TypeError('Response lost after saving.');
   return server;
  });
  render(<CvConversationPanel {...props()}/>);const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
  for(const text of ['I built the screens.','I also wrote the tests.']){
   fireEvent.change(input,{target:{value:text}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByRole('alert');
   fireEvent.click(screen.getByRole('button',{name:'Check saved messages'}));await waitFor(()=>expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  }
  fireEvent.click(screen.getByRole('button',{name:'Why this question?'}));await screen.findByText('Why are you asking this question?');await waitFor(()=>expect(input).toBeEnabled());
  for(const text of ['I built the screens.','I also wrote the tests.']){
   fireEvent.change(input,{target:{value:text}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await waitFor(()=>expect(input).toHaveValue(''));
   expect(screen.getAllByText(text)).toHaveLength(1);
  }
  const calls=vi.mocked(cvApi.sendMessage).mock.calls;
  expect(calls[3][1]).toEqual(calls[0][1]);expect(calls[4][1]).toEqual(calls[1][1]);expect(routed).toBe(3);
 });
 it('resolves a lost receipt in its original segment after continuing without replacing the current chat',async()=>{
  const original=conversation(),full=conversation({read_only:true,revision:3,messages:[message('m1','My contribution.',[],'user')]}),next=conversation({id:'chat-two',previous_conversation_id:'chat-one'});
  vi.mocked(cvApi.openConversation).mockResolvedValueOnce(original).mockResolvedValueOnce(next);
  vi.mocked(cvApi.sendMessage).mockRejectedValueOnce(new TypeError('Response lost.')).mockResolvedValueOnce(full);
  vi.mocked(cvApi.conversation).mockResolvedValue(full);
  render(<CvConversationPanel {...props()}/>);const input=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'My contribution.'}});fireEvent.click(screen.getByRole('button',{name:'Send message'}));await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button',{name:'Check saved messages'}));fireEvent.click(await screen.findByRole('button',{name:'Continue in a new conversation'}));
  const resumed=await screen.findByRole('textbox',{name:'Message elo'});await waitFor(()=>expect(resumed).toBeEnabled());expect(resumed).toHaveValue('My contribution.');
  fireEvent.click(screen.getByRole('button',{name:'Send message'}));await waitFor(()=>expect(resumed).toHaveValue(''));
  const calls=vi.mocked(cvApi.sendMessage).mock.calls;expect(calls[1][0]).toBe('chat-one');expect(calls[1][1]).toEqual(calls[0][1]);
  expect(screen.getByRole('button',{name:'Previous conversation'})).toBeEnabled();expect(screen.queryByText('My contribution.')).not.toBeInTheDocument();
 });
 it('keeps a draft through revision conflict and refreshes saved messages before another send',async()=>{
  vi.mocked(cvApi.sendMessage).mockRejectedValue(new CvApiError('Conversation changed.',409));
  vi.mocked(cvApi.conversation).mockResolvedValue(conversation({revision:4,messages:[message('m1','A newer saved response.')]}));
  render(<CvConversationPanel {...props()}/>); const input=await screen.findByRole('textbox',{name:'Message elo'}); await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'My new explanation'}}); fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  expect(await screen.findByText('A newer saved response.')).toBeVisible(); expect(input).toHaveValue('My new explanation'); expect(cvApi.sendMessage).toHaveBeenCalledTimes(1);
 });
 it('asks a side question without losing the current answer draft',async()=>{
  const initial=conversation({active_question:{id:'q1',item_id:'project-one',title:'ShopTrack',question:'What did you build?'},messages:[message('m1','What did you build?')]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(initial); vi.mocked(cvApi.sendMessage).mockResolvedValue({...initial,revision:2,messages:[...initial.messages,message('m2','This helps describe your own work.')]});
  render(<CvConversationPanel {...props()}/>); const input=await screen.findByRole('textbox',{name:'Message elo'}); await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'I built the screens'}}); fireEvent.click(screen.getByRole('button',{name:'Why this question?'}));
  await screen.findByText('This helps describe your own work.'); expect(input).toHaveValue('I built the screens'); expect(screen.queryByText(/Current topic:/)).not.toBeInTheDocument(); expect(screen.getAllByText('What did you build?')).toHaveLength(1); expect(screen.getByRole('button',{name:'Why this question?'}).closest('.cv-chat-messages')).not.toBeNull();
  expect(vi.mocked(cvApi.sendMessage).mock.calls[0][1]).toMatchObject({text:'Why are you asking this question?'});
 });
 it('requires an explicit save or cancel for a proposed correction',async()=>{
  const proposal=action(); vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({messages:[message('m1','Review this correction.',[proposal])]}));
  vi.mocked(cvApi.conversationAction).mockResolvedValue(conversation({revision:2,messages:[message('m1','Review this correction.',[{...proposal,status:'cancelled'}])]}));
  render(<CvConversationPanel {...props()}/>); await screen.findByRole('button',{name:'Save change'}); expect(cvApi.conversationAction).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Cancel change'})); await waitFor(()=>expect(cvApi.conversationAction).toHaveBeenCalledWith('chat-one','action-one',expect.objectContaining({decision:'cancel',expected_revision:1}),'synthetic-session',expect.any(AbortSignal)));
  expect(await screen.findByText('Cancelled',{selector:'.cv-chat-action-status'})).toBeVisible(); expect(screen.queryByRole('button',{name:'Save change'})).not.toBeInTheDocument();
 });
 it('requires a specific source choice and never guesses between two projects',async()=>{
  const proposal=action({kind:'choose_source',status:'needs_source',title:'Choose the project',changes:[],choices:[{id:'project-a',label:'Dashboard at work',description:'Internship',kind:'item'},{id:'project-b',label:'Dashboard at university',description:'Group project',kind:'item'}]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({messages:[message('m1','Which project?', [proposal])]})); vi.mocked(cvApi.conversationAction).mockResolvedValue(conversation({revision:2}));
  render(<CvConversationPanel {...props()}/>); expect(await screen.findByRole('button',{name:'Use this source'})).toBeDisabled();
  fireEvent.click(screen.getByRole('radio',{name:/Dashboard at university/})); fireEvent.click(screen.getByRole('button',{name:'Use this source'}));
  await waitFor(()=>expect(cvApi.conversationAction).toHaveBeenCalledWith('chat-one','action-one',expect.objectContaining({decision:'save',item_id:'project-b'}),'synthetic-session',expect.any(AbortSignal)));
 });
 it('offers explicit existing-declaration attachment or a distinct manual capability',async()=>{
  const proposal=action({kind:'add_capability',title:'Add Python',changes:[],choices:[{id:'declaration-a',label:'Python',description:'Earlier manual capability',kind:'declaration'}]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({cv_id:null,messages:[message('m1','Review your addition.',[proposal])]})); vi.mocked(cvApi.conversationAction).mockResolvedValue(conversation({cv_id:null,revision:2}));
  render(<CvConversationPanel {...props()} cvId={null} detail={null}/>); expect(await screen.findByRole('button',{name:'Save capability'})).toBeDisabled();
  fireEvent.click(screen.getByRole('radio',{name:/Earlier manual capability/})); fireEvent.click(screen.getByRole('button',{name:'Save capability'}));
  await waitFor(()=>expect(cvApi.conversationAction).toHaveBeenCalledWith('chat-one','action-one',expect.objectContaining({decision:'save',mode:'attach',attach_to_id:'declaration-a'}),'synthetic-session',expect.any(AbortSignal)));
 });
 it('loads older messages and makes older conversation segments read only',async()=>{
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({previous_conversation_id:'chat-old',next_before:20,messages:[message('m21','Recent explanation.')]}));
  vi.mocked(cvApi.conversation).mockImplementation(async(id,_token,_signal,before)=>id==='chat-old'?conversation({id:'chat-old',read_only:true,messages:[message('m1','Earlier segment.',[action()])]}):conversation({previous_conversation_id:'chat-old',messages:[message('m1','First saved message.')],next_before:null}));
  render(<CvConversationPanel {...props()}/>); fireEvent.click(await screen.findByRole('button',{name:'Show earlier messages'}));
  expect(await screen.findByText('First saved message.')).toBeVisible(); expect(screen.getByText('Recent explanation.')).toBeVisible();
  expect(cvApi.conversation).toHaveBeenCalledWith('chat-one','synthetic-session',expect.any(AbortSignal),20);
  fireEvent.click(screen.getByRole('button',{name:'Previous conversation'})); await screen.findByText('Earlier segment.');
  expect(screen.queryByRole('button',{name:'Save change'})).not.toBeInTheDocument(); expect(screen.queryByRole('textbox',{name:'Message elo'})).not.toBeInTheDocument(); expect(screen.getByRole('button',{name:'Return to current conversation'})).toBeEnabled();
 });
 it('lets users finish a proposal in a full current segment before continuing',async()=>{
  const proposal=action();vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({read_only:true,messages:[message('m1','Review this final change.',[proposal])]}));vi.mocked(cvApi.conversationAction).mockResolvedValue(conversation({read_only:true,revision:2,messages:[message('m1','Review this final change.',[{...proposal,status:'cancelled'}])]}));
  render(<CvConversationPanel {...props()}/>);expect(await screen.findByRole('button',{name:'Continue in a new conversation'})).toBeDisabled();expect(screen.getByRole('button',{name:'Save change'})).toBeEnabled();fireEvent.click(screen.getByRole('button',{name:'Cancel change'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Continue in a new conversation'})).toBeEnabled());expect(cvApi.conversationAction).toHaveBeenCalled();
 });
 it.each([
  {decision:'save',button:'Save change',before:'awaiting_confirmation',after:'saved'},
  {decision:'cancel',button:'Cancel change',before:'awaiting_confirmation',after:'cancelled'},
  {decision:'retry',button:'Retry this action',before:'failed',after:'saved'},
 ] as const)('refreshes an older $decision action omitted from the latest forty-message mutation response',async({decision,button,before,after})=>{
  let updated=false;
  const latest=Array.from({length:40},(_,i)=>message(`m${81+i}`,`Latest message ${81+i}`));
  const older=()=>Array.from({length:40},(_,i)=>message(`m${41+i}`,`Earlier message ${41+i}`,i?[]:[action({status:updated?after:before})]));
  const envelope=()=>conversation({revision:updated?2:1,messages:latest,next_before:81});
  vi.mocked(cvApi.openConversation).mockResolvedValue(envelope());
  vi.mocked(cvApi.conversation).mockImplementation(async(_id,_token,_signal,cursor)=>cursor===81?{...envelope(),messages:older(),next_before:41}:cursor===42?{...envelope(),messages:[older()[0]],next_before:41}:envelope());
  vi.mocked(cvApi.conversationAction).mockImplementation(async()=>{updated=true;return envelope();});
  render(<CvConversationPanel {...props()}/>);fireEvent.click(await screen.findByRole('button',{name:'Show earlier messages'}));
  fireEvent.click(await screen.findByRole('button',{name:button}));
  await waitFor(()=>expect(screen.getByText(after==='saved'?'Saved':'Cancelled',{selector:'.cv-chat-action-status'})).toBeVisible());
  expect(cvApi.conversation).toHaveBeenCalledWith('chat-one','synthetic-session',expect.any(AbortSignal),42);
  expect(cvApi.conversationAction).toHaveBeenCalledWith('chat-one','action-one',expect.objectContaining({decision}),'synthetic-session',expect.any(AbortSignal));
  expect(screen.queryByRole('button',{name:button})).not.toBeInTheDocument();expect(screen.getByText('Earlier message 80')).toBeVisible();
 });
 it.each([
  {status:'saved',revision:2,label:'Saved'},
  {status:'failed',revision:1,label:'Needs attention'},
 ] as const)('polls an older pending action to $status, including lease expiry without a revision change',async({status,revision,label})=>{
  let loaded=false;
  const pending=action({status:'pending'}),latest=conversation({messages:[message('m81','Latest saved message.')],next_before:81});
  vi.mocked(cvApi.openConversation).mockResolvedValue(latest);
  vi.mocked(cvApi.conversation).mockImplementation(async(_id,_token,_signal,cursor)=>{
   if(cursor===81){loaded=true;return conversation({messages:[message('m41','Older processing action.',[pending])],next_before:41});}
   if(cursor===42)return conversation({revision,messages:[message('m41','Older processing action.',[{...pending,status}])],next_before:41});
   return {...latest,revision:loaded?revision:1};
  });
  const options=props();render(<CvConversationPanel {...options}/>);fireEvent.click(await screen.findByRole('button',{name:'Show earlier messages'}));
  await screen.findByText('Processing',{selector:'.cv-chat-action-status'});
  const input=screen.getByRole('textbox',{name:'Message elo'});fireEvent.change(input,{target:{value:'My next answer stays here.'}});
  await waitFor(()=>expect(screen.getByText(label,{selector:'.cv-chat-action-status'})).toBeVisible(),{timeout:2500});
  expect(screen.queryByText('Processing',{selector:'.cv-chat-action-status'})).not.toBeInTheDocument();expect(input).toHaveValue('My next answer stays here.');
  if(status==='saved')expect(options.onChanged).toHaveBeenCalled();else expect(screen.getByRole('button',{name:'Retry this action'})).toBeEnabled();
 });
 it('loads every page of a full segment before allowing continuation and exposes its oldest unresolved action',async()=>{
  let release!:(value:CvConversation)=>void;
  const page=(start:number,end:number)=>conversation({read_only:true,messages:Array.from({length:end-start+1},(_,i)=>message(`m${start+i}`,`Saved message ${start+i}`,start+i===1?[action()]:[])),next_before:start===1?null:start});
  vi.mocked(cvApi.openConversation).mockResolvedValue(page(461,500));
  vi.mocked(cvApi.conversation).mockImplementation(async(_id,_token,_signal,cursor)=>{
   const end=cursor!-1,start=Math.max(1,end-39);
   if(start===1)return new Promise(resolve=>release=resolve);
   return page(start,end);
  });
  render(<CvConversationPanel {...props()}/>);
  await waitFor(()=>expect(cvApi.conversation).toHaveBeenCalledTimes(12));
  expect(screen.getByRole('button',{name:'Continue in a new conversation'})).toBeDisabled();expect(screen.getByText(/Checking earlier messages for outstanding actions/)).toBeVisible();
  await act(async()=>release(page(1,20)));
  expect(await screen.findByRole('button',{name:'Save change'})).toBeEnabled();expect(screen.getByText('Saved message 1')).toBeVisible();
  expect(screen.getByRole('button',{name:'Continue in a new conversation'})).toBeDisabled();expect(screen.queryByRole('button',{name:'Show earlier messages'})).not.toBeInTheDocument();expect(cvApi.conversation).toHaveBeenCalledTimes(12);
 });
 it('does not let a delayed older page overwrite a newer action or lose the draft',async()=>{
  let finish!:(value:CvConversation)=>void;const proposal=action();
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({messages:[message('m81','Current correction.',[proposal])],next_before:81}));
  vi.mocked(cvApi.conversation).mockImplementation(async(_id,_token,_signal,cursor)=>cursor===81?new Promise(resolve=>finish=resolve):conversation({revision:3,messages:[message('m81','Current correction.',[{...proposal,status:'saved'}])],next_before:81}));
  render(<CvConversationPanel {...props()}/>);fireEvent.click(await screen.findByRole('button',{name:'Show earlier messages'}));
  const input=screen.getByRole('textbox',{name:'Message elo'});fireEvent.change(input,{target:{value:'An unsent explanation.'}});fireEvent(window,new Event('focus'));
  await screen.findByText('Saved',{selector:'.cv-chat-action-status'});
  await act(async()=>finish(conversation({messages:[message('m41','Earlier page.'),message('m81','Current correction.',[proposal])],next_before:41})));
  expect(screen.queryByRole('button',{name:'Save change'})).not.toBeInTheDocument();expect(screen.getByText('Saved',{selector:'.cv-chat-action-status'})).toBeVisible();expect(input).toHaveValue('An unsent explanation.');
  expect(screen.getByRole('alert')).toHaveTextContent('changed while loading earlier messages');
 });
 it('shows pending interpretation separately from a saved fact and updates after polling',async()=>{
  const pending=action({kind:'clarify',status:'pending',title:'Your explanation',summary:'Your answer is saved; interpretation is pending.',changes:[]});
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({messages:[message('m1','I built the screens.',[],'user'),message('m2','Message saved.',[pending])]}));
  vi.mocked(cvApi.conversation).mockResolvedValue(conversation({revision:2,messages:[message('m2','Message saved.',[{...pending,status:'saved',summary:'Your React contribution is recorded.'}])]}));
  const options=props(); render(<CvConversationPanel {...options}/>); expect(await screen.findByText('Processing',{selector:'.cv-chat-action-status'})).toBeVisible();
  await waitFor(()=>expect(screen.getByText('Your React contribution is recorded.')).toBeVisible(),{timeout:2500}); expect(options.onChanged).toHaveBeenCalled();
 });
 it('preserves multiline composition and rejects over-limit messages without truncating the draft',async()=>{
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({limits:{max_message_chars:20,max_messages:500}}));
  render(<CvConversationPanel {...props()}/>); const input=await screen.findByRole('textbox',{name:'Message elo'}); await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'A complete explanation longer than twenty characters'}}); fireEvent.keyDown(input,{key:'Enter',shiftKey:true});
  expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled(); expect(input).toHaveValue('A complete explanation longer than twenty characters'); expect(cvApi.sendMessage).not.toHaveBeenCalled();
 });
 it('aborts the old conversation and ignores its late result on a CV change',async()=>{
  let finish!:(value:CvConversation)=>void; vi.mocked(cvApi.sendMessage).mockImplementation(()=>new Promise(resolve=>finish=resolve));
  const options=props(), view=render(<CvConversationPanel key="cv-one" {...options}/>); const input=await screen.findByRole('textbox',{name:'Message elo'}); await waitFor(()=>expect(input).toBeEnabled());
  fireEvent.change(input,{target:{value:'Private source one'}}); fireEvent.click(screen.getByRole('button',{name:'Send message'}));
  vi.mocked(cvApi.openConversation).mockResolvedValue(conversation({id:'chat-two',cv_id:'cv-two',messages:[message('m1','Source two conversation.')]}));
  view.rerender(<CvConversationPanel key="cv-two" {...options} cvId="cv-two" detail={savedCv('cv-two')}/>); await screen.findByText('Source two conversation.');
  await act(async()=>finish(conversation({revision:2,messages:[message('m1','Private old result.')]})));
  expect(within(screen.getByRole('region',{name:'CV conversation'})).queryByText('Private old result.')).not.toBeInTheDocument(); expect(options.onChanged).not.toHaveBeenCalled();
 });
});

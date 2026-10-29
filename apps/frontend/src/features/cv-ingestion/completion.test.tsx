import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CvReview } from './cv-review';
import { ResumePreview } from './resume-preview';
import { CapabilityDeclarations } from './capability-declarations';
import { DeclarationAttachment } from './declaration-attachment';
import { SourceReconciliation } from './source-reconciliation';
import { cvApi, CvApiError } from '@/lib/api/cv';
import { clarificationState, confirmedTarget, emptyDeclarations, policy, savedCv } from '../../../tests/fixtures/cv';
import type { Clarification, CvDetail, Declaration, Reconciliation } from './types';

vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token',account:{id:'synthetic-owner'}})}));
vi.mock('@/lib/api/cv',async importOriginal=>{const actual=await importOriginal<typeof import('@/lib/api/cv')>();return {...actual,cvApi:Object.fromEntries(Object.keys(actual.cvApi).map(key=>[key,vi.fn()]))};});
const signal=()=>new AbortController().signal;
const metadata={provider:'synthetic',model:'fixture',prompt_version:'1',schema_version:'1'};
function answered(detail:CvDetail):Clarification{return {id:'answer-one',item_id:detail.items[0].id,kind:'project',question:'Which work was yours?',uncertainty_key:'contribution',status:'answered',answer:'I wrote Python with my tutor for six months. My teammate wrote SQL.',career_target_id:confirmedTarget.id,career_target_version:1,answer_revision:1,interpretation_status:'ready',resolution:'partial',interpretation_error:null,interpretation:{claims:[{skill_id:'skill:python',name:'Python',attribution:'personal',assistance:'supervised',proficiency:null,experience_months:6,evidence_excerpt:'I wrote Python with my tutor for six months.',changed_fields:['attribution','assistance','experience_months']},{skill_id:'skill:sql',name:'SQL',attribution:'team',assistance:'unknown',proficiency:null,experience_months:null,evidence_excerpt:'My teammate wrote SQL.',changed_fields:['attribution']}],summary:'Python is personal work under supervision. SQL belongs to the team in this project.',resolved_uncertainties:['personal_contribution'],remaining_uncertainties:['proficiency'],metadata}};}
function review(detail:CvDetail,onSaved=vi.fn()){return <CvReview detail={detail} policy={policy} questions={clarificationState(detail,confirmedTarget,true)} token="token" signal={signal()} onSaved={onSaved} refresh={vi.fn().mockResolvedValue(undefined)}/>;}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(cvApi.openConversation).mockImplementation(async body=>({id:'conversation',cv_id:body.cv_id,revision:1,read_only:false,previous_conversation_id:null,active_question:null,context:null,messages:[],next_before:null,limits:{max_message_chars:4000,max_messages:500}}));vi.mocked(cvApi.conversation).mockImplementation(async()=>({id:'conversation',cv_id:'cv-one',revision:1,read_only:false,previous_conversation_id:null,active_question:null,context:null,messages:[],next_before:null,limits:{max_message_chars:4000,max_messages:500}}));vi.mocked(cvApi.policy).mockResolvedValue(policy);vi.mocked(cvApi.list).mockResolvedValue({cvs:[],selection:{cv_id:null,version:0}});vi.mocked(cvApi.get).mockImplementation(async id=>savedCv(id));vi.mocked(cvApi.declarations).mockResolvedValue(emptyDeclarations);vi.mocked(cvApi.questions).mockResolvedValue(clarificationState(savedCv()));});

describe('clarification interpretation review',()=>{
 it('distinguishes personal supervised work from teammate support and keeps partial knowledge visible',()=>{
  const detail=savedCv();detail.clarifications=[answered(detail)];render(review(detail));
  const result=screen.getByLabelText('Explanation interpretation');
  expect(result).toHaveTextContent('Python: personal contribution reported · Performed under supervision · Experience: 6 months reported');
  expect(result).toHaveTextContent('SQL: team work only; not personal support from this source');
  expect(result).toHaveTextContent('Part of the explanation is resolved. Other details remain unknown');
  expect(screen.getByText(detail.clarifications[0].answer!)).toBeVisible();
  expect(screen.getByRole('button',{name:'Edit explanation'})).toBeEnabled();
 });
 it('retries interpretation of a durably saved answer without resubmitting or losing the original text',async()=>{
  const detail=savedCv();detail.clarifications=[{...answered(detail),interpretation_status:'failed',interpretation:null,interpretation_error:'Provider unavailable',resolution:'unresolved'}];
  const updated={...detail,version:3,clarifications:[answered(detail)]};vi.mocked(cvApi.retryInterpretation).mockResolvedValue(updated);const onSaved=vi.fn();render(review(detail,onSaved));
  expect(screen.getByText(detail.clarifications[0].answer!)).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'Retry interpretation'}));
  await waitFor(()=>expect(onSaved).toHaveBeenCalledWith(updated));
  expect(cvApi.retryInterpretation).toHaveBeenCalledWith(detail.id,'answer-one',expect.objectContaining({expected_version:1,mutation_id:expect.any(String)}),'token',expect.any(AbortSignal));
  expect(cvApi.answer).not.toHaveBeenCalled();
 });
 it('keeps an inability to clarify separate from a resolved capability',()=>{
  const detail=savedCv();const question=answered(detail);detail.clarifications=[{...question,answer:'I do not know.',resolution:'unanswerable',interpretation:{...question.interpretation!,claims:[],summary:'This contribution remains unknown.',resolved_uncertainties:[],remaining_uncertainties:['personal_contribution']}}];render(review(detail));
  expect(screen.getByText(/You could not clarify this further/)).toHaveTextContent('does not establish a missing capability');
 });
});

describe('effective skills and dates',()=>{
 it('renders a project-derived skill and requires explicit matching against its contributing project',async()=>{
  const detail=savedCv();detail.items=[detail.items[0]];detail.skills[0].item_ids=[detail.items[0].id];
  const view=render(review(detail));expect(within(screen.getByRole('region',{name:'Potential skills'})).getByText('Python')).toBeVisible();
  expect(within(screen.getByRole('region',{name:'Potential skills'})).getByRole('link')).toHaveAttribute('href',`#cv-item-${detail.items[0].id}`);view.unmount();
  vi.mocked(cvApi.addDeclaration).mockResolvedValue({...emptyDeclarations,version:1});render(<CapabilityDeclarations data={emptyDeclarations} selectedCv={detail} token="token" signal={signal()} onSaved={vi.fn()} refresh={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText('Capability name'),{target:{value:'Python'}});fireEvent.change(screen.getByRole('textbox',{name:'Capability description'}),{target:{value:'I also cleaned another dataset.'}});
  expect(screen.getByRole('button',{name:'Add capability'})).toBeDisabled();fireEvent.click(screen.getByRole('radio',{name:/Attach to CV evidence: Team dashboard/}));fireEvent.click(screen.getByRole('button',{name:'Add capability'}));
  await waitFor(()=>expect(cvApi.addDeclaration).toHaveBeenCalled());expect(vi.mocked(cvApi.addDeclaration).mock.calls[0][0].cv_match).toEqual({cv_id:detail.id,item_id:detail.items[0].id,cv_version:1});
 });
 it('preserves partial date precision and does not derive experience months from dates',async()=>{
  const detail=savedCv();detail.items[0].experience_months=6;vi.mocked(cvApi.edit).mockResolvedValue({...detail,version:2});render(review(detail));fireEvent.click(screen.getByRole('button',{name:'Edit or remove Team dashboard'}));
  fireEvent.change(screen.getByLabelText('Start date'),{target:{value:'2023'}});fireEvent.change(screen.getByLabelText('End date'),{target:{value:'2024-02'}});fireEvent.click(screen.getByRole('button',{name:'Save correction'}));
  await waitFor(()=>expect(cvApi.edit).toHaveBeenCalled());expect(vi.mocked(cvApi.edit).mock.calls[0][2]).toMatchObject({start_date:'2023',end_date:'2024-02',ongoing:false,experience_months:6});
 });
 it('rejects invalid dates while preserving the draft and lets an ongoing item explicitly clear the end date',async()=>{
  const detail=savedCv();vi.mocked(cvApi.edit).mockResolvedValue({...detail,version:2});render(review(detail));fireEvent.click(screen.getByRole('button',{name:'Edit or remove Team dashboard'}));
  fireEvent.change(screen.getByLabelText('Start date'),{target:{value:'2023-02-29'}});fireEvent.click(screen.getByRole('button',{name:'Save correction'}));expect(await screen.findByRole('alert')).toHaveTextContent('valid YYYY');expect(cvApi.edit).not.toHaveBeenCalled();expect(screen.getByLabelText('Start date')).toHaveValue('2023-02-29');
  fireEvent.change(screen.getByLabelText('Start date'),{target:{value:'2024-02-29'}});fireEvent.change(screen.getByLabelText('End date'),{target:{value:'2025'}});fireEvent.click(screen.getByRole('checkbox',{name:'Still ongoing'}));expect(screen.getByLabelText('End date')).toHaveValue('');fireEvent.click(screen.getByRole('button',{name:'Save correction'}));
  await waitFor(()=>expect(cvApi.edit).toHaveBeenCalled());expect(vi.mocked(cvApi.edit).mock.calls[0][2]).toMatchObject({start_date:'2024-02-29',end_date:null,ongoing:true});
 });
 it.each(['focus','online'])('refreshes changed saved facts on %s while retaining an active correction draft',async event=>{
  let detail=savedCv();vi.mocked(cvApi.list).mockImplementation(async()=>({cvs:[detail],selection:{cv_id:detail.id,version:1}}));vi.mocked(cvApi.get).mockImplementation(async()=>detail);vi.mocked(cvApi.questions).mockImplementation(async()=>clarificationState(detail,confirmedTarget,true));
  render(<ResumePreview/>);fireEvent.click(screen.getByText('Your CV summary',{selector:'summary span'}));fireEvent.click(await screen.findByRole('button',{name:'Edit or remove Team dashboard'}));fireEvent.change(screen.getByRole('textbox',{name:'Description'}),{target:{value:'My unsaved description'}});
  detail={...detail,version:2,items:detail.items.map(item=>({...item,description:'Updated elsewhere'}))};await act(async()=>window.dispatchEvent(new Event(event)));
  await screen.findByText(/This CV changed while you were editing/);expect(screen.getByRole('textbox',{name:'Description'})).toHaveValue('My unsaved description');expect(screen.getByRole('button',{name:'Save correction'})).toBeDisabled();expect(screen.getByText('Latest saved: Updated elsewhere')).toBeVisible();
 });
});

describe('source reconciliation',()=>{
 function candidate(detail:CvDetail):Reconciliation{return {cv_id:detail.id,cv_version:detail.version,candidate_id:'candidate-one',source_cv_id:detail.id,previous_items:detail.items,candidate_items:[{...detail.items[0],id:'new-project',title:'Reinterpreted project',description:'New source interpretation'}],affected_item_ids:[detail.items[0].id],previous_answers:[answered(detail)],extraction:metadata,notices:[]};}
 it('requires an explicit source decision and preserves original answers while reviewing the new evidence',async()=>{
  const detail={...savedCv(),reconciliation_candidate_id:'candidate-one'};const pending=candidate(detail);vi.mocked(cvApi.reconciliation).mockResolvedValue(pending);vi.mocked(cvApi.resolveReconciliation).mockResolvedValue({...detail,version:2,reconciliation_candidate_id:null});
  render(<SourceReconciliation detail={detail} list={null} token="token" signal={signal()} onSaved={vi.fn()} refresh={vi.fn()}/>);
  const choice=await screen.findByLabelText('Reconcile Team dashboard');expect(choice).toHaveValue('');expect(screen.getByRole('button',{name:'Accept reviewed extraction'})).toBeDisabled();expect(screen.getByText(pending.previous_answers[0].answer!)).toBeVisible();
  fireEvent.change(choice,{target:{value:'new-project'}});fireEvent.click(screen.getByRole('button',{name:'Accept reviewed extraction'}));await waitFor(()=>expect(cvApi.resolveReconciliation).toHaveBeenCalled());
  expect(vi.mocked(cvApi.resolveReconciliation).mock.calls[0][1]).toMatchObject({candidate_id:'candidate-one',expected_version:1,action:'accept_candidate',choices:[{item_id:detail.items[0].id,target_item_id:'new-project'}]});
 });
 it('retains chosen mappings on conflict but requires review before applying a newer comparison',async()=>{
  const detail={...savedCv(),reconciliation_candidate_id:'candidate-one'},pending=candidate(detail),refresh=vi.fn().mockResolvedValue(undefined),controller=signal();vi.mocked(cvApi.reconciliation).mockResolvedValue(pending);vi.mocked(cvApi.resolveReconciliation).mockRejectedValue(new CvApiError('Source changed',409));
  const props={list:null,token:'token',signal:controller,onSaved:vi.fn(),refresh};const view=render(<SourceReconciliation {...props} detail={detail}/>);fireEvent.change(await screen.findByLabelText('Reconcile Team dashboard'),{target:{value:'new-project'}});fireEvent.click(screen.getByRole('button',{name:'Accept reviewed extraction'}));await screen.findByRole('alert');expect(refresh).toHaveBeenCalled();
  vi.mocked(cvApi.reconciliation).mockResolvedValue({...pending,cv_version:2});view.rerender(<SourceReconciliation {...props} detail={{...detail,version:2}}/>);await screen.findByText(/Your choices are retained but cannot be applied/);expect(screen.getByLabelText('Reconcile Team dashboard')).toHaveValue('new-project');expect(screen.getByRole('button',{name:'Accept reviewed extraction'})).toBeDisabled();
 });
});

describe('manual evidence links',()=>{
 it('preserves a declaration when its linked source is removed and lets the user keep it standalone',async()=>{
  const detail=savedCv(),declaration:Declaration={id:'declaration-one',name:'Python',skill_id:'python',description:'My separate Python experience.',provenance:'user_declared',attached_to:{cv_id:detail.id,item_id:detail.items[1].id,cv_version:1},created_at:'2026-10-28T00:00:00Z',updated_at:'2026-10-28T00:00:00Z'},data={version:4,declarations:[declaration]};
  vi.mocked(cvApi.updateAttachment).mockResolvedValue({version:5,declarations:[{...declaration,attached_to:null}]});const onSaved=vi.fn();render(<DeclarationAttachment declaration={declaration} link={{declaration_id:declaration.id,status:'removed',selected:true,current_cv_version:2}} linkError="" data={data} selectedCv={detail} token="token" signal={signal()} onSaved={onSaved} refresh={vi.fn()}/>);
  expect(screen.getByText(/Your declaration is retained/)).toBeVisible();fireEvent.click(screen.getByRole('button',{name:'Review CV link'}));fireEvent.change(screen.getByRole('combobox'),{target:{value:'standalone'}});fireEvent.click(screen.getByRole('button',{name:'Save link choice'}));await waitFor(()=>expect(onSaved).toHaveBeenCalled());expect(vi.mocked(cvApi.updateAttachment).mock.calls[0][0]).toMatchObject({expected_version:4,declaration_id:declaration.id,cv_match:null});
 });
});

"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Icon } from '@/components/ui/icon';
import { CardSkeleton, EmptyState, PageTitle } from '@/components/ui/workspace-ui';
import { useProfile } from '@/features/profile/profile-provider';
import { cvApi, CvApiError } from '@/lib/api/cv';
import { ExtractedResults } from './extracted-results';
import { SourceReconciliation } from './source-reconciliation';
import { CvConversationPanel } from './cv-conversation';
import { CvProcessingProgress } from './cv-processing-progress';
import { SavedCvCard } from './saved-cv-card';
import { SkillsProfileSummary } from './skills-profile-summary';
import { FirstUploadNextSteps, SkillsProcessing } from './skills-states';
import type { CvDetail, CvList, CvPolicy, Declarations, Questions, SkillsProfile } from './types';
import { errorText } from '@/lib/errors';

const processing=(status:string)=>status==='queued'||status==='processing';
const mergeCvs=(first:CvList['cvs'],next:CvList['cvs'])=>[...new Map([...first,...next].map(cv=>[cv.id,cv])).values()];
export function ResumePreview() {
 const {token,account}=useProfile();
 return token&&account?<ResumeWorkspace key={`${account.id}:${token}`} token={token}/>:null;
}
function ResumeWorkspace({token}:{token:string}) {
 const [docked,setDocked]=useState(false),[uploadOpen,setUploadOpen]=useState(()=>typeof window!=='undefined'&&new URLSearchParams(window.location.search).get('upload')==='1');
 const [policy,setPolicy]=useState<CvPolicy|null>(null),[list,setList]=useState<CvList|null>(null),[detail,setDetail]=useState<CvDetail|null>(null),[selectedCv,setSelectedCv]=useState<CvDetail|null>(null),[questions,setQuestions]=useState<Questions|null>(null),[declarations,setDeclarations]=useState<Declarations|null>(null);
 const [policyError,setPolicyError]=useState(''),[listError,setListError]=useState(''),[detailError,setDetailError]=useState(''),[declarationError,setDeclarationError]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [viewId,setViewId]=useState<string|null>(null),[loading,setLoading]=useState(true),[detailLoading,setDetailLoading]=useState(false),[busy,setBusy]=useState(''),[file,setFile]=useState<File|null>(null),[reuploadTarget,setReuploadTarget]=useState<CvDetail|null>(null);
 const [skillsProfile,setSkillsProfile]=useState<SkillsProfile|null>(null),[skillsError,setSkillsError]=useState('');
 const [chatWorking,setChatWorking]=useState(false);
 const [chatDraft,setChatDraft]=useState('');
 const [chatOpen,setChatOpen]=useState(false),[chatCvId,setChatCvId]=useState<string|null|undefined>(undefined);
 const [reviewLaterId,setReviewLaterId]=useState<string|null>(null);
 const [mountedReviewId,setMountedReviewId]=useState<string|null>(null);
 const waitingForCv=typeof chatCvId==='string'&&(detail?.id!==chatCvId||detail.status!=='ready');
 useEffect(()=>{
  setMountedReviewId(previous=>typeof chatCvId==='string'&&(!waitingForCv||previous===chatCvId)?chatCvId:null);
 },[chatCvId,waitingForCv]);
 const [summaryOpen,setSummaryOpen]=useState(false);
 const [listRefreshing,setListRefreshing]=useState(false),[moreLoading,setMoreLoading]=useState(false),[moreError,setMoreError]=useState('');
 const loadedPages=useRef(1);
 const resultsPanel=useRef<HTMLElement>(null);
 const [preparing,setPreparing]=useState<string|null>(null),[prepareError,setPrepareError]=useState('');
 const prepareMutation=useRef<{body:string;id:string}|null>(null);
 const viewedCv=useRef(viewId);viewedCv.current=viewId;
 const lifetime=useRef(new AbortController()),listSequence=useRef(0),detailSequence=useRef(0),detailController=useRef<AbortController|null>(null),fileInput=useRef<HTMLInputElement>(null),uploadKey=useRef(crypto.randomUUID()),mutation=useRef<{body:string;id:string}|null>(null),pendingUpload=useRef(false),selectionRef=useRef<string|null>(null);
 const getKey=(body:unknown)=>{const value=JSON.stringify(body);if(mutation.current?.body!==value)mutation.current={body:value,id:crypto.randomUUID()};return mutation.current!.id;};
 const getPolicy=useCallback(async()=>{try{const value=await cvApi.policy(token,lifetime.current.signal);if(!lifetime.current.signal.aborted){setPolicy(value);setPolicyError('');}}catch(cause){if(!lifetime.current.signal.aborted)setPolicyError(errorText(cause, 'Could not load upload policy.'));}},[token]);
 const getSkillsProfile=useCallback(async()=>{try{const value=await cvApi.skillsProfile(token,lifetime.current.signal);if(!lifetime.current.signal.aborted){setSkillsProfile(value);setSkillsError('');}}catch(cause){if(!lifetime.current.signal.aborted)setSkillsError(errorText(cause, 'Could not load your skills profile.'));}},[token]);
 const getDeclarations=useCallback(async()=>{try{const value=await cvApi.declarations(token,lifetime.current.signal);if(!lifetime.current.signal.aborted){setDeclarations(value);setDeclarationError('');}}catch(cause){if(!lifetime.current.signal.aborted)setDeclarationError(errorText(cause, 'Could not load manual capabilities.'));}},[token]);
 const getList=useCallback(async()=>{
  const seq=++listSequence.current,pageCount=loadedPages.current;setListRefreshing(true);setMoreLoading(false);
  try{let value=await cvApi.list(token,lifetime.current.signal);const cursors=new Set<string>();
   for(let page=1;page<pageCount&&value.next_cursor;page++){
    if(lifetime.current.signal.aborted||seq!==listSequence.current)return;
    const cursor=value.next_cursor;if(cursors.has(cursor))throw new Error('Could not finish refreshing saved CVs. Try again.');cursors.add(cursor);
    const next=await cvApi.list(token,lifetime.current.signal,cursor);if(next.next_cursor===cursor)throw new Error('Could not finish refreshing saved CVs. Try again.');value={...next,cvs:mergeCvs(value.cvs,next.cvs)};
   }
   if(lifetime.current.signal.aborted||seq!==listSequence.current)return;setList(value);setListError('');setMoreError('');selectionRef.current=value.selection.cv_id;
   if(value.selection.cv_id){const selected=await cvApi.get(value.selection.cv_id,token,lifetime.current.signal);if(!lifetime.current.signal.aborted&&seq===listSequence.current)setSelectedCv(selected);}else setSelectedCv(null);
  }catch(cause){if(!lifetime.current.signal.aborted&&seq===listSequence.current)setListError(errorText(cause, 'Could not load saved CVs.'));}finally{if(!lifetime.current.signal.aborted&&seq===listSequence.current){setLoading(false);setListRefreshing(false);}}
 },[token]);
 async function loadMore(){
  const cursor=list?.next_cursor;if(!cursor||moreLoading||listRefreshing)return;
  const seq=++listSequence.current;setMoreLoading(true);setMoreError('');
  try{const value=await cvApi.list(token,lifetime.current.signal,cursor);if(lifetime.current.signal.aborted||seq!==listSequence.current)return;
   if(value.next_cursor===cursor)throw new Error('Could not load older CVs. Try again in a moment.');
   setList(previous=>previous?{...previous,cvs:mergeCvs(previous.cvs,value.cvs),next_cursor:value.next_cursor}:previous);loadedPages.current++;
  }catch(cause){if(!lifetime.current.signal.aborted&&seq===listSequence.current)setMoreError(errorText(cause, 'Could not load older CVs.'));}
  finally{if(!lifetime.current.signal.aborted&&seq===listSequence.current)setMoreLoading(false);}
 }
 const getDetail=useCallback(async(id:string)=>{
  const seq=++detailSequence.current;detailController.current?.abort();const controller=new AbortController();detailController.current=controller;setDetailLoading(true);
  try{let value=await cvApi.get(id,token,controller.signal);if(lifetime.current.signal.aborted||seq!==detailSequence.current||viewedCv.current!==id)return;setDetail(value);setDetailError('');
   try{const clarification=await cvApi.questions(id,token,controller.signal);
    if(clarification.cv_version!==value.version)value=await cvApi.get(id,token,controller.signal);
    if(lifetime.current.signal.aborted||seq!==detailSequence.current||viewedCv.current!==id)return;
    if(clarification.cv_version!==value.version)throw new Error('This CV changed while its questions were loading. Try again in a moment.');
    setDetail(value);setQuestions(clarification);
   }catch{if(!lifetime.current.signal.aborted&&seq===detailSequence.current&&viewedCv.current===id)setQuestions(null);}
  }catch(cause){if(!lifetime.current.signal.aborted&&!controller.signal.aborted&&seq===detailSequence.current)setDetailError(errorText(cause, 'Could not load this CV.'));}finally{if(!lifetime.current.signal.aborted&&seq===detailSequence.current)setDetailLoading(false);}
 },[token]);
 useEffect(()=>{if(lifetime.current.signal.aborted)lifetime.current=new AbortController();void getPolicy();void getList();void getDeclarations();void getSkillsProfile();return()=>{lifetime.current.abort();detailController.current?.abort();listSequence.current++;detailSequence.current++;};},[getPolicy,getList,getDeclarations,getSkillsProfile]);
 useEffect(()=>{
  const dirty=()=>Boolean(document.querySelector('.cv-workspace [data-unsaved="true"]'));
  function unload(event:BeforeUnloadEvent){if(dirty()){event.preventDefault();event.returnValue='';}}
  function leave(event:MouseEvent){const anchor=(event.target as Element|null)?.closest?.('a[href]');if(!dirty()||!anchor||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;const url=new URL(anchor.getAttribute('href')!,location.href);if(url.pathname===location.pathname&&url.origin===location.origin)return;if(!window.confirm('Leave this page and discard unsaved CV or capability drafts?')){event.preventDefault();event.stopImmediatePropagation();}}
  window.addEventListener('beforeunload',unload);document.addEventListener('click',leave,true);return()=>{window.removeEventListener('beforeunload',unload);document.removeEventListener('click',leave,true);};
 },[]);
 useEffect(()=>{if(!viewId&&list?.selection.cv_id)setViewId(list.selection.cv_id);},[list,viewId]);
 // The most recent upload becomes the active CV once it is ready (tried once per upload, so a later manual choice of an older CV is kept).
 const autoActivated=useRef<string|null>(null);
 useEffect(()=>{if(!list||busy)return;const newest=[...list.cvs].filter(cv=>cv.status!=='failed').sort((x,y)=>y.created_at.localeCompare(x.created_at))[0];if(!newest||newest.status!=='ready'||list.selection.cv_id===newest.id||autoActivated.current===newest.id)return;autoActivated.current=newest.id;void select(newest.id,true);});
 // Saved CVs but none active: show the newest ready one so an unreviewed CV lands on its review screen, not an empty page.
 useEffect(()=>{if(viewId||!list||list.selection.cv_id)return;const newest=[...list.cvs].filter(cv=>cv.status==='ready').sort((x,y)=>y.created_at.localeCompare(x.created_at))[0];if(newest)setViewId(newest.id);},[list,viewId]);
 useEffect(()=>{if(viewId)void getDetail(viewId);},[viewId,getDetail]);
 useEffect(()=>{if(!list?.cvs.some(cv=>processing(cv.status))&&!(detail&&processing(detail.status)))return;const timer=setInterval(()=>{void getList();if(viewId&&(list?.cvs.some(cv=>cv.id===viewId&&processing(cv.status))||(detail?.id===viewId&&processing(detail.status))))void getDetail(viewId);},3000);return()=>clearInterval(timer);},[list,viewId,detail?.status,getList,getDetail]);
 const foregroundRefresh=useRef(false);
 useEffect(()=>{
  async function revalidate(){
   if(document.visibilityState==='hidden'||foregroundRefresh.current||busy||preparing||document.querySelector('.cv-workspace [aria-busy="true"]'))return;
   foregroundRefresh.current=true;
   try{await Promise.allSettled([getList(),getDeclarations(),getSkillsProfile(),...(viewedCv.current?[getDetail(viewedCv.current)]:[])]);}
   finally{foregroundRefresh.current=false;}
  }
  window.addEventListener('focus',revalidate);window.addEventListener('online',revalidate);document.addEventListener('visibilitychange',revalidate);
  return()=>{window.removeEventListener('focus',revalidate);window.removeEventListener('online',revalidate);document.removeEventListener('visibilitychange',revalidate);};
 },[busy,preparing,getList,getDeclarations,getSkillsProfile,getDetail]);
 async function refresh(){await Promise.allSettled([getList(),getDeclarations(),getSkillsProfile(),...(viewId?[getDetail(viewId)]:[])]);}
 async function saved(value:CvDetail){const current=viewedCv.current===value.id;if(current){setDetail(value);setQuestions(p=>p?{...p,cv_version:value.version,questions:p.questions.flatMap(q=>{const updated=value.clarifications.find(item=>item.id===q.id);return updated?[updated]:[];})}:p);}setList(p=>p?{...p,cvs:p.cvs.map(c=>c.id===value.id?value:c)}:p);if(selectionRef.current===value.id)setSelectedCv(value);setNotice('Changes saved. Dependent results may need review; no analysis was regenerated.');if(current)await getDetail(value.id);}
 async function prepareQuestions(){
  if(!detail||!questions?.context||detailLoading||preparing||questions.cv_version!==detail.version)return;
  const id=detail.id,seq=detailSequence.current,context=questions.context;
  const body={expected_version:detail.version,career_target_id:context.id,career_target_version:context.version,career_target_selection_version:context.selection_version};
  const signature=JSON.stringify({cv_id:id,...body});if(prepareMutation.current?.body!==signature)prepareMutation.current={body:signature,id:crypto.randomUUID()};
  setPreparing(id);setPrepareError('');
  try{await cvApi.prepare(id,{...body,mutation_id:prepareMutation.current.id},token,lifetime.current.signal);
   if(lifetime.current.signal.aborted||viewedCv.current!==id||seq!==detailSequence.current)return;
   await getDetail(id);
  }catch(cause){if(!lifetime.current.signal.aborted&&viewedCv.current===id&&seq===detailSequence.current){setPrepareError(errorText(cause, 'Could not prepare relevant questions.'));if(cause instanceof CvApiError&&cause.status===409)await getDetail(id);}}
  finally{if(!lifetime.current.signal.aborted)setPreparing(current=>current===id?null:current);}
 }
 async function upload(event:FormEvent){
  event.preventDefault();if(busy||!file||!policy)return;setError('');setNotice('');
  const extension=file.name.split('.').pop()?.toLowerCase();if(!file.size||file.size>policy.max_file_bytes||!policy.formats.includes(extension as 'pdf'|'docx')){setError(`Choose a non-empty ${policy.formats.map(f=>f.toUpperCase()).join(' or ')} file up to ${policy.max_file_bytes/(1024*1024)} MiB.`);return;}
  if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Upload this CV and discard unsaved CV or capability drafts?'))return;
  const form=new FormData();form.set('file',file);form.set('mutation_id',uploadKey.current);if(reuploadTarget){form.set('cv_id',reuploadTarget.id);form.set('expected_version',String(reuploadTarget.version));}setBusy('upload');pendingUpload.current=true;
  try{const value=await cvApi.upload(form,token,lifetime.current.signal);if(lifetime.current.signal.aborted)return;viewedCv.current=value.id;detailSequence.current++;detailController.current?.abort();setViewId(value.id);setDetail(value);setQuestions(null);setDetailError('');setChatDraft('');setChatCvId(value.id);setChatOpen(true);reviewUrl(value.id);setFile(null);setReuploadTarget(null);if(fileInput.current)fileInput.current.value='';uploadKey.current=crypto.randomUUID();pendingUpload.current=false;setNotice('Upload saved. Your CV review will start when processing finishes. Make it your active CV when you’re ready.');await getList();}
  catch(cause){if(!lifetime.current.signal.aborted)setError(`${errorText(cause, 'The upload response was interrupted.')} Check saved status before retrying this file. Retry keeps the same request identity.`);}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 async function select(id:string,auto=false){
  if(!list||busy)return;
  const candidate=list.cvs.find(cv=>cv.id===id);
  if(!candidate||candidate.status!=='ready')return;
  if(!auto&&candidate.profile_reviewed_effective_version!==candidate.effective_version&&!window.confirm('This CV has not been reviewed in its current form. elo will use the AI’s interpretation, which may be incomplete or inaccurate. If any roles or responsibilities are not clearly stated in your CV details, the AI may infer skills or levels of experience that do not reflect the skills you currently possess. Review and clarify these details before relying on it.\n\nMake this your active CV anyway?'))return;
  const body={cv_id:id,expected_version:list.selection.version};setBusy(`select:${id}`);setError('');setNotice('');
  try{const value=await cvApi.select({...body,mutation_id:getKey(body)},token,lifetime.current.signal);if(lifetime.current.signal.aborted)return;selectionRef.current=value.cv_id;setList(p=>p?{...p,selection:value}:p);setNotice(auto?'Your most recent CV is now your active CV. Your existing results haven’t been regenerated.':'This is now your active CV. Your existing results haven’t been regenerated.');await getList();}
  catch(cause){if(!lifetime.current.signal.aborted){setError(errorText(cause, 'Could not select this CV.'));if(cause instanceof CvApiError&&cause.status===409)await getList();}}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 async function retry(){
  if(!detail||busy)return;const body={expected_version:detail.version};setBusy('retry');setError('');
  try{const value=await cvApi.retry(detail.operation_id,{...body,mutation_id:getKey({id:detail.operation_id,...body})},token,lifetime.current.signal);if(!lifetime.current.signal.aborted){saved(value);await getList();}}
  catch(cause){if(!lifetime.current.signal.aborted)setError(errorText(cause, 'Could not retry this CV.'));}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 async function deleteCv(cv:CvList['cvs'][number]){
  if(busy||!window.confirm(`Permanently delete ${cv.file_name} (CV ${cv.id})? This removes its extraction, corrections, clarifications and CV conversations, discards its unsaved drafts, and clears it if selected. Manual capabilities and existing analysis/roadmap snapshots remain. This cannot be undone.`))return;
  const body={expected_version:cv.version};setBusy(`delete:${cv.id}`);setError('');setNotice('');
  try{
   const result=await cvApi.delete(cv.id,{...body,mutation_id:getKey({operation:'delete',id:cv.id,...body})},token,lifetime.current.signal);
   if(lifetime.current.signal.aborted)return;
   listSequence.current++;selectionRef.current=result.selection.cv_id;
   setList(previous=>previous?{...previous,cvs:previous.cvs.filter(item=>item.id!==cv.id),selection:result.selection}:previous);
   setSelectedCv(previous=>previous?.id===cv.id?null:previous);
   if(viewedCv.current===cv.id){setSummaryOpen(false);viewedCv.current=null;detailSequence.current++;detailController.current?.abort();setViewId(null);setDetail(null);if(chatCvId===cv.id){setChatOpen(false);setChatDraft('');setChatCvId(undefined);}setQuestions(null);setDetailLoading(false);setDetailError('');setPrepareError('');setPreparing(null);prepareMutation.current=null;}
   if(reuploadTarget?.id===cv.id){setReuploadTarget(null);setFile(null);if(fileInput.current)fileInput.current.value='';uploadKey.current=crypto.randomUUID();pendingUpload.current=false;}
   setNotice('CV deleted. Manual capabilities and existing analysis/roadmap snapshots remain. No replacement CV was selected.');
   await getList();
  }catch(cause){if(!lifetime.current.signal.aborted){setError(errorText(cause, 'Could not delete this CV. Retry with the same request identity.'));if(cause instanceof CvApiError&&cause.status===409)await getList();}}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 function reviewUrl(id:string|null){const url=new URL(window.location.href);url.searchParams.set('review',id??'manual');url.searchParams.delete('cv');url.searchParams.delete('uploaded');if(url.href!==window.location.href)window.history.pushState(null,'',url);}
 function closeReview(){setChatOpen(false);const url=new URL(window.location.href);url.searchParams.delete('review');url.searchParams.delete('uploaded');window.history.replaceState(null,'',url);requestAnimationFrame(()=>{const heading=document.querySelector<HTMLElement>('.cv-workspace h1');heading?.setAttribute('tabindex','-1');heading?.focus();});}
 function reviewLater(unconfirmed=false){
  if(unconfirmed&&!window.confirm('We couldn’t confirm whether your message was saved. Reopen this CV here to retry the original send. Leave the review now?'))return;
  if(!unconfirmed&&chatDraft.trim()&&!window.confirm('Your unsent text stays here while this page is open. Leave the review now?'))return;
  setReviewLaterId(chatCvId??null);
  setNotice(unconfirmed?'Reopen this CV in this tab to check the interrupted send.':'Open this CV again whenever you’re ready to continue its review.');
  closeReview();
 }
 const restoreRoute=useRef<()=>void>(()=>{});
 restoreRoute.current=()=>{
  const params=new URL(window.location.href).searchParams;
  const reviewId=params.get('review'),resultsId=params.get('cv');
  if(reviewId==='manual')openManual(false);
  else if(reviewId)review(reviewId,false);
  else if(resultsId)openResults(resultsId,false);
  else{setChatOpen(false);setSummaryOpen(false);}
 };
 useEffect(()=>{const restore=()=>restoreRoute.current();restore();window.addEventListener('popstate',restore);return()=>window.removeEventListener('popstate',restore);},[]);
 useEffect(()=>{
  if(!chatOpen||!chatCvId)return;
  const frame=requestAnimationFrame(()=>document.querySelector<HTMLElement>('.cv-review-screen .cv-chat h2')?.focus());
  return()=>cancelAnimationFrame(frame);
 },[chatOpen,chatCvId]);
 function review(id:string,updateUrl=true){if(busy)return;if(chatCvId===id&&viewId===id){setChatOpen(true);if(updateUrl)reviewUrl(id);requestAnimationFrame(()=>document.querySelector('.cv-chat')?.scrollIntoView?.({block:'start'}));return;}if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Leave this CV and discard its unsaved draft?'))return;setSummaryOpen(false);viewedCv.current=id;detailSequence.current++;detailController.current?.abort();setViewId(id);setDetail(null);setQuestions(null);setDetailError('');setPrepareError('');setPreparing(null);if(chatCvId!==id)setChatDraft('');setChatCvId(id);setChatOpen(true);if(updateUrl)reviewUrl(id);if(id===viewId)void getDetail(id);requestAnimationFrame(()=>document.querySelector('.cv-chat')?.scrollIntoView?.({block:'start'}));}
 function inspectCv(id:string){
  if(busy)return false;
  const switchingReview=typeof chatCvId==='string'&&chatCvId!==id;
  if((viewedCv.current!==id||switchingReview)&&document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Leave this CV and discard its unsaved draft?'))return false;
  if(switchingReview){setChatCvId(undefined);setChatDraft('');}
  if(viewedCv.current!==id||detail?.id!==id){
   viewedCv.current=id;detailSequence.current++;detailController.current?.abort();setViewId(id);setDetail(null);setQuestions(null);
   if(id===viewId)void getDetail(id);
  }
  setSummaryOpen(true);
  return true;
 }
 function closeResults(updateUrl=true){
  setSummaryOpen(false);
  if(updateUrl){const url=new URL(window.location.href);if(url.searchParams.has('cv')){url.searchParams.delete('cv');window.history.pushState(null,'',url);}}
  requestAnimationFrame(()=>document.getElementById('your-cvs')?.scrollIntoView?.({block:'start'}));
 }
 function openResults(id:string,updateUrl=true){
  if(!inspectCv(id))return;
  setChatOpen(false);
  if(updateUrl){
   const url=new URL(window.location.href);
   url.searchParams.delete('review');url.searchParams.delete('uploaded');url.searchParams.set('cv',id);
   if(url.href!==window.location.href)window.history.pushState(null,'',url);
  }
  requestAnimationFrame(()=>{
   resultsPanel.current?.querySelector<HTMLElement>('h1')?.focus();
   resultsPanel.current?.scrollIntoView?.({block:'start'});
  });
 }
 function reupload(value:CvDetail){if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Reprocess this source and discard its unsaved draft?'))return;setReuploadTarget(value);setFile(null);if(fileInput.current){fileInput.current.value='';fileInput.current.focus();}uploadKey.current=crypto.randomUUID();setError('');}
 function openManual(updateUrl=true){if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&chatCvId!==null&&!window.confirm('Switch to manual entry and discard the unsent conversation draft?'))return;if(chatCvId!==null)setChatDraft('');setChatCvId(null);setChatOpen(true);if(updateUrl)reviewUrl(null);}
 async function saveCvProfile(){const source=detail??selectedCv;if(!source||busy||chatWorking)return;const body={expected_version:source.version};setBusy('cv-profile');setSkillsError('');try{const value=await cvApi.saveCvProfile(source.id,{...body,mutation_id:getKey({operation:'cv-profile',id:source.id,...body})},token,lifetime.current.signal);if(!lifetime.current.signal.aborted){if(viewedCv.current===source.id)setDetail(value);if(selectionRef.current===source.id)setSelectedCv(value);await getList();}}catch(cause){if(!lifetime.current.signal.aborted){setSkillsError(errorText(cause, 'Could not save this CV review. Retry without changing sources.'));if(cause instanceof CvApiError&&cause.status===409){mutation.current=null;await refresh();}}}finally{if(!lifetime.current.signal.aborted)setBusy('');}}
 async function saveProfile(){if(!skillsProfile||busy||chatWorking)return;const body={expected_version:skillsProfile.version,status:'saved' as const,areas:skillsProfile.areas,entries:skillsProfile.entries};setBusy('profile');setSkillsError('');try{const value=await cvApi.saveSkillsProfile({...body,mutation_id:getKey({operation:'skills-profile',...body})},token,lifetime.current.signal);if(!lifetime.current.signal.aborted){setSkillsProfile(value);await getDeclarations();}}catch(cause){if(!lifetime.current.signal.aborted){setSkillsError(errorText(cause, 'Could not save your skills profile. Retry your saved draft.'));if(cause instanceof CvApiError&&cause.status===409){mutation.current=null;await getSkillsProfile();}}}finally{if(!lifetime.current.signal.aborted)setBusy('');}}
 function selectDroppedFile(value:File){if(busy||!policy)return;if(value.size>policy.max_file_bytes){setError(`This file exceeds the ${policy.max_file_bytes/(1024*1024)} MiB limit. Choose a smaller file.`);return;}setFile(value);uploadKey.current=crypto.randomUUID();pendingUpload.current=false;setError('');}
 const firstUpload=Boolean(list&&!list.cvs.length&&(skillsProfile||skillsError)&&!skillsProfile?.entries.length&&(!skillsProfile||skillsProfile.status==='empty')&&!declarations?.declarations.length&&!chatOpen);
 const readingCv=list&&!list.selection.cv_id&&!skillsProfile?.entries.length?list.cvs.find(cv=>cv.id===viewId&&processing(cv.status))??list.cvs.find(cv=>processing(cv.status)):undefined;
 const [dragging,setDragging]=useState(false);
 // Right after an upload the review is still waiting on extraction: show the reading page, not the empty chat shell.
 const waitingProcessing=Boolean(!docked&&chatOpen&&waitingForCv&&typeof chatCvId==='string'&&detail?.id===chatCvId&&processing(detail.status)&&!detailError);
 const shownCv=waitingProcessing?list?.cvs.find(cv=>cv.id===chatCvId)??detail:readingCv;
 const readingId=readingCv?.id;
 useEffect(()=>{if(!viewId&&readingId)setViewId(readingId);},[viewId,readingId]);
 const recentReview=list?.cvs.find(cv=>cv.id===reviewLaterId)??(detail?.id===reviewLaterId?detail:undefined)??list?.cvs.find(cv=>cv.status!=='failed');
 return <section className={`page on cv-workspace${chatOpen&&!docked&&!waitingProcessing?' cv-review-screen':''}${docked&&chatOpen?' cv-has-dock':''}`}><div hidden={(chatOpen&&!docked&&!waitingProcessing)||summaryOpen}>
  {(!chatOpen||docked||waitingProcessing)&&(shownCv&&!firstUpload?<SkillsProcessing token={token} title={<PageTitle title="Skills Profile" info="Levels come from your CV and review answers; practical competence hasn’t been tested. A missing detail is uncertain, not absent. Job-specific evaluation happens against your Career Goal."/>} cv={shownCv} items={detail?.id===shownCv.id?detail.items:[]} busy={Boolean(busy)} cancel={()=>{const item=list?.cvs.find(cv=>cv.id===shownCv.id);if(item)void deleteCv(item);}} review={waitingProcessing?undefined:()=>review(shownCv.id)} later={waitingProcessing?()=>reviewLater():undefined}/>:<SkillsProfileSummary firstUpload={firstUpload} token={token} title={<PageTitle title="Skills Profile" info="Levels come from your CV and review answers; practical competence hasn’t been tested. A missing detail is uncertain, not absent. Job-specific evaluation happens against your Career Goal."/>} profile={skillsProfile} cv={detail??selectedCv} recentReview={recentReview} declarations={declarations} error={skillsError} chat={()=>{if(docked&&chatOpen){closeReview();return;}setDocked(true);const id=list?.selection.cv_id;if(id)review(id);else openManual();}} chatOpen={docked&&chatOpen} cvs={list?.cvs} activeCvId={list?.selection.cv_id??null} viewCv={id=>openResults(id)} makeActive={id=>void select(id)} removeCv={value=>{const item=list?.cvs.find(cv=>cv.id===value.id);if(item)void deleteCv(item);}} busy={Boolean(busy)} upload={()=>{setUploadOpen(true);requestAnimationFrame(()=>{document.getElementById('your-cvs')?.scrollIntoView?.({block:'start',behavior:'smooth'});fileInput.current?.focus({preventScroll:true});});}} build={()=>openManual()} review={review} retry={()=>void getSkillsProfile()} save={()=>void saveProfile()} saving={busy==='profile'} saveCv={()=>void saveCvProfile()} savingCv={busy==='cv-profile'} pending={chatWorking}/>)}
  <div>
  <p aria-label="Selected CV" className={`small cv-baseline-status${firstUpload||readingCv?' cv-visually-hidden':''}`}>{list?.selection.cv_id?<>Active CV: <strong>{list.cvs.find(cv=>cv.id===list.selection.cv_id)?.display_name??list.cvs.find(cv=>cv.id===list.selection.cv_id)?.file_name??selectedCv?.display_name??selectedCv?.file_name??'Saved CV'}</strong><span className="cv-visually-hidden"> {list.selection.cv_id}</span></>:list?'No active CV yet.':''}</p>
  <div className={`cv-top-grid${firstUpload?' is-first-upload':''}`} id="your-cvs"><section hidden={!firstUpload&&!uploadOpen&&!file&&!reuploadTarget} className="card pad cv-upload-panel" aria-label="Upload your CV">{policy?<><form className="cv-form" onSubmit={upload}>{reuploadTarget&&<div className="cv-warning"><p>Re-uploading the exact source for {reuploadTarget.file_name} · CV {reuploadTarget.id}. Its saved corrections and removals will be preserved. A changed document needs a separate upload.</p><button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={()=>{setReuploadTarget(null);uploadKey.current=crypto.randomUUID();}}>Cancel source re-upload</button></div>}<div className={`skills-dropzone${dragging?' is-over':''}${file?' has-file':''}`} onDragOver={event=>{event.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)} onDrop={event=>{event.preventDefault();setDragging(false);if(event.dataTransfer.files.length===1)selectDroppedFile(event.dataTransfer.files[0]);else setError('Choose one CV at a time.');}}>{file?<><span className="skills-drop-icon is-done" aria-hidden="true"><Icon name="check"/></span><h2>CV selected</h2><p className="skills-file-chip" role="status"><Icon name="doc"/><strong>{file.name}</strong><span>{file.size<1024*1024?`${Math.max(1,Math.round(file.size/1024))} KB`:`${(file.size/(1024*1024)).toFixed(1)} MB`}</span></p><p>Ready to upload. Check the file below, then choose Upload CV.</p></>:<><span className="skills-drop-icon" aria-hidden="true"><Icon name="doc"/></span><h2>Upload your CV</h2><p>Drag a file here, or choose one from your device.</p></>}<label className={`btn${file?'':' pri'} skills-drop-choose`}><Icon name="up"/>{file?'Choose a different file':'Choose CV file'}<input ref={fileInput} id="cv-document" aria-label="CV document" type="file" accept={policy.formats.map(f=>`.${f}`).join(',')} disabled={Boolean(busy)} onChange={e=>{const value=e.target.files?.[0];if(value)selectDroppedFile(value);else setFile(null);}}/></label></div><p className="small">Text-based {policy.formats.map(f=>f.toUpperCase()).join(' or ')} · Up to {policy.max_file_bytes/(1024*1024)} MiB. Scanned PDFs need a text-based alternative. Files are private and retained temporarily for processing and retry. The text read from a file stays saved until you delete that CV or upload a replacement.</p>{policy.max_saved_cvs&&policy.max_stored_original_bytes&&<p className="small">Your account can save up to {policy.max_saved_cvs} CVs and retain up to {policy.max_stored_original_bytes/(1024*1024)} MiB of original files at a time.</p>}{!policy.extraction_configured&&<p className="cv-warning">CV extraction is not configured on this server. Your existing saved CVs and manual capabilities remain available. New files cannot be processed until it is configured.</p>}<button className="btn pri" disabled={!file||Boolean(busy)||!policy.extraction_configured}><Icon name="up"/>{busy==='upload'?'Uploading…':pendingUpload.current?'Retry upload':reuploadTarget?'Re-upload same source':'Upload CV'}</button></form></>:<p className="small">{policyError||'Loading supported formats and upload limit…'}</p>}{policyError&&<button className="btn ghost sm" onClick={()=>void getPolicy()}>Retry upload settings</button>}{firstUpload&&<div className="skills-first-chat"><p>Don’t have a CV yet? You can tell elo about your skills and experience in a chat instead.</p><button type="button" className="btn" disabled={Boolean(busy)} onClick={()=>openManual()}>Add skills by chat</button></div>}</section>

  {firstUpload?<FirstUploadNextSteps/>:<section className="card cv-saved cv-library" aria-label="Saved CVs"><header className="cv-library-head"><div><h2>Your CVs</h2><p>elo uses your <strong>active CV</strong> for your skills, goal match and roadmap.</p></div>{list&&<div className="cv-library-count"><span className="cv-library-meter" aria-hidden="true"><i style={{width:`${Math.min(100,Math.round(100*list.cvs.length/(policy?.max_saved_cvs??3)))}%`}}/></span><span><strong>{list.cvs.length}</strong> of {policy?.max_saved_cvs??3} CVs</span></div>}</header><div className="cv-library-scroll" tabIndex={0} role="region" aria-label="Your uploaded CVs">{loading&&<CardSkeleton label="Loading saved CVs…"/>}{listError&&<div role="alert" className="cv-error"><p>{listError}</p><button className="btn ghost sm" onClick={()=>void getList()}>Retry saved CVs</button></div>}{list&&!list.cvs.length&&<EmptyState icon="doc" title="No saved CV yet">Upload a readable CV, choose Build through chat without one.</EmptyState>}
   <div className="cv-list">{list&&[...list.cvs].sort((a,b)=>a.file_name.localeCompare(b.file_name)||b.created_at.localeCompare(a.created_at)).map(cv=><SavedCvCard key={cv.id} cv={cv} active={list.selection.cv_id===cv.id} busy={Boolean(busy)} token={token} review={()=>cv.status==='failed'?inspectCv(cv.id):review(cv.id)} results={()=>openResults(cv.id)} select={()=>void select(cv.id)} remove={()=>void deleteCv(cv)} refresh={getList} saved={value=>{setList(previous=>previous?{...previous,cvs:previous.cvs.map(item=>item.id===value.id?value:item)}:previous);if(viewedCv.current===value.id)setDetail(value);if(selectionRef.current===value.id)setSelectedCv(value);}}/>)}</div>
  {moreError&&<p role="alert" className="cv-error">{moreError}</p>}{list?.next_cursor&&<button type="button" className="btn ghost sm" disabled={moreLoading||listRefreshing} onClick={()=>void loadMore()}>{moreLoading?'Loading older CVs…':'Show more saved CVs'}</button>}
  </div></section>}</div>
  {busy==='upload'&&<p role="status" className="cv-notice">Uploading the file. Once accepted, processing status is saved and can be checked after returning.</p>}{error&&<div role="alert" className="cv-error">{error}</div>}{notice&&<p role="status" className="cv-notice">{notice}</p>}
  {detail && !readingCv && detail.id!==list?.selection.cv_id && <p className="cv-viewing-notice">Reviewing <strong>{detail.file_name}</strong>. {list?.selection.cv_id?'Your selected CV stays unchanged until you choose a different one in Your CVs.':'Choose this ready CV in Your CVs when you want to use it for analysis.'}</p>}
  </div></div>
  {summaryOpen&&viewId&&<section className="cv-results-page" aria-label="Extracted results" ref={resultsPanel}>
   {detailLoading&&!detail&&<p role="status">Loading this CV…</p>}
   {detailError&&<div role="alert" className="cv-error"><p>{detailError}</p><div className="row cv-actions"><button className="btn ghost sm" onClick={()=>void getDetail(viewId)}>Retry this CV</button><button type="button" className="btn ghost sm" onClick={()=>closeResults()}>Back to Skills Profile</button></div></div>}
   {detail&&detail.id===viewId&&(detail.status==='ready'?<ExtractedResults cv={detail} onBack={()=>closeResults()}>
    {detail.id!==list?.selection.cv_id&&<p className="cv-warning">This is not your active CV, so it does not feed your analysis until you make it active in Your CVs.</p>}
    {detail.notices?.map((text,index)=><p className="cv-warning" key={index}>{text}</p>)}
    <SourceReconciliation key={detail.id} detail={detail} list={list} token={token} signal={lifetime.current.signal} onSaved={saved} refresh={refresh}/>
   </ExtractedResults>:<section className="card pad" role={processing(detail.status)?'status':undefined}>
    <button type="button" className="btn ghost sm" onClick={()=>closeResults()}>Back to Skills Profile</button>
    {processing(detail.status)?<><h2>Processing {detail.file_name}</h2><p className="small">Your upload is saved. You can leave and return to check progress. elo checks again automatically; your previous active CV stays in use.</p></>:<><h2>Processing failed: {detail.file_name}</h2><p className="cv-error">{detail.error?.message??'This CV could not be processed.'}</p>{detail.source_available&&detail.error?.retryable?<button className="btn pri sm" disabled={Boolean(busy)} onClick={()=>void retry()}>Retry processing</button>:<><p className="small">Re-upload the exact source file to retry. A changed document should be uploaded as a new CV.</p><button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={()=>{closeResults();reupload(detail);}}>Re-upload this source</button></>}</>}
   </section>)}
  </section>}
  {chatCvId!==undefined&&<div className={docked?'cv-chat-dock':undefined} hidden={!chatOpen}>
   {waitingForCv&&chatCvId&&!waitingProcessing&&<section className="cv-chat" aria-label="CV review progress">
    <header className="cv-chat-header">
     <div><div><h2 tabIndex={-1}>Review your CV</h2><p>{detail?.id===chatCvId?(detail.display_name??detail.file_name):'Loading your CV…'}</p></div></div>
     <button type="button" className="btn ghost sm" onClick={()=>reviewLater()}>Save and review later</button>
    </header>
    <div className="cv-chat-messages">
     {detailError?<div role="alert" className="cv-error"><p>{detailError}</p><button type="button" className="btn ghost sm" onClick={()=>void getDetail(chatCvId)}>Retry loading CV</button></div>:detail?.id===chatCvId&&detail.status==='failed'?<div role="alert">
      <h3>We couldn’t process this CV</h3><p className="cv-error">{detail.error?.message??'Return to Skills Profile to retry this upload.'}</p>
      {detail.source_available&&detail.error?.retryable&&<button type="button" className="btn pri" disabled={Boolean(busy)} onClick={()=>void retry()}>Retry processing</button>}
     </div>:<div className="cv-chat-welcome" role="status">
      <h3>Preparing your CV for review</h3>
      {detail?.id===chatCvId?<><p>Your upload is saved. The first clarification question will appear here when processing finishes. You can come back anytime.</p><CvProcessingProgress cv={detail}/></>:<p>Checking the saved status of this CV.</p>}
     </div>}
     {error&&<p role="alert" className="cv-error">{error}</p>}
    </div>
   </section>}
   {(!waitingForCv||mountedReviewId===chatCvId)&&<CvConversationPanel key={chatCvId??'manual'} hidden={waitingForCv} cvId={chatCvId} detail={detail?.id===chatCvId?detail:selectedCv?.id===chatCvId?selectedCv:null} token={token} draft={chatDraft} onDraftChange={setChatDraft} unavailable={Boolean(busy)||waitingForCv} purpose="skills_profile" autoReview={chatOpen&&!waitingForCv&&!docked} onActivityChanged={setChatWorking} onChanged={refresh} onOpenSummary={chatCvId?()=>openResults(chatCvId):closeReview} onReviewLater={reviewLater}/>}
  </div>}
 </section>;
}

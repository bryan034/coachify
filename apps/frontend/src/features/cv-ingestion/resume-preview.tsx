"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { Icon } from '@/components/ui/icon';
import { EmptyState, PageTitle } from '@/components/ui/workspace-ui';
import { useProfile } from '@/features/profile/profile-provider';
import { cvApi, CvApiError } from '@/lib/api/cv';
import { CvReview } from './cv-review';
import { CapabilityDeclarations } from './capability-declarations';
import { SourceReconciliation } from './source-reconciliation';
import { CvConversationPanel } from './cv-conversation';
import type { CvDetail, CvList, CvPolicy, Declarations, Questions } from './types';

const processing=(status:string)=>status==='queued'||status==='processing';
const date=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
export function ResumePreview() {
 const {token,account}=useProfile();
 return token&&account?<ResumeWorkspace key={`${account.id}:${token}`} token={token}/>:null;
}
function ResumeWorkspace({token}:{token:string}) {
 const [policy,setPolicy]=useState<CvPolicy|null>(null),[list,setList]=useState<CvList|null>(null),[detail,setDetail]=useState<CvDetail|null>(null),[selectedCv,setSelectedCv]=useState<CvDetail|null>(null),[questions,setQuestions]=useState<Questions|null>(null),[declarations,setDeclarations]=useState<Declarations|null>(null);
 const [policyError,setPolicyError]=useState(''),[listError,setListError]=useState(''),[detailError,setDetailError]=useState(''),[declarationError,setDeclarationError]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [viewId,setViewId]=useState<string|null>(null),[loading,setLoading]=useState(true),[detailLoading,setDetailLoading]=useState(false),[busy,setBusy]=useState(''),[file,setFile]=useState<File|null>(null),[reuploadTarget,setReuploadTarget]=useState<CvDetail|null>(null);
 const [filesOpen,setFilesOpen]=useState(false),[summaryOpen,setSummaryOpen]=useState(false);
 const summaryPanel=useRef<HTMLDetailsElement>(null);
 const [preparing,setPreparing]=useState<string|null>(null),[prepareError,setPrepareError]=useState('');
 const prepareMutation=useRef<{body:string;id:string}|null>(null);
 const viewedCv=useRef(viewId);viewedCv.current=viewId;
 const lifetime=useRef(new AbortController()),listSequence=useRef(0),detailSequence=useRef(0),detailController=useRef<AbortController|null>(null),fileInput=useRef<HTMLInputElement>(null),uploadKey=useRef(crypto.randomUUID()),mutation=useRef<{body:string;id:string}|null>(null),pendingUpload=useRef(false),selectionRef=useRef<string|null>(null);
 const getKey=(body:unknown)=>{const value=JSON.stringify(body);if(mutation.current?.body!==value)mutation.current={body:value,id:crypto.randomUUID()};return mutation.current!.id;};
 const getPolicy=useCallback(async()=>{try{const value=await cvApi.policy(token,lifetime.current.signal);if(!lifetime.current.signal.aborted){setPolicy(value);setPolicyError('');}}catch(cause){if(!lifetime.current.signal.aborted)setPolicyError(cause instanceof Error?cause.message:'Could not load upload policy.');}},[token]);
 const getDeclarations=useCallback(async()=>{try{const value=await cvApi.declarations(token,lifetime.current.signal);if(!lifetime.current.signal.aborted){setDeclarations(value);setDeclarationError('');}}catch(cause){if(!lifetime.current.signal.aborted)setDeclarationError(cause instanceof Error?cause.message:'Could not load manual capabilities.');}},[token]);
 const getList=useCallback(async()=>{
  const seq=++listSequence.current;
  try{const value=await cvApi.list(token,lifetime.current.signal);if(lifetime.current.signal.aborted||seq!==listSequence.current)return;setList(value);setListError('');selectionRef.current=value.selection.cv_id;
   if(value.selection.cv_id){const selected=await cvApi.get(value.selection.cv_id,token,lifetime.current.signal);if(!lifetime.current.signal.aborted&&seq===listSequence.current)setSelectedCv(selected);}else setSelectedCv(null);
  }catch(cause){if(!lifetime.current.signal.aborted&&seq===listSequence.current)setListError(cause instanceof Error?cause.message:'Could not load saved CVs.');}finally{if(!lifetime.current.signal.aborted)setLoading(false);}
 },[token]);
 const getDetail=useCallback(async(id:string)=>{
  const seq=++detailSequence.current;detailController.current?.abort();const controller=new AbortController();detailController.current=controller;setDetailLoading(true);
  try{let value=await cvApi.get(id,token,controller.signal);if(lifetime.current.signal.aborted||seq!==detailSequence.current||viewedCv.current!==id)return;setDetail(value);setDetailError('');
   try{const clarification=await cvApi.questions(id,token,controller.signal);
    if(clarification.cv_version!==value.version)value=await cvApi.get(id,token,controller.signal);
    if(lifetime.current.signal.aborted||seq!==detailSequence.current||viewedCv.current!==id)return;
    if(clarification.cv_version!==value.version)throw new Error('This CV changed while its questions were loading. Refresh saved status to try again.');
    setDetail(value);setQuestions(clarification);
   }catch{if(!lifetime.current.signal.aborted&&seq===detailSequence.current&&viewedCv.current===id)setQuestions(null);}
  }catch(cause){if(!lifetime.current.signal.aborted&&!controller.signal.aborted&&seq===detailSequence.current)setDetailError(cause instanceof Error?cause.message:'Could not load this CV.');}finally{if(!lifetime.current.signal.aborted&&seq===detailSequence.current)setDetailLoading(false);}
 },[token]);
 useEffect(()=>{if(lifetime.current.signal.aborted)lifetime.current=new AbortController();void getPolicy();void getList();void getDeclarations();return()=>{lifetime.current.abort();detailController.current?.abort();listSequence.current++;detailSequence.current++;};},[getPolicy,getList,getDeclarations]);
 useEffect(()=>{
  const dirty=()=>Boolean(document.querySelector('.cv-workspace [data-unsaved="true"]'));
  function unload(event:BeforeUnloadEvent){if(dirty()){event.preventDefault();event.returnValue='';}}
  function leave(event:MouseEvent){const anchor=(event.target as Element|null)?.closest?.('a[href]');if(!dirty()||!anchor||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;const url=new URL(anchor.getAttribute('href')!,location.href);if(url.pathname===location.pathname&&url.origin===location.origin)return;if(!window.confirm('Leave this page and discard unsaved CV or capability drafts?')){event.preventDefault();event.stopImmediatePropagation();}}
  window.addEventListener('beforeunload',unload);document.addEventListener('click',leave,true);return()=>{window.removeEventListener('beforeunload',unload);document.removeEventListener('click',leave,true);};
 },[]);
 useEffect(()=>{if(!viewId&&list?.selection.cv_id)setViewId(list.selection.cv_id);},[list,viewId]);
 useEffect(()=>{if(viewId)void getDetail(viewId);},[viewId,getDetail]);
 useEffect(()=>{if(!list?.cvs.some(cv=>processing(cv.status)))return;const timer=setInterval(()=>{void getList();if(viewId&&list.cvs.some(cv=>cv.id===viewId&&processing(cv.status)))void getDetail(viewId);},3000);return()=>clearInterval(timer);},[list,viewId,getList,getDetail]);
 const foregroundRefresh=useRef(false);
 useEffect(()=>{
  async function revalidate(){
   if(document.visibilityState==='hidden'||foregroundRefresh.current||busy||preparing||document.querySelector('.cv-workspace [aria-busy="true"]'))return;
   foregroundRefresh.current=true;
   try{await Promise.allSettled([getList(),getDeclarations(),...(viewedCv.current?[getDetail(viewedCv.current)]:[])]);}
   finally{foregroundRefresh.current=false;}
  }
  window.addEventListener('focus',revalidate);window.addEventListener('online',revalidate);document.addEventListener('visibilitychange',revalidate);
  return()=>{window.removeEventListener('focus',revalidate);window.removeEventListener('online',revalidate);document.removeEventListener('visibilitychange',revalidate);};
 },[busy,preparing,getList,getDeclarations,getDetail]);
 async function refresh(){await Promise.allSettled([getList(),getDeclarations(),...(viewId?[getDetail(viewId)]:[])]);}
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
  }catch(cause){if(!lifetime.current.signal.aborted&&viewedCv.current===id&&seq===detailSequence.current){setPrepareError(cause instanceof Error?cause.message:'Could not prepare relevant questions.');if(cause instanceof CvApiError&&cause.status===409)await getDetail(id);}}
  finally{if(!lifetime.current.signal.aborted)setPreparing(current=>current===id?null:current);}
 }
 async function upload(event:FormEvent){
  event.preventDefault();if(busy||!file||!policy)return;setError('');setNotice('');
  const extension=file.name.split('.').pop()?.toLowerCase();if(!file.size||file.size>policy.max_file_bytes||!policy.formats.includes(extension as 'pdf'|'docx')){setError(`Choose a non-empty ${policy.formats.map(f=>f.toUpperCase()).join(' or ')} file up to ${policy.max_file_bytes/(1024*1024)} MiB.`);return;}
  if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Upload this CV and discard unsaved CV or capability drafts?'))return;
  const form=new FormData();form.set('file',file);form.set('mutation_id',uploadKey.current);if(reuploadTarget){form.set('cv_id',reuploadTarget.id);form.set('expected_version',String(reuploadTarget.version));}setBusy('upload');pendingUpload.current=true;
  try{const value=await cvApi.upload(form,token,lifetime.current.signal);if(lifetime.current.signal.aborted)return;setViewId(value.id);setDetail(value);setFile(null);setReuploadTarget(null);if(fileInput.current)fileInput.current.value='';uploadKey.current=crypto.randomUUID();pendingUpload.current=false;setNotice('Upload saved. Review its processing status below. Select a ready CV explicitly when you want to use it for analysis.');await getList();}
  catch(cause){if(!lifetime.current.signal.aborted)setError(`${cause instanceof Error?cause.message:'The upload response was interrupted.'} Check saved status before retrying this file. Retry keeps the same request identity.`);}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 async function select(id:string){
  if(!list||busy)return;const body={cv_id:id,expected_version:list.selection.version};setBusy(`select:${id}`);setError('');setNotice('');
  try{const value=await cvApi.select({...body,mutation_id:getKey(body)},token,lifetime.current.signal);if(lifetime.current.signal.aborted)return;selectionRef.current=value.cv_id;setList(p=>p?{...p,selection:value}:p);setNotice('CV selected for future analysis. Your existing results have not been regenerated.');await getList();}
  catch(cause){if(!lifetime.current.signal.aborted){setError(cause instanceof Error?cause.message:'Could not select this CV.');if(cause instanceof CvApiError&&cause.status===409)await getList();}}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 async function retry(){
  if(!detail||busy)return;const body={expected_version:detail.version};setBusy('retry');setError('');
  try{const value=await cvApi.retry(detail.operation_id,{...body,mutation_id:getKey({id:detail.operation_id,...body})},token,lifetime.current.signal);if(!lifetime.current.signal.aborted){saved(value);await getList();}}
  catch(cause){if(!lifetime.current.signal.aborted)setError(cause instanceof Error?cause.message:'Could not retry this CV.');}
  finally{if(!lifetime.current.signal.aborted)setBusy('');}
 }
 function review(id:string){if(busy)return;if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Leave this CV and discard its unsaved draft?'))return;viewedCv.current=id;detailSequence.current++;detailController.current?.abort();setViewId(id);setDetail(null);setQuestions(null);setDetailError('');setPrepareError('');setPreparing(null);}
 function reupload(value:CvDetail){setFilesOpen(true);if(document.querySelector('.cv-workspace [data-unsaved="true"]')&&!window.confirm('Reprocess this source and discard its unsaved draft?'))return;setReuploadTarget(value);setFile(null);if(fileInput.current){fileInput.current.value='';fileInput.current.focus();}uploadKey.current=crypto.randomUUID();setError('');}
 return <section className="page on cv-workspace"><PageTitle title="Resume & Tracker"><button type="button" className="btn ghost" onClick={()=>void refresh()} disabled={Boolean(busy)}>Refresh saved status</button></PageTitle>
  <details className="cv-files-disclosure" open={filesOpen || Boolean(list && !list.cvs.length)} onToggle={event=>setFilesOpen(event.currentTarget.open)}><summary><span>CV files</span><span className="small">{list?.selection.cv_id ? list.cvs.find(cv=>cv.id===list.selection.cv_id)?.file_name : 'Upload or choose a saved CV'}</span></summary>
  <div className="cv-top-grid"><section className="card pad"><h2>Upload a CV</h2>{policy?<><form className="cv-form" onSubmit={upload}>{reuploadTarget&&<div className="cv-warning"><p>Re-uploading the exact source for {reuploadTarget.file_name} · CV {reuploadTarget.id}. Its saved corrections and removals will be preserved. A changed document needs a separate upload.</p><button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={()=>{setReuploadTarget(null);uploadKey.current=crypto.randomUUID();}}>Cancel source re-upload</button></div>}<label htmlFor="cv-document">CV document<input ref={fileInput} id="cv-document" type="file" accept={policy.formats.map(f=>`.${f}`).join(',')} disabled={Boolean(busy)} onChange={e=>{setFile(e.target.files?.[0]??null);uploadKey.current=crypto.randomUUID();pendingUpload.current=false;setError('');}}/></label><p className="small">Text-based {policy.formats.map(f=>f.toUpperCase()).join(' or ')} · Up to {policy.max_file_bytes/(1024*1024)} MiB. Scanned PDFs need a text-based alternative. Files are private and retained temporarily for processing and retry.</p>{!policy.extraction_configured&&<p className="cv-warning">CV extraction is not configured on this server. Your existing saved CVs and manual capabilities remain available. New files cannot be processed until it is configured.</p>}<button className="btn pri" disabled={!file||Boolean(busy)||!policy.extraction_configured}><Icon name="up"/>{busy==='upload'?'Uploading…':pendingUpload.current?'Retry upload':reuploadTarget?'Re-upload same source':'Upload CV'}</button></form></>:<p className="small">{policyError||'Loading supported formats and upload limit…'}</p>}{policyError&&<button className="btn ghost sm" onClick={()=>void getPolicy()}>Retry upload settings</button>}</section>
  <aside className="card pad cv-selected" aria-label="Selected CV"><h2>Selected for analysis</h2>{list?.selection.cv_id?<><strong>{list.cvs.find(c=>c.id===list.selection.cv_id)?.file_name??'Selected CV'}</strong><p className="small">CV {list.selection.cv_id}</p>{selectedCv&&<p className="small">Extraction {selectedCv.extraction_version} · Effective version {selectedCv.effective_version} · {selectedCv.status==='ready'?'Ready for source selection':'Currently unavailable for analysis'}</p>}</>:<p className="small">{list?'No CV selected. Uploading a file does not select it. Choose a ready CV below.':'Saved selection has not loaded yet. Refresh saved status to restore it.'}</p>}<p className="small">Manual capabilities are included separately. A confirmed career target is still needed for relevant clarification and analysis.</p><Link className="text-link" href="/career-goal">Open Career Goal</Link><p className="small">Target confirmation and gap analysis are not available in this screen.</p></aside></div>
  {busy==='upload'&&<p role="status" className="cv-notice">Uploading the file. Once accepted, processing status is saved and can be checked after returning.</p>}{error&&<div role="alert" className="cv-error">{error}</div>}{notice&&<p role="status" className="cv-notice">{notice}</p>}
  <section className="card pad cv-saved" aria-label="Saved CVs"><div className="row between"><h2>Saved CVs</h2><span className="small">{list?.cvs.length??0} saved</span></div>{loading&&<p role="status">Loading saved CVs…</p>}{listError&&<div role="alert" className="cv-error"><p>{listError}</p><button className="btn ghost sm" onClick={()=>void getList()}>Retry saved CVs</button></div>}{list&&!list.cvs.length&&<EmptyState icon="doc" title="No saved CV yet">Upload a readable CV, or add a capability below without one.</EmptyState>}
   <div className="cv-list">{list?.cvs.map(cv=><article key={cv.id} aria-label={`CV ${cv.id}`} className={list.selection.cv_id===cv.id?'selected':''}><div className="row between"><h3>{cv.file_name}</h3><span className="pill n">{cv.status==='ready'?'Ready':cv.status==='failed'?'Failed':'Processing'}</span></div><p className="small">CV {cv.id}</p><p className="small">Uploaded {date(cv.created_at)} · Updated {date(cv.updated_at)}</p><p className="small">Extraction {cv.extraction_version} · Effective version {cv.effective_version}</p>{list.selection.cv_id===cv.id&&<p className="cv-selection-label">Selected for analysis</p>}{cv.error&&<p className="small">{cv.error.message}</p>}<div className="row cv-actions"><button className="btn ghost sm" disabled={Boolean(busy)} onClick={()=>review(cv.id)}>Review CV</button><button className="btn pri sm" disabled={Boolean(busy)||cv.status!=='ready'||list.selection.cv_id===cv.id} onClick={()=>void select(cv.id)}>{list.selection.cv_id===cv.id?'Selected':'Select for analysis'}</button></div>{cv.status!=='ready'&&<p className="small">This file cannot be selected until a usable extraction is saved.</p>}</article>)}</div>
  </section>
  </details>
  {detail && detail.id!==list?.selection.cv_id && <p className="cv-viewing-notice">Reviewing <strong>{detail.file_name}</strong>. {list?.selection.cv_id?'Your selected CV stays unchanged until you choose a different one in CV files.':'Choose this ready CV in CV files when you want to use it for analysis.'}</p>}
  {!loading && (viewId || !list?.selection.cv_id) && <CvConversationPanel key={viewId??'manual'} cvId={viewId} detail={detail?.id===viewId?detail:null} token={token} unavailable={Boolean(busy)} onChanged={refresh} onOpenSummary={()=>{setSummaryOpen(true);requestAnimationFrame(()=>{summaryPanel.current?.scrollIntoView?.({behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});summaryPanel.current?.querySelector('summary')?.focus();});}}/>}
  <details ref={summaryPanel} className="cv-summary-disclosure" open={summaryOpen} onToggle={event=>setSummaryOpen(event.currentTarget.open)}><summary><span>Your CV summary</span><span className="small">Saved details, sources and manual capabilities</span></summary>
  {viewId&&<section className="card pad cv-review" aria-label="CV review">{detailLoading&&!detail&&<p role="status">Loading this CV…</p>}{detailError&&<div role="alert" className="cv-error"><p>{detailError}</p><button className="btn ghost sm" onClick={()=>void getDetail(viewId)}>Retry this CV</button></div>}{detail&&detail.id===viewId&&<>{detail.id!==list?.selection.cv_id&&<p className="cv-warning">Viewing {detail.file_name} (CV {detail.id}). This is not your selected analysis source.</p>}{processing(detail.status)?<div role="status"><h2>Processing {detail.file_name}</h2><p className="small">Your upload is saved. You can leave and return to check progress. If the connection is interrupted, use Refresh saved status; your previous selected CV remains identified above.</p></div>:detail.status==='failed'?<><h2>Processing failed: {detail.file_name}</h2><p className="cv-error">{detail.error?.message??'This CV could not be processed.'}</p>{detail.source_available&&detail.error?.retryable?<button className="btn pri sm" disabled={Boolean(busy)} onClick={()=>void retry()}>Retry processing</button>:<><p className="small">Re-upload the exact source file to retry while retaining this CV’s corrections. A changed document should be uploaded as a new CV.</p><button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={()=>reupload(detail)}>Re-upload this source</button></>}</>:<button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={()=>reupload(detail)}>Re-upload this source</button>}
   {detail.notices?.map((text,index)=><p className="cv-warning" key={index}>{text}</p>)}
   {detail.reconciliation?.map(entry=><p className="cv-warning" key={entry.item_id}>Saved item {entry.item_id}: {entry.reason}</p>)}
   {detail.extraction_version>0&&(policy?<><CvReview key={detail.id} detail={detail} policy={policy} questions={questions} token={token} signal={lifetime.current.signal} onSaved={saved} refresh={refresh} onPrepare={prepareQuestions} preparing={preparing===detail.id} prepareError={prepareError} refreshing={detailLoading}/></>:<p className="small">Load the upload settings to review and edit this CV safely.</p>)}
   <SourceReconciliation key={detail.id} detail={detail} list={list} token={token} signal={lifetime.current.signal} onSaved={saved} refresh={refresh}/>
  </>}</section>}
  {declarations?<CapabilityDeclarations data={declarations} selectedCv={selectedCv} token={token} signal={lifetime.current.signal} onSaved={setDeclarations} refresh={refresh}/>:<section className="card pad cv-declarations"><h2>Add what your CV leaves out</h2><p className="small">{declarationError||'Loading your manual capabilities…'}</p>{declarationError&&<button className="btn ghost sm" onClick={()=>void getDeclarations()}>Retry manual capabilities</button>}</section>}
 </details>
 </section>;
}

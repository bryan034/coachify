"use client";
import { useEffect, useRef, useState } from 'react';
import { cvApi, CvApiError } from '@/lib/api/cv';
import type { CvDetail, CvList, Reconciliation, ReconciliationInput } from './types';
import { EvidenceList } from './cv-review';

export function SourceReconciliation({detail,list,token,signal,onSaved,refresh}:{detail:CvDetail;list:CvList|null;token:string;signal:AbortSignal;onSaved:(value:CvDetail)=>void|Promise<void>;refresh:()=>Promise<void>}) {
 const [candidate,setCandidate]=useState<Reconciliation|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false),[choices,setChoices]=useState<Record<string,string>>({}),[source,setSource]=useState(''),[sourceVersion,setSourceVersion]=useState<number|null>(null),[base,setBase]=useState<{version:number;candidateId:string}|null>(null),[compareVersion,setCompareVersion]=useState(detail.version);
 const choicesRef=useRef(choices);choicesRef.current=choices;
 const receipt=useRef<{body:string;id:string}|null>(null);
 const key=(body:unknown)=>{const signature=JSON.stringify(body);if(receipt.current?.body!==signature)receipt.current={body:signature,id:crypto.randomUUID()};return receipt.current.id;};
 const candidateId=detail.reconciliation_candidate_id;
 useEffect(()=>{
  const controller=new AbortController();setError('');
  if(!candidateId){setCandidate(null);setBase(null);setChoices({});return()=>controller.abort();}
  setLoading(true);
  void (async()=>{try{const value=await cvApi.reconciliation(detail.id,token,AbortSignal.any([signal,controller.signal]));if(signal.aborted||controller.signal.aborted)return;setCandidate(value);if(!Object.keys(choicesRef.current).length)setBase(value?{version:value.cv_version,candidateId:value.candidate_id}:null);}catch(cause){if(!signal.aborted&&!controller.signal.aborted)setError(cause instanceof Error?cause.message:'Could not load the changed evidence.');}finally{if(!signal.aborted&&!controller.signal.aborted)setLoading(false);}})();
  return()=>controller.abort();
 },[detail.id,detail.version,candidateId,token,signal]);
 const stale=Boolean(candidate&&base&&(base.version!==detail.version||base.version!==candidate.cv_version||base.candidateId!==candidate.candidate_id));
 const complete=Boolean(candidate&&candidate.affected_item_ids.every(id=>Object.hasOwn(choices,id)&&choices[id]!==''));
 const readySources=list?.cvs.filter(cv=>cv.id!==detail.id&&cv.status==='ready')??[];
 const compareStale=Boolean(source&&(compareVersion!==detail.version||readySources.find(cv=>cv.id===source)?.version!==sourceVersion));
 async function resolve(action:ReconciliationInput['action']){
  if(busy||loading||!candidate||!base||stale||(action==='accept_candidate'&&!complete))return;
  const decisions=action==='keep_previous'?[]:candidate.affected_item_ids.map(item_id=>({item_id,target_item_id:choices[item_id]==='archive'?null:choices[item_id]}));
  const targets=decisions.flatMap(choice=>choice.target_item_id?[choice.target_item_id]:[]);
  if(new Set(targets).size!==targets.length){setError('Choose a different new source for each saved item, or keep that statement in history.');return;}
  const body={expected_version:base.version,candidate_id:candidate.candidate_id,action,choices:decisions};setBusy(true);setError('');
  try{const value=await cvApi.resolveReconciliation(detail.id,{...body,mutation_id:key(body)},token,signal);if(!signal.aborted){setChoices({});await onSaved(value);}}
  catch(cause){if(!signal.aborted){setError(cause instanceof Error?cause.message:'Could not apply the reconciliation choice.');if(cause instanceof CvApiError&&cause.status===409)await refresh();}}
  finally{if(!signal.aborted)setBusy(false);}
 }
 async function compare(){
  if(busy||!source||sourceVersion===null||compareStale)return;
  const body={expected_version:compareVersion,source_cv_id:source,source_version:sourceVersion};setBusy(true);setError('');
  try{const value=await cvApi.compareReconciliation(detail.id,{...body,mutation_id:key(body)},token,signal);if(!signal.aborted){setSource('');setSourceVersion(null);await onSaved(value);}}
  catch(cause){if(!signal.aborted){setError(cause instanceof Error?cause.message:'Could not compare the saved sources.');if(cause instanceof CvApiError&&cause.status===409)await refresh();}}
  finally{if(!signal.aborted)setBusy(false);}
 }
 if(!candidateId&&detail.status!=='ready')return null;
 return <section className="cv-section cv-source-reconciliation" aria-label="Source reconciliation">
  <h3>{candidateId?'Review changed source evidence':'Compare a replacement CV'}</h3>
  {loading&&<p role="status">Loading the previous statements and new evidence…</p>}
  {list?.next_cursor&&<p className="small">To find an older source, open CV files and choose Show more saved CVs.</p>}
  {candidate?<div data-unsaved={Object.keys(choices).length>0} aria-busy={busy}>
   <p className="small">The saved result remains available until you choose. Review the actual evidence; matching names do not transfer an explanation automatically.</p>
   {candidate.notices.map((notice,index)=><p key={index} className="small">{notice}</p>)}
   <details><summary>Inspect the new extraction ({candidate.candidate_items.length} items)</summary>{candidate.candidate_items.map(item=><article key={item.id} className="cv-item"><h4>{item.title}</h4><p className="small">{item.kind} · {item.id}</p><p className="cv-copy">{item.description}</p><EvidenceList item={item}/></article>)}</details>
   {candidate.affected_item_ids.map(id=>{const previous=candidate.previous_items.find(item=>item.id===id),selected=candidate.candidate_items.find(item=>item.id===choices[id]);return <article className="cv-item" key={id}><h4>{previous?.title??'Previous source item'}</h4><p className="small">Previous item {id}</p>{previous&&<><p className="cv-copy">{previous.description}</p>{previous.removed&&<p className="cv-warning">This item was removed from the previous effective evidence.</p>}<EvidenceList item={previous}/></>}{candidate.previous_answers.filter(answer=>answer.item_id===id&&answer.answer).map(answer=><blockquote key={answer.id}><p>{answer.answer}</p><cite>Your saved explanation</cite></blockquote>)}<label>How should this saved statement carry forward?<select aria-label={`Reconcile ${previous?.title??id}`} value={choices[id]??''} disabled={busy||stale} onChange={event=>setChoices(current=>({...current,[id]:event.target.value}))}><option value="">Choose after comparing the sources</option><option value="archive">Keep in history without applying to the new evidence</option>{candidate.candidate_items.filter(item=>item.kind===previous?.kind).map(item=><option value={item.id} key={item.id}>Apply to {item.title} · {item.id}</option>)}</select></label>{selected&&<div><p className="small">Chosen new source</p><p className="cv-copy">{selected.description}</p><EvidenceList item={selected}/></div>}</article>;})}
   {!candidate.affected_item_ids.length&&<p className="small">There are no affected saved statements that need reassignment. Review the new extraction before accepting it.</p>}
   {stale&&<div className="cv-warning"><p>The saved source or comparison changed. Your choices are retained but cannot be applied until you review the latest comparison.</p><button type="button" className="btn ghost sm" onClick={()=>{setChoices({});setBase({version:candidate.cv_version,candidateId:candidate.candidate_id});setError('');}}>Review latest comparison choices</button></div>}
   <div className="row cv-actions"><button type="button" className="btn pri sm" disabled={busy||loading||stale||!complete} onClick={()=>void resolve('accept_candidate')}>Accept reviewed extraction</button><button type="button" className="btn ghost sm" disabled={busy||loading||stale} onClick={()=>void resolve('keep_previous')}>{candidate.source_cv_id===detail.id?'Keep previous extraction':'Keep this CV unchanged'}</button></div><p className="small">Reapplied explanations keep their original history and must be interpreted against the new evidence. This does not select a different CV for analysis.</p>
  </div>:!candidateId?<form className="cv-form" data-unsaved={Boolean(source)} aria-busy={busy} onSubmit={event=>{event.preventDefault();void compare();}}>
   <p className="small">If this is a replacement for an earlier saved CV, explicitly compare their evidence before carrying statements forward. Each CV keeps its own history.</p><label>Previous saved CV<select value={source} disabled={busy} onChange={event=>{setSource(event.target.value);setSourceVersion(readySources.find(cv=>cv.id===event.target.value)?.version??null);setCompareVersion(detail.version);}}><option value="">Choose a ready saved CV</option>{readySources.map(cv=><option key={cv.id} value={cv.id}>{cv.file_name} · {cv.id}</option>)}</select></label>{compareStale&&<p className="cv-warning">A saved CV changed. Select the previous source again after reviewing its latest version.</p>}<button className="btn ghost sm" disabled={busy||!source||compareStale}>Compare saved evidence</button>
  </form>:!loading&&!error?<p className="small">This comparison is no longer available. Refresh saved status.</p>:null}
  {error&&<p role="alert" className="cv-error">{error} Your existing extraction and statements are retained.</p>}
 </section>;
}

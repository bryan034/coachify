"use client";
import { useEffect, useRef, useState } from 'react';
import { cvApi, CvApiError } from '@/lib/api/cv';
import type { CvDetail, DeclarationInput, DeclarationLinks, Declarations } from './types';
import { DeclarationAttachment } from './declaration-attachment';
const normalized=(value:string)=>value.normalize('NFKC').trim().replace(/\s+/g,' ').toLowerCase();
export function CapabilityDeclarations({data,selectedCv,token,signal,onSaved,refresh}:{data:Declarations;selectedCv:CvDetail|null;token:string;signal:AbortSignal;onSaved:(v:Declarations)=>void;refresh:()=>Promise<void>}) {
 const [name,setName]=useState(''),[description,setDescription]=useState(''),[choice,setChoice]=useState(''),[sourceVersion,setSourceVersion]=useState<{id:string;version:number}|null>(null),[version,setVersion]=useState(data.version),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[conflict,setConflict]=useState(false);
 const receipt=useRef<{body:string;id:string}|null>(null);
 const [links,setLinks]=useState<DeclarationLinks|null>(null),[linkError,setLinkError]=useState('');
 const hasLinks=data.declarations.some(declaration=>declaration.attached_to);
 useEffect(()=>{
  const controller=new AbortController();setLinks(null);setLinkError('');
  if(hasLinks)void (async()=>{try{const value=await cvApi.declarationLinks(token,AbortSignal.any([signal,controller.signal]));if(!controller.signal.aborted&&!signal.aborted)setLinks(value);}catch{if(!controller.signal.aborted&&!signal.aborted)setLinkError('Refresh saved status to retry checking CV links.');}})();
  return()=>controller.abort();
 },[hasLinks,data.version,selectedCv?.id,selectedCv?.version,token,signal]);
 const manualMatches=data.declarations.filter(d=>normalized(d.name)===normalized(name));
 const matchingIds=new Set(selectedCv?.skills.filter(skill=>normalized(skill.name)===normalized(name)).flatMap(skill=>skill.item_ids)??[]);
 const cvMatches=selectedCv?.items.filter(item=>!item.removed&&matchingIds.has(item.id))??[];
 const matches=manualMatches.length+cvMatches.length>0;
 const maxName=data.limits?.name??120,maxDescription=data.limits?.description??2000;
 const dirty=Boolean(name||description),stale=dirty&&(version!==data.version||Boolean(sourceVersion&&(sourceVersion.id!==selectedCv?.id||sourceVersion.version!==selectedCv?.version)));
 const invalid=!name.trim()||!description.trim()||Array.from(name).length>maxName||Array.from(description).length>maxDescription;
 async function save(){
  if(busy||invalid||stale||conflict||(matches&&!choice))return;
  const body:Omit<DeclarationInput,'mutation_id'>={expected_version:version,name,description,mode:!matches?'new':choice==='distinct'?'distinct':'attach'};
  if(choice.startsWith('manual:'))body.attach_to_id=choice.slice(7);
  if(choice.startsWith('cv:')&&selectedCv)body.cv_match={cv_id:selectedCv.id,item_id:choice.slice(3),cv_version:selectedCv.version};
  if(choice==='distinct'&&cvMatches.length&&selectedCv)body.cv_match={cv_id:selectedCv.id,item_id:cvMatches[0].id,cv_version:selectedCv.version};
  const serialized=JSON.stringify(body);if(receipt.current?.body!==serialized)receipt.current={body:serialized,id:crypto.randomUUID()};
  setBusy(true);setError('');setNotice('');
  try{const value=await cvApi.addDeclaration({...body,mutation_id:receipt.current!.id},token,signal);if(!signal.aborted){onSaved(value);setVersion(value.version);setName('');setDescription('');setChoice('');setSourceVersion(null);setNotice('Capability saved. It stays with your account across CV changes.');}}
  catch(cause){if(!signal.aborted){setError(cause instanceof Error?cause.message:'Could not save this capability.');if(cause instanceof CvApiError&&cause.status===409){setConflict(true);await refresh();}}}
  finally{if(!signal.aborted)setBusy(false);}
 }
 return <section className="card pad cv-declarations" aria-label="Manual capabilities"><h2>Add what your CV leaves out</h2><p className="small">Describe a capability in your own words. A CV or proof is not required. Your declaration stays with your account when you change CVs.</p>
  <form className="cv-form" data-unsaved={dirty} aria-busy={busy} onSubmit={e=>{e.preventDefault();void save();}}>
   <label>Capability name<input value={name} onChange={e=>{if(!dirty)setVersion(data.version);setName(e.target.value);setChoice('');setSourceVersion(null);setNotice('');}} disabled={busy} maxLength={maxName} required/></label>
   <label>Capability description<textarea aria-label="Capability description" rows={4} value={description} onChange={e=>{if(!dirty)setVersion(data.version);setDescription(e.target.value);setNotice('');}} disabled={busy} aria-invalid={Array.from(description).length>maxDescription} required/><span className="small">{Array.from(description).length} / {maxDescription} characters. Include what you have done; unknown proficiency or experience stays unknown.</span></label>
   {matches&&<fieldset className="cv-match"><legend>Similar capability already recorded</legend><p className="small">Choose whether this adds context to existing evidence or describes a distinct claim. Repeated statements are not independent proof.</p>{manualMatches.map(match=><label key={match.id}><input type="radio" name="capability-match" value={`manual:${match.id}`} checked={choice===`manual:${match.id}`} onChange={e=>{setChoice(e.target.value);setSourceVersion(selectedCv?{id:selectedCv.id,version:selectedCv.version}:null);}}/><span>Add to your declaration: <strong>{match.name}</strong><span className="cv-copy">{match.description}</span></span></label>)}{cvMatches.map(match=><label key={match.id}><input type="radio" name="capability-match" value={`cv:${match.id}`} checked={choice===`cv:${match.id}`} onChange={e=>{setChoice(e.target.value);setSourceVersion(selectedCv?{id:selectedCv.id,version:selectedCv.version}:null);}}/><span>Attach to CV evidence: <strong>{match.title}</strong><span className="cv-copy">{selectedCv?.file_name} · Source {match.id} · {match.description}</span>{match.evidence.map((e,index)=><span className="cv-copy" key={`${e.id}:${index}`}>{e.excerpt} · {e.location}</span>)}</span></label>)}<label><input type="radio" name="capability-match" value="distinct" checked={choice==='distinct'} onChange={e=>{setChoice(e.target.value);setSourceVersion(selectedCv?{id:selectedCv.id,version:selectedCv.version}:null);}}/><span>Keep as a distinct claim</span></label></fieldset>}
   {(stale||conflict)&&<div className="cv-warning"><p>Saved capabilities or matching evidence changed. Your draft is retained. Review the current evidence and choose how to save it.</p><button type="button" className="btn ghost sm" onClick={()=>{setVersion(data.version);setConflict(false);setChoice('');setSourceVersion(null);setError('');}}>Keep capability draft against refreshed version</button></div>}
   {error&&<p role="alert" className="cv-error">{error} Your draft is still here.</p>}{notice&&<p role="status" className="cv-notice">{notice}</p>}
   <div className="row cv-actions"><button className="btn pri sm" disabled={busy||invalid||stale||conflict||(matches&&!choice)}>{busy?'Saving capability…':'Add capability'}</button><button type="button" className="btn ghost sm" disabled={busy||!dirty} onClick={()=>{setName('');setDescription('');setChoice('');setSourceVersion(null);setVersion(data.version);setError('');setConflict(false);}}>Cancel addition</button></div>
  </form>
  <div className="cv-manual-list"><h3>Your manual capabilities</h3>{!data.declarations.length&&<p className="small">No manual capabilities saved yet.</p>}{data.declarations.map(d=><article key={d.id}><div className="row between"><h4>{d.name}</h4><span className="pill n">Your declaration</span></div><p className="cv-copy">{d.description}</p>{d.contributions?.filter(c=>c.description!==d.description).map(c=><p className="cv-copy" key={c.id}>{c.description}</p>)}<DeclarationAttachment declaration={d} link={links?.declarations_version===data.version?links.links.find(link=>link.declaration_id===d.id):undefined} linkError={linkError} data={data} selectedCv={selectedCv} token={token} signal={signal} onSaved={onSaved} refresh={refresh}/><p className="small">Proficiency and experience: unknown unless described above.</p></article>)}</div>
 </section>;
}

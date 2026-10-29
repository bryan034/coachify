"use client";
import { useRef, useState } from 'react';
import { cvApi, CvApiError } from '@/lib/api/cv';
import type { CvDetail, Declaration, DeclarationLink, Declarations } from './types';

export function DeclarationAttachment({declaration,link,linkError,data,selectedCv,token,signal,onSaved,refresh}:{declaration:Declaration;link?:DeclarationLink;linkError:string;data:Declarations;selectedCv:CvDetail|null;token:string;signal:AbortSignal;onSaved:(value:Declarations)=>void;refresh:()=>Promise<void>}) {
 const [editing,setEditing]=useState(false),[choice,setChoice]=useState(''),[version,setVersion]=useState(data.version),[sourceVersion,setSourceVersion]=useState<number|null>(null),[sourceId,setSourceId]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const receipt=useRef<{body:string;id:string}|null>(null);
 const normalize=(text:string)=>text.normalize('NFKC').trim().replace(/\s+/g,' ').toLowerCase();
 const matchingIds=new Set(selectedCv?.skills.filter(skill=>normalize(skill.name)===normalize(declaration.name)).flatMap(skill=>skill.item_ids)??[]);
 const sources=selectedCv?.status==='ready'?selectedCv.items.filter(item=>!item.removed&&matchingIds.has(item.id)):[];
 const stale=editing&&(version!==data.version||(choice!==''&&choice!=='standalone'&&(sourceId!==selectedCv?.id||sourceVersion!==selectedCv?.version)));
 const status=!declaration.attached_to?'standalone':link?.status??'unavailable';
 const label={standalone:'Standalone declaration; no CV evidence link.',current:'Linked evidence is current.',changed:'Linked evidence changed. Review how this declaration relates to it.',removed:'The linked source no longer supports this skill. Your declaration is retained.',unavailable:'The linked evidence could not be checked. Your declaration is retained.',unverified:'This older link needs an explicit review before it can be treated as current.'}[status];
 async function save(){
  if(busy||stale||!choice)return;
  if(choice!=='standalone'&&(!selectedCv||!sources.some(source=>source.id===choice)))return;
  const body={expected_version:version,declaration_id:declaration.id,cv_match:choice==='standalone'?null:{cv_id:selectedCv!.id,item_id:choice,cv_version:selectedCv!.version}};
  const signature=JSON.stringify(body);if(receipt.current?.body!==signature)receipt.current={body:signature,id:crypto.randomUUID()};
  setBusy(true);setError('');
  try{const value=await cvApi.updateAttachment({...body,mutation_id:receipt.current.id},token,signal);if(!signal.aborted){onSaved(value);setEditing(false);setChoice('');}}
  catch(cause){if(!signal.aborted){setError(cause instanceof Error?cause.message:'Could not save the link choice.');if(cause instanceof CvApiError&&cause.status===409)await refresh();}}
  finally{if(!signal.aborted)setBusy(false);}
 }
 return <div className="cv-attachment"><p className={status==='current'||status==='standalone'?'small':'cv-warning'}>{label}</p>{declaration.attached_to&&<p className="small">Saved source: {declaration.attached_to.cv_id} · {declaration.attached_to.item_id}{link&&!link.selected?' · This is a different CV from your selected analysis source.':''}</p>}{declaration.attached_to&&linkError&&<p className="small">{linkError}</p>}
  {editing?<form className="cv-form" data-unsaved={Boolean(choice)} aria-busy={busy} onSubmit={event=>{event.preventDefault();void save();}} aria-label={`Review link for ${declaration.name}`}>
   <label>How should this declaration be linked?<select value={choice} disabled={busy} onChange={event=>{setChoice(event.target.value);setSourceId(selectedCv?.id??null);setSourceVersion(selectedCv?.version??null);}}><option value="">Choose after reviewing the evidence</option><option value="standalone">Keep as a standalone declaration</option>{sources.map(source=><option key={source.id} value={source.id}>Link to {source.title} · {source.id}</option>)}</select></label>
   {choice&&choice!=='standalone'&&sources.filter(source=>source.id===choice).map(source=><div key={source.id}><p className="cv-copy">{source.description}</p>{source.evidence.map((e,index)=><blockquote key={`${e.id}:${index}`}><p>{e.excerpt}</p><cite>{e.location}</cite></blockquote>)}</div>)}
   {stale&&<div className="cv-warning"><p>The saved declaration or selected evidence changed. Your choice has not been applied.</p><button type="button" className="btn ghost sm" onClick={()=>{setVersion(data.version);setChoice('');setSourceId(null);setSourceVersion(null);setError('');}}>Review latest link choices</button></div>}
   {error&&<p role="alert" className="cv-error">{error}</p>}<div className="row cv-actions"><button className="btn pri sm" disabled={busy||stale||!choice}>Save link choice</button><button type="button" className="btn ghost sm" disabled={busy} onClick={()=>{setEditing(false);setChoice('');setError('');}}>Cancel link review</button></div><p className="small">Changing a link preserves your declaration and its descriptions. It does not verify the claim.</p>
  </form>:<button type="button" className="btn ghost sm" onClick={()=>{setEditing(true);setVersion(data.version);setChoice('');setError('');}}>Review CV link</button>}
 </div>;
}

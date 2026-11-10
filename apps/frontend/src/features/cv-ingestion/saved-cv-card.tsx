"use client";
import {useEffect,useRef,useState} from 'react';
import {cvApi,CvApiError} from '@/lib/api/cv';
import type {CvDetail,CvSummary} from './types';

type Props={cv:CvSummary;active:boolean;busy:boolean;token:string;review:()=>void;results:()=>void;select:()=>void;remove:()=>void;saved:(cv:CvDetail)=>void;refresh:()=>Promise<void>};
export function SavedCvCard({cv,active,busy,token,review,results,select,remove,saved,refresh}:Props){
 const [editing,setEditing]=useState(false),[title,setTitle]=useState(''),[saving,setSaving]=useState(false),[error,setError]=useState('');
 const controller=useRef(new AbortController()),pending=useRef<{title:string;version:number;id:string}|null>(null);
 useEffect(()=>{if(controller.current.signal.aborted)controller.current=new AbortController();return()=>controller.current.abort();},[]);
 async function rename(event:React.FormEvent){
  event.preventDefault();const value=title.trim();if(!value||saving)return;
  if(pending.current?.title!==value)pending.current={title:value,version:cv.version,id:crypto.randomUUID()};
  const request=pending.current;setSaving(true);setError('');
  try{const result=await cvApi.rename(cv.id,{display_name:request.title,expected_version:request.version,mutation_id:request.id},token,controller.current.signal);if(controller.current.signal.aborted)return;saved(result);pending.current=null;setEditing(false);}
  catch(cause){if(controller.current.signal.aborted)return;setError(cause instanceof Error?cause.message:'Could not rename this CV. Try again.');if(cause instanceof CvApiError&&cause.status===409){pending.current=null;await refresh();}}
  finally{if(!controller.current.signal.aborted)setSaving(false);}
 }
 const name=cv.display_name??cv.file_name;
 return <article aria-label={`CV ${cv.id}`} className={active?'selected':''}>
  <div className="row between"><h3>{name}</h3><span className="pill n">{cv.status==='ready'?'Ready':cv.status==='failed'?'Failed':'Processing'}</span></div>
  {active&&<p className="cv-selection-label">Active baseline</p>}
  {editing?<form className="cv-rename-form" onSubmit={rename}><label>CV title<input autoFocus maxLength={200} required value={title} disabled={saving} onChange={event=>setTitle(event.target.value)}/></label><div className="row"><button className="btn pri sm" disabled={saving||!title.trim()}>{saving?'Saving…':'Save title'}</button><button type="button" className="btn ghost sm" disabled={saving} onClick={()=>{setEditing(false);setError('');pending.current=null;}}>Cancel</button></div></form>:<button type="button" className="text-link cv-rename" disabled={busy} onClick={()=>{setTitle(name);setEditing(true);setError('');}}>Rename</button>}
  {error&&<p role="alert" className="cv-error">{error}</p>}
  <p className="small">Uploaded {new Date(cv.created_at).toLocaleDateString(undefined,{dateStyle:'medium'})}</p>
  <details className="cv-card-details"><summary>File details</summary><p className="small">{cv.file_name}</p><p className="small">CV {cv.id}</p><p className="small">Updated {new Date(cv.updated_at).toLocaleString()} · Extraction {cv.extraction_version} · Effective version {cv.effective_version}</p></details>
  {cv.error&&<p className="small">{cv.error.message}</p>}
  <div className="row cv-actions"><button type="button" className="btn pri sm" disabled={busy||saving} onClick={review}>{cv.status==='ready'?'Review CV':'View processing status'}</button>{cv.status==='ready'&&<button type="button" className="btn ghost sm" disabled={busy||saving} onClick={results}>View extracted results</button>}<button type="button" className="btn ghost sm" disabled={busy||saving||cv.status!=='ready'||active} onClick={select}>{active?'Active baseline':'Set as active baseline'}</button><button type="button" className="btn ghost sm" disabled={busy||saving} onClick={remove}>Delete CV</button></div>
  {cv.status!=='ready'&&<p className="small">Processing must finish before this CV can become your active baseline.</p>}
 </article>;
}

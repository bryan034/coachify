"use client";
import {useEffect,useRef,useState} from 'react';
import {roadmapApi} from '@/lib/api/roadmap';
type Proposal={id:string;name:string;description:string;proposal_hash:string};
type View={version:number;declarations_version:number;items:Proposal[]};
export function EvidenceProposals({token,version,onSaved}:{token:string;version:number;onSaved:()=>void}){
 const [view,setView]=useState<View>(),[error,setError]=useState(''),[busy,setBusy]=useState(false),[attempt,setAttempt]=useState(0);
 const [skipped,setSkipped]=useState<string[]>([]);
 const command=useRef<{key:string;body:object}|null>(null);
 useEffect(()=>{const abort=new AbortController();void roadmapApi<View>('/planner/evidence-proposals',token,undefined,abort.signal).then(value=>{if(!abort.signal.aborted)setView(value);}).catch(()=>{if(!abort.signal.aborted)setError('Session evidence suggestions could not be loaded.');});return()=>abort.abort();},[token,version,attempt]);
 async function confirm(item:Proposal){if(!view||busy)return;setBusy(true);setError('');command.current??={key:item.id,body:{expected_version:view.version,expected_declarations_version:view.declarations_version,proposal_hash:item.proposal_hash,mutation_id:crypto.randomUUID()}};try{await roadmapApi(`/planner/evidence-proposals/${command.current.key}/confirm`,token,command.current.body);command.current=null;setAttempt(value=>value+1);onSaved();}catch{setError('This suggestion could not be saved. Your note is retained; reload to review the latest sources.');}finally{setBusy(false);}}
 // One suggestion at a time; "Not now" hides it for this visit only, so nothing is lost.
 const item=view?.items?.find(entry=>!skipped.includes(entry.id));
 if(!item&&!error)return null;
 return <section className="evidence-banner" aria-labelledby="evidence-title">
  {item&&<><div><h2 id="evidence-title">Add this to your Skills Profile?</h2><p><strong>{item.name}</strong>: {item.description}</p><p className="small">From your own practice notes. Nothing is added until you confirm.</p></div>
   <div className="evidence-actions"><button type="button" className="btn ghost" disabled={busy} onClick={()=>setSkipped(current=>[...current,item.id])}>Not now</button><button type="button" className="btn pri" disabled={busy} onClick={()=>void confirm(item)}>{busy?'Adding…':'Add to Skills Profile'}</button></div></>}
  {error&&<p role="alert">{error} <button type="button" className="btn ghost" onClick={()=>{command.current=null;setError('');setAttempt(value=>value+1);}}>Reload suggestions</button></p>}
 </section>;
}

"use client";
import {useEffect,useRef,useState} from 'react';
import {roadmapApi} from '@/lib/api/roadmap';
type Proposal={id:string;name:string;description:string;proposal_hash:string};
type View={version:number;declarations_version:number;items:Proposal[]};
export function EvidenceProposals({token,version,onSaved}:{token:string;version:number;onSaved:()=>void}){
 const [view,setView]=useState<View>(),[error,setError]=useState(''),[busy,setBusy]=useState(false),[attempt,setAttempt]=useState(0);
 const command=useRef<{key:string;body:object}|null>(null);
 useEffect(()=>{const abort=new AbortController();void roadmapApi<View>('/planner/evidence-proposals',token,undefined,abort.signal).then(value=>{if(!abort.signal.aborted)setView(value);}).catch(()=>{if(!abort.signal.aborted)setError('Session evidence suggestions could not be loaded.');});return()=>abort.abort();},[token,version,attempt]);
 async function confirm(item:Proposal){if(!view||busy)return;setBusy(true);setError('');command.current??={key:item.id,body:{expected_version:view.version,expected_declarations_version:view.declarations_version,proposal_hash:item.proposal_hash,mutation_id:crypto.randomUUID()}};try{await roadmapApi(`/planner/evidence-proposals/${command.current.key}/confirm`,token,command.current.body);command.current=null;setAttempt(value=>value+1);onSaved();}catch{setError('This suggestion could not be saved. Your note is retained; reload to review the latest sources.');}finally{setBusy(false);}}
 if(!view?.items?.length&&!error)return null;
 return <section className="card pad"><h2>Evidence from your practice</h2><p>These are self-reported practice notes. Confirm each suggestion before adding it to your Skills Profile.</p>{view?.items?.map(item=><article key={item.id}><h3>{item.name}</h3><p>{item.description}</p><button className="btn ghost" disabled={busy} onClick={()=>void confirm(item)}>Confirm evidence</button></article>)}{error&&<p role="alert">{error} <button className="btn ghost" onClick={()=>{command.current=null;setError('');setAttempt(value=>value+1);}}>Reload suggestions</button></p>}</section>;
}

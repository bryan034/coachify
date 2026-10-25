"use client";
import {useEffect,useRef,useState} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {useCareerSession} from './career-session';
import {RequirementEditor} from './requirement-editor';
import {careerApi,type CurrentGoal,type JDExtraction,type ReviewSkill,type SavedReview} from '@/lib/api/career';
export function JobReviewChat(){
 const {token}=useProfile();const session=useCareerSession();const router=useRouter();const params=useSearchParams();
 const requested=params.get('review');const [review,setReview]=useState<SavedReview>();const [current,setCurrent]=useState<CurrentGoal>();
 const [editing,setEditing]=useState(false);const [busy,setBusy]=useState(false);const [loading,setLoading]=useState(true);
 const [error,setError]=useState('');const [notice,setNotice]=useState('');const [retry,setRetry]=useState(0);const [message,setMessage]=useState('');
 const [turns,setTurns]=useState<{message:string;reply:string}[]>([]);const [proposals,setProposals]=useState<ReviewSkill[]|null>(null);
 const [details,setDetails]=useState(false);const [replace,setReplace]=useState(false);
 const log=useRef<HTMLDivElement>(null);const sequence=useRef(0);const controller=useRef<AbortController|null>(null);const loaded=useRef<string|null>(null);
 const receipt=useRef<{signature:string;key:string}|null>(null);const latest=useRef(session);latest.current=session;
 const dirty=useRef(false);dirty.current=editing||!!message;
 function keyFor(signature:string){if(receipt.current?.signature!==signature)receipt.current={signature,key:crypto.randomUUID()};return receipt.current.key;}
 function remember(result:SavedReview){setReview(result);loaded.current=result.review_id;latest.current.setJDReview({...result,turns:[],proposals:null});window.history.replaceState(null,'',`/career-goal/chat?source=jd&review=${result.review_id}`);}
 useEffect(()=>{
  if(requested&&loaded.current===requested)return;
  const abort=new AbortController();controller.current?.abort();controller.current=abort;const n=++sequence.current;
  setLoading(true);setError('');
  void (async()=>{
   if(!token)return;
   try{
    const selected=await careerApi<CurrentGoal>('/goals/current',token,{signal:abort.signal});
    if(n!==sequence.current||abort.signal.aborted)return;setCurrent(selected);
    let result:SavedReview;
    if(requested)result=await careerApi<SavedReview>(`/goals/${requested}`,token,{signal:abort.signal});
    else if(latest.current.jd){
     const source=latest.current.jd;const body=JSON.stringify({text:source.text,source_url:source.url||null,source_kind:source.kind});
     result=await careerApi<SavedReview>('/jd/extract',token,{method:'POST',body,signal:abort.signal,headers:{'Idempotency-Key':keyFor('/jd/extract'+body)}});
    }else return;
    if(n!==sequence.current||abort.signal.aborted)return;remember(result);setEditing(false);setProposals(null);setTurns([]);
   }catch(cause){if(n===sequence.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not load this review.');}
   finally{if(n===sequence.current)setLoading(false);}
  })();
  return()=>{abort.abort();};
 },[requested,session.jd,token,retry]);
 useEffect(()=>()=>{sequence.current++;controller.current?.abort();},[]);
 useEffect(()=>{function warn(e:BeforeUnloadEvent){if(dirty.current){e.preventDefault();e.returnValue='';}}function link(e:MouseEvent){const anchor=(e.target as Element|null)?.closest?.('a[href]');if(!dirty.current||!anchor||e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;if(!window.confirm('Leave and discard unsaved edits? Your saved review will remain available.')){e.preventDefault();e.stopImmediatePropagation();}}window.addEventListener('beforeunload',warn);document.addEventListener('click',link,true);return()=>{window.removeEventListener('beforeunload',warn);document.removeEventListener('click',link,true);};},[]);
 useEffect(()=>{if(turns.length||busy)log.current?.scrollTo?.({top:log.current.scrollHeight});},[turns.length,busy]);
 async function save(content:JDExtraction,ack=false){
  if(!review||!token||busy)return;const abort=new AbortController();controller.current?.abort();controller.current=abort;const n=++sequence.current;
  const body=JSON.stringify({expected_version:review.version,content,acknowledge_context:ack});setBusy(true);setError('');
  try{
   const result=await careerApi<SavedReview>(`/goals/${review.review_id}/review`,token,{method:'PATCH',body,signal:abort.signal,headers:{'Idempotency-Key':keyFor('save:'+review.review_id+body)}});
   if(n!==sequence.current||abort.signal.aborted)return;remember(result);setEditing(false);setProposals(null);setNotice('Review saved.');receipt.current=null;
  }catch(cause){if(n===sequence.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not save. Your edits are retained.');}
  finally{if(n===sequence.current)setBusy(false);}
 }
 async function send(){
  if(!review||!token||busy||editing||!message.trim())return;const abort=new AbortController();controller.current?.abort();controller.current=abort;const n=++sequence.current;
  const input=message.trim();setBusy(true);setError('');
  try{
   const result=await careerApi<{reply:string;proposed_skills:ReviewSkill[]|null}>('/jd/messages',token,{method:'POST',signal:abort.signal,body:JSON.stringify({review_id:review.review_id,expected_version:review.version,message:input,conversation:turns.slice(-6).flatMap(t=>[{role:'user',content:t.message},{role:'assistant',content:t.reply}])})});
   if(n!==sequence.current||abort.signal.aborted)return;setTurns(p=>[...p,{message:input,reply:result.reply}].slice(-30));setProposals(result.proposed_skills);setMessage('');
  }catch(cause){if(n===sequence.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not respond. Your message is retained.');}
  finally{if(n===sequence.current)setBusy(false);}
 }
 async function confirm(){
  if(!review||!current||!token||busy||editing)return;const abort=new AbortController();controller.current?.abort();controller.current=abort;const n=++sequence.current;
  const c=review.extraction;const body=JSON.stringify({role:c.role,field:c.field,company:c.company,location:c.location,seniority_level:c.seniority_level,job_url:c.job_url,
   target_type:review.target_type,review_id:review.review_id,expected_review_version:review.version,expected_selection_version:current.selection_version,replace_current:replace});
  setBusy(true);setError('');
  try{
   const selected=await careerApi<CurrentGoal>('/goals/confirm',token,{method:'POST',body,signal:abort.signal,headers:{'Idempotency-Key':keyFor('confirm:'+body)}});
   if(n!==sequence.current||abort.signal.aborted)return;setCurrent(selected);setNotice('Career goal confirmed and saved.');setReplace(false);receipt.current=null;
  }catch(cause){if(n===sequence.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not confirm this goal.');}
  finally{if(n===sequence.current)setBusy(false);}
 }
 const chosen=!!review&&!!current?.goal&&(current.goal._id===review.review_id||(current.review_selection?.id===review.review_id&&current.review_selection?.version===review.version)||(current.goal.source_review_id===review.review_id&&current.goal.source_review_version===review.version));
 const replacement=!!current?.goal&&!chosen;
 function leave(){if(!dirty.current||window.confirm('Leave and discard unsaved edits? Your saved review will remain available.'))router.push('/career-goal');}
 return <section className="page on career-agent-page">
  <header className="agent-page-header"><div><p className="small">Understand the role. Shape your direction.</p><h1>Career Goal</h1></div><button className="btn ghost sm" disabled={busy} onClick={leave}>← Career Goal</button></header>
  <div className="agent-workspace"><div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true">C</span><div><strong>Coachify agent</strong><p className="small">{review?.target_type==='career_exploration'?'Career direction review':'Job description · skill review'}</p></div></div><button className="btn ghost sm" onClick={()=>setDetails(v=>!v)}>{details?'Hide details':'Conversation details'}</button></div>
   {details&&<aside className="agent-details"><p>{review?`Saved review · version ${review.version}`:'No saved review loaded'}</p>{session.jd?<details><summary>View selected description</summary><pre>{session.jd.text}</pre></details>:<p className="small">Your structured review is saved. The original description is not retained; import it again if you want a fresh extraction.</p>}</aside>}
   <div className="agent-transcript" role="log" aria-label="Career agent conversation" aria-live="polite" ref={log}>
    <div className="agent-message assistant"><span className="agent-message-label">Coachify</span><p>Let’s understand this role together. Ask about the responsibilities, qualifications or skills. You can edit the review, or ask me to propose changes for your approval.</p></div>
    {loading&&<p role="status">Opening your career goal…</p>}
    {!loading&&!review&&!error&&<p>Your selected job description was temporary and is no longer available. Add it again, or open a saved review from Career Goal.</p>}
    {review&&<>
     <div className="agent-source-card"><strong>{review.extraction.role||'Role not specified'}</strong><p className="small">{review.extraction.company||'Company not specified'} · {chosen?'Selected career goal':'Saved review'} · v{review.version}</p>{session.jd&&<button className="btn ghost sm" onClick={()=>setDetails(true)}>View description</button>}<button className="btn ghost sm" disabled={busy||editing} onClick={()=>{setEditing(true);setNotice('');}}>Edit review</button></div>
     {editing?<RequirementEditor review={review} busy={busy} onSave={(content,ack)=>void save(content,ack)} onCancel={()=>setEditing(false)}/>:<>
      <section className="jd-skills jd-context" aria-label="Extracted job context"><h2>About this role</h2><p className="small">Supporting excerpts for these role details are unavailable. Skill and condition context appears below.</p>{review.extraction.summary&&<p>{review.extraction.summary}</p>}
       <dl>{(['field','location','seniority_level'] as const).map(k=><div key={k}><dt>{({field:'Field',location:'Location',seniority_level:'Seniority'})[k]}</dt><dd>{review.extraction[k]||'Not specified'}</dd></div>)}</dl>
       {!!review.extraction.responsibilities.length&&<><h3>Responsibilities</h3><ul>{review.extraction.responsibilities.map((r,i)=><li key={i}>{r}</li>)}</ul></>}
      </section>
      <section className="jd-skills" aria-label="Extracted career skills"><h2>Skills to review</h2><p className="small">These requirements describe the role, not your current capabilities.</p>{!review.extraction.skills.length&&<p>No supported skills were identified. Ask about the available context.</p>}
       {review.extraction.skills.map((s,i)=><article key={s.item_id||i}><strong>{s.name}</strong><span className="pill n">{s.priority}</span><p className="small">{s.origin==='employer'?'JD requirement':s.origin==='user_declaration'?'User added':'Inferred / suggested'} · {s.category}{s.correction==='user'?' · Edited by you':''}</p>{s.context&&<p>{s.context}</p>}{s.evidence&&<p className="small">Supporting context: {s.evidence}</p>}{s.required_proficiency&&<p>Required proficiency: {s.required_proficiency}</p>}{s.required_experience_months!=null&&<p>Required experience: {s.required_experience_months} months</p>}{s.group_id&&<p className="small">{s.group_operator==='any'?'OR':'AND'} group: {s.group_id}</p>}</article>)}
      </section>
      <section className="jd-skills" aria-label="Non-skill requirements"><h2>Qualifications and other requirements</h2>{!review.extraction.non_skill_requirements.length&&<p>No non-skill requirements were identified.</p>}{review.extraction.non_skill_requirements.map(r=><article key={r.requirement_id}><strong>{r.description}</strong><p>{r.priority} · {r.origin==='generated_guidance'?'Suggested guidance':r.origin==='user_declaration'?'User added':'JD condition'}{r.correction==='user'?' · Edited by you':''}</p><p className="small">Supporting context: {r.evidence}</p>{(r.minimum_months!=null||r.maximum_months!=null)&&<p>Experience: {r.minimum_months??'unspecified'}–{r.maximum_months??'unspecified'} months</p>}{r.completion_status&&r.completion_status!=='unspecified'&&<p>Completion requirement: {r.completion_status.replace('_',' ')}</p>}{r.group_id&&<p className="small">{r.group_operator==='any'?'OR':'AND'} group: {r.group_id}</p>}</article>)}<p className="small">These conditions do not establish whether you meet an employer’s eligibility criteria.</p></section>
      {review.requirements_need_review&&<p role="status" className="goal-notice">The role or context changed. Open Edit review and acknowledge that you have reviewed its requirements before confirming.</p>}
      {review.extraction.skills.some(s=>!s.skill_id)&&<p className="small">Your goal is saved. Some skills need further review before they can be used in gap analysis.</p>}
      {!chosen&&<section className="agent-review"><h2>Confirm this career goal</h2>{replacement&&<label><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/>Replace {current?.goal?.role} as my selected goal; keep its history.</label>}<button className="btn pri" disabled={busy||!current||!review.extraction.role||!review.extraction.field||review.requirements_need_review||(replacement&&!replace)} onClick={()=>void confirm()}>Confirm and save goal</button></section>}
     </>}
    </>}
    {turns.map((t,i)=><div className="agent-exchange" key={i}><div className="agent-message user"><span className="agent-message-label">You</span><p>{t.message}</p></div><div className="agent-message assistant"><span className="agent-message-label">Coachify</span><p>{t.reply}</p></div></div>)}
    {proposals&&<section className="jd-proposals"><h2>Proposed skill changes</h2><p className="small">Review the full proposed list. Applying it saves a new review version.</p><ul>{proposals.map((s,i)=><li key={s.item_id||i}><strong>{s.name}</strong> · {s.priority} · {s.origin==='employer'?'JD requirement':s.origin==='user_declaration'?'User added':'Suggested guidance'}{s.context&&<p>{s.context}</p>}</li>)}</ul><button className="btn pri" disabled={busy||editing} onClick={()=>review&&void save({...review.extraction,skills:proposals})}>Apply proposed changes</button><button className="btn ghost" disabled={busy} onClick={()=>setProposals(null)}>Discard proposed changes</button></section>}
    {busy&&<p role="status">Coachify is working…</p>}{notice&&<p role="status" className="goal-notice">{notice}</p>}
    {error&&<div role="alert" className="goal-error"><p>{error}</p><p className="small">Your unsaved inputs are retained. Retry the action, or reload the saved review.</p><button className="btn ghost sm" disabled={busy} onClick={()=>{if(!dirty.current||window.confirm('Reload saved values and discard unsaved edits?')){loaded.current=null;setEditing(false);setRetry(v=>v+1);}}}>{review?'Reload saved review':'Retry extraction'}</button></div>}
   </div>
   <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}><p className="small">{editing?'Save or cancel your edits before chatting.':'Ask about the role, skills or conditions. Suggested changes need your approval.'}</p><div className="agent-compose-row"><textarea aria-label="Message Coachify" value={message} maxLength={600} rows={2} disabled={busy||loading||!review||editing} placeholder="Ask about this role…" onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={busy||loading||!review||editing||!message.trim()}>↑</button></div><button type="button" className="btn ghost sm" disabled={busy} onClick={leave}>Change job description</button></form>
  </div>
 </section>;
}

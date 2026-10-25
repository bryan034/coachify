"use client";
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {useRouter,useSearchParams} from 'next/navigation';
import Link from 'next/link';
import {useProfile} from '@/features/profile/profile-provider';
import {useCareerSession} from './career-session';
import {careerApi,importExplorationCV,type CareerContext,type CurrentGoal,type GoalDraft,type RoleSuggestion,type SavedGoal} from '@/lib/api/career';
const warning='For more reliable current-skill extraction, use the dedicated CV upload section. This career-goal agent may interpret a CV attached here less accurately.';
const emptyRole=()=>({role:'',field:'',company:'',location:'',seniority_level:''});
import {JobReviewChat} from './job-review-chat';
export function CareerChat(){
 const params=useSearchParams();
 return params.get('source')==='jd'||params.has('review')?<JobReviewChat/>:<ExplorationChat/>;
}
function ExplorationChat(){
 const {token}=useProfile();const router=useRouter();const params=useSearchParams();const session=useCareerSession();
 const requested=params.get('exploration');
 const [draft,setDraft]=useState<GoalDraft>();const [context,setContext]=useState<CareerContext>();const [current,setCurrent]=useState<CurrentGoal>();
 const [history,setHistory]=useState<GoalDraft[]>([]);const [message,setMessage]=useState('');const [pending,setPending]=useState('');
 const [consent,setConsent]=useState(false);const [cvId,setCvId]=useState('');const [useCV,setUseCV]=useState(false);
 const [cvText,setCVText]=useState('');const [cvName,setCVName]=useState('');const [busy,setBusy]=useState(false);const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');const [notice,setNotice]=useState('');const [retry,setRetry]=useState(0);
 const [review,setReview]=useState<ReturnType<typeof emptyRole>>();const [replace,setReplace]=useState(false);
 const [showDetails,setShowDetails]=useState(false);const controller=useRef<AbortController|null>(null);const seq=useRef(0);
 const mutation=useRef<{signature:string;key:string}|null>(null);const transcript=useRef<HTMLDivElement|null>(null);const reviewPanel=useRef<HTMLFormElement|null>(null);
 const latestSession=useRef(session);latestSession.current=session;
 const draftId=useRef<string|null>(null);const dirty=useRef(false);dirty.current=!!(message||cvText||review);
 useEffect(()=>()=>{seq.current++;controller.current?.abort();},[]);
 useEffect(()=>{
  function unload(event:BeforeUnloadEvent){if(dirty.current){event.preventDefault();event.returnValue='';}}
  window.addEventListener('beforeunload',unload);return()=>window.removeEventListener('beforeunload',unload);
 },[]);
 useEffect(()=>{
  if(requested&&draftId.current===requested){setBusy(false);setPending('');return;}
  const abort=new AbortController();controller.current?.abort();controller.current=abort;const n=++seq.current;
  setError('');setNotice('');setReview(undefined);setConsent(false);setMessage('');setPending('');setBusy(false);
  setDraft(undefined);setLoading(true);draftId.current=null;
  async function load(){if(!token)return;try{
   const [ctx,selected,list,restored]=await Promise.all([
    careerApi<CareerContext>('/context',token,{signal:abort.signal}),
    careerApi<CurrentGoal>('/goals/current',token,{signal:abort.signal}),
    careerApi<{goals:SavedGoal[];explorations:GoalDraft[]}>('/goals',token,{signal:abort.signal}),
    requested?careerApi<GoalDraft>(`/explorations/${requested}`,token,{signal:abort.signal}):Promise.resolve(undefined)]);
   if(n!==seq.current||abort.signal.aborted)return;
   setContext(ctx);setCurrent(selected);setHistory(list.explorations);setCvId(ctx.cvs.find(c=>c.status==='succeeded')?.id||'');
   if(restored){setDraft(restored);draftId.current=restored._id;const attachment=latestSession.current.attachment;
    setCVText(attachment?.draftId===restored._id?attachment.text:'');setCVName(attachment?.draftId===restored._id?attachment.name:'');}
   else{setCVText('');setCVName('');setUseCV(false);}
  }catch(cause){if(!abort.signal.aborted&&n===seq.current)setError(cause instanceof Error?cause.message:'Could not load the conversation.');}
   finally{if(n===seq.current)setLoading(false);}}
  void load();return()=>{seq.current++;abort.abort();};
 },[token,requested,retry]);
 useEffect(()=>{const log=transcript.current;if(log)log.scrollTo?.({top:log.scrollHeight});},[draft?.version,busy]);
 useEffect(()=>{const log=transcript.current,panel=reviewPanel.current;if(review&&log&&panel)log.scrollTo?.({top:log.scrollTop+panel.getBoundingClientRect().top-log.getBoundingClientRect().top,behavior:'instant'});},[!!review]);
 function actionKey(signature:string){if(mutation.current?.signature!==signature)mutation.current={signature,key:crypto.randomUUID()};return mutation.current.key;}
 async function post<T,>(path:string,body:unknown,signal:AbortSignal){return careerApi<T>(path,token!,{method:'POST',body:JSON.stringify(body),signal,
  headers:{'Idempotency-Key':actionKey(path+JSON.stringify(body))}});}
 async function send(skip=false){
  if(!token||busy||!consent||(!skip&&!message.trim()))return;
  const n=++seq.current;const abort=new AbortController();controller.current?.abort();controller.current=abort;
  setBusy(true);setError('');setNotice('');setPending(skip?'I’m not sure about that.':message.trim());
  try{
   let active=draft;
   if(!active){
    active=await post<GoalDraft>('/explorations',{consent:true,cv_id:useCV?cvId:null,temporary_filename:!useCV&&cvName?cvName:null},abort.signal);
    if(n!==seq.current||abort.signal.aborted)return;
    mutation.current=null;setDraft(active);draftId.current=active._id;
    if(cvText)session.setAttachment({draftId:active._id,text:cvText,name:cvName});
   }
   const next=await post<GoalDraft>(`/explorations/${active._id}/messages`,{expected_version:active.version,answer:skip?null:message.trim(),skip,
    attachment_text:active.cv.mode==='temporary'?cvText||null:null},abort.signal);
   if(n!==seq.current||abort.signal.aborted)return;
   setDraft(next);draftId.current=next._id;setHistory(h=>[next,...h.filter(d=>d._id!==next._id)]);setMessage('');mutation.current=null;
   // Native history keeps the provider mounted and does not reset consent/composer state.
   if(!requested)window.history.replaceState(null,'',`/career-goal/chat?exploration=${next._id}`);
  }catch(cause){if(n===seq.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'The agent could not respond. Your message is still here; retry.');}
  finally{if(n===seq.current){setBusy(false);setPending('');}}
 }
 async function upload(file?:File){
  if(!file||!token||busy)return;
  if(!file.size||file.size>10*1024*1024){setError('Choose a non-empty PDF, DOCX or TXT CV up to 10 MiB.');return;}
  const n=++seq.current;const abort=new AbortController();controller.current?.abort();controller.current=abort;setBusy(true);setError('');
  try{const preview=await importExplorationCV(file,token,abort.signal);if(n!==seq.current||abort.signal.aborted)return;
   setCVText(preview.text);setCVName(preview.source_name);setUseCV(false);
   if(draft)session.setAttachment({draftId:draft._id,text:preview.text,name:preview.source_name});
  }catch(cause){if(n===seq.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not read the CV.');}
  finally{if(n===seq.current)setBusy(false);}
 }
 async function confirm(event:FormEvent){
  event.preventDefault();if(!review||!draft||!current||!token||busy)return;
  const n=++seq.current;const abort=new AbortController();controller.current=abort;setBusy(true);setError('');
  try{const selected=await post<CurrentGoal>('/goals/confirm',{...Object.fromEntries(Object.entries(review).map(([k,v])=>[k,v.trim()||null])),
    target_type:'career_exploration',expected_selection_version:current.selection_version,draft_id:draft._id,expected_draft_version:draft.version,replace_current:replace},abort.signal);
   if(n!==seq.current||abort.signal.aborted)return;mutation.current=null;setCurrent(selected);setReview(undefined);setNotice('Career goal saved. Skill requirements are pending the next step.');
  }catch(cause){if(n===seq.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not save this goal.');}
  finally{if(n===seq.current)setBusy(false);}
 }
 function reviewRole(role:RoleSuggestion){setReview({...emptyRole(),role:role.role,field:role.field});setReplace(false);}
 function navigate(path:string){if(busy)return;if(!dirty.current||window.confirm('Leave this conversation? Unsent messages and temporary attachments may be discarded.'))router.push(path);}
 const needsAttachment=draft?.cv.mode==='temporary'&&!cvText;
 const initial='Hi, I’m your career agent. Tell me what you’d like to achieve, or what you’re unsure about. We’ll work through it together, one question at a time.';
 return <section className="page on career-agent-page">
  <header className="agent-page-header"><div><p className="small">Your direction, one conversation at a time</p><h1>Career Goal</h1></div><button className="btn ghost sm" disabled={busy} onClick={()=>navigate('/career-goal')}>← Career Goal</button></header>
  <div className="agent-workspace"><div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true">C</span><div><strong>Coachify agent</strong><p className="small">Career exploration</p></div></div><button className="btn ghost sm" disabled={busy} onClick={()=>setShowDetails(v=>!v)}>{showDetails?'Hide details':'Conversation details'}</button></div>
  {showDetails&&<aside className="agent-details">
    <strong>{current?.goal?`Selected goal: ${current.goal.role}`:'No career goal confirmed yet'}</strong>
    {draft&&<dl>{Object.entries(draft.answers).map(([topic,answer])=><div key={topic}><dt>{topic}</dt><dd>{answer.status==='skipped'?'Unknown / skipped':answer.value}{answer.status==='partial'?' — still clarifying':''}</dd></div>)}</dl>}
    {!!history.length&&<details><summary>Previous conversations</summary>{history.map(d=><button key={d._id} className="btn ghost sm" disabled={busy||d._id===draft?._id} onClick={()=>navigate(`/career-goal/chat?exploration=${d._id}`)}>Conversation {d._id.slice(-6)}</button>)}</details>}
  </aside>}
  {<details className="agent-cv-options"><summary>{draft?.cv.mode==='saved'?`Using ${draft.cv.filename}`:cvName?`Temporary CV: ${cvName}`:'CV optional · add or choose a CV'}</summary>
   {draft?.cv.mode!=='saved'&&<p className="small">{warning} <Link href="/cv">Go to CV upload</Link>. Dedicated uploads are not available yet; you can continue without one.</p>}
   {!draft&&!!context?.cvs.length&&<><label htmlFor="agent-saved-cv">Processed CV</label><select id="agent-saved-cv" value={cvId} onChange={e=>{setCvId(e.target.value);setUseCV(false);}}>{context.cvs.map(cv=><option key={cv.id} disabled={cv.status!=='succeeded'} value={cv.id}>{cv.filename} · {cv.status} · v{cv.version}</option>)}</select><label><input type="checkbox" checked={useCV} disabled={!cvId} onChange={e=>{setUseCV(e.target.checked);if(e.target.checked){setCVName('');setCVText('');}}}/>Use this processed CV</label></>}
   {(!draft||draft.cv.mode==='temporary')&&<><label htmlFor="agent-cv-file">{needsAttachment?'Reattach the same temporary CV':'Temporary CV attachment'}</label><input id="agent-cv-file" type="file" accept=".pdf,.docx,.txt" disabled={busy} onChange={e=>void upload(e.target.files?.[0])}/></>}
   {draft?.cv.mode==='saved'&&<p className="small">CV version {draft.cv.version} · extraction {draft.cv.extraction_version}</p>}
   {draft&&<button className="btn ghost sm" disabled={busy} onClick={()=>{session.chooseJD(null);draftId.current=null;navigate('/career-goal/chat');}}>Start a new conversation to change CV context</button>}
  </details>}
  <div className="agent-transcript" ref={transcript} role="log" aria-label="Career agent conversation" aria-live="polite">
   <div className="agent-message assistant"><span className="agent-message-label">Coachify</span><p>{initial}</p></div>
   {!draft&&<p className="agent-cv-reminder small">No CV is required to start. {warning} <Link href="/cv">CV upload</Link></p>}
   {loading&&<p role="status">Opening your conversation…</p>}
   {draft?.turns.map((turn,index)=><div className="agent-exchange" key={`${draft._id}-${index}`}><div className="agent-message user"><span className="agent-message-label">You</span><p>{turn.answer.value||'I’m not sure; skip this for now.'}</p></div><div className="agent-message assistant"><span className="agent-message-label">Coachify</span><p>{turn.reply}</p></div></div>)}
   {draft&&(draft.total_turns||0)>draft.turns.length&&<p className="small">Earlier messages are summarised in the saved conversation details.</p>}
   {pending&&<div className="agent-message user"><span className="agent-message-label">You</span><p>{pending}</p></div>}
   {busy&&<p role="status" className="agent-thinking">Coachify is thinking<span aria-hidden="true">…</span></p>}
   {draft?.context_complete&&!!draft.suggestions.length&&<div className="agent-directions"><p className="small">Directions we can explore · AI guidance</p>{draft.suggestions.map((role,index)=><article key={index}><h2>{role.role}</h2><p>{role.rationale}</p><p className="small">Still uncertain: {role.uncertainty}</p><button className="btn ghost sm" disabled={busy} onClick={()=>reviewRole(role)}>Review this direction</button></article>)}</div>}
   {notice&&<p role="status" className="goal-notice">{notice}</p>}
   {error&&<div role="alert" className="goal-error"><p>{error}</p><p className="small">Your inputs are still here. Retry the request when the service is available.</p><button className="btn ghost sm" disabled={busy} onClick={()=>{if(!dirty.current||window.confirm('Reload saved progress and discard unsent edits?')){draftId.current=null;setRetry(v=>v+1);}}}>Reload conversation</button></div>}
  {review&&<form ref={reviewPanel} className="agent-review" onSubmit={confirm}><h2>Review your career goal</h2>{(Object.keys(review) as (keyof typeof review)[]).map(field=><label key={field}>{({role:'Role',field:'Field',company:'Company',location:'Location',seniority_level:'Seniority'})[field]}<input required={field==='role'||field==='field'} maxLength={160} value={review[field]} onChange={e=>setReview({...review,[field]:e.target.value})}/></label>)}<p className="small">Company is optional. Skill requirements will remain pending until the next stage.</p>{current?.goal&&<label><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/>Replace {current.goal.role} as my selected goal; keep its history.</label>}<div className="row"><button className="btn pri" disabled={busy||!!current?.goal&&!replace}>Confirm and save goal</button><button type="button" className="btn ghost" disabled={busy} onClick={()=>setReview(undefined)}>Cancel</button></div></form>}
  </div>
  <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}>
   <label className="agent-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>Allow Coachify to send this conversation and chosen CV context to the configured AI provider.</label>
   <div className="agent-compose-row"><textarea aria-label="Message Coachify" placeholder="Tell me what you’re hoping to achieve…" value={message} maxLength={600} rows={2} disabled={busy||loading} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={busy||loading||!message.trim()||(!consent||needsAttachment||!current)}>↑</button></div>
   {<div className="agent-compose-meta"><span className="small">Enter to send · Shift+Enter for a new line</span>{draft?.next_question&&<button type="button" className="btn ghost sm" disabled={busy||!consent||needsAttachment} onClick={()=>void send(true)}>Skip this question</button>}</div>}
   {needsAttachment&&<p role="status" className="small">Reattach the temporary CV above, or start a new conversation without it.</p>}
  </form></div>
 </section>;
}

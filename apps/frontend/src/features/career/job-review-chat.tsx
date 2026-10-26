"use client";
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {useCareerSession} from './career-session';
import {AgentMarkdown,AgentActivity,AgentReply,AgentRecovery,errorCode,isTokenLimit} from './agent-message';
import {RequirementEditor} from './requirement-editor';
import {careerApi,type JDExtraction,type ReviewSkill,type CareerWorkspace} from '@/lib/api/career';

function introduction(workspace:CareerWorkspace){
 const c=workspace.review?.extraction,r=workspace.research;if(!c||!r)return '';
 const stages=[...new Set([...(r.process?.stages.map(s=>s.name)||[]),...r.skills.map(s=>s.interview_stage).filter(Boolean)])];
 const assessments=[...new Set(r.skills.map(s=>s.assessment_type).filter(Boolean))];
 return [
  workspace.review?.requirements_need_review?'> The role context changed; review the listed requirements because they may belong to the earlier role.':'',
  '## Your career goal',`Let’s look at ${c.role}${c.company?' at '+c.company:''}.`,
  [c.location?`**Location:** ${c.location}`:'',c.seniority_level?`**Level:** ${c.seniority_level}`:''].filter(Boolean).join(' · '),
  '### Role overview',c.summary||`This role focuses on ${c.field||'the responsibilities in your description'}.`,
  c.responsibilities.length?'**Main responsibilities**\n'+c.responsibilities.slice(0,4).map(v=>`- ${v}`).join('\n'):'',
  '### Skills for this role',
  workspace.review?.target_type==='career_exploration'?'These skills are general AI planning suggestions, not employer-stated requirements.':'',
  c.skills.length?c.skills.slice(0,8).map(s=>`- **${s.name}** — ${s.priority}`).join('\n'):'No supported skills were identified in the description.',
  c.non_skill_requirements.length?'### Qualifications and conditions\n'+c.non_skill_requirements.slice(0,6).map(v=>`- ${v.description}`).join('\n'):'',
  '### Interview process',
  r.process?.round_count!=null?`**Reported interview rounds:** ${r.process.round_count}.`:'The number of interview rounds is not established by the saved research.',
  stages.length?'**Reported interview stages**\n'+stages.map(v=>`- ${v}`).join('\n'):'The sources do not establish the interview stages.',
  assessments.length?'**Reported assessments**\n'+assessments.map(v=>`- ${v}`).join('\n'):'Assessment formats remain unknown.',
  '### Interview preparation',
  r.skills.length?r.skills.slice(0,8).map(s=>`- **${s.name}**`).join('\n'):'No supported interview topics were found; this does not establish that interviews have no requirements.',
  r.skills.some(s=>s.evidence_origin==='brave_summary')?'Some interview findings are Brave AI synthesis linked to sources, rather than direct website quotations.':'',
  'Interview reports are preparation guidance, not guaranteed questions.',
  '**What would you like to know?** Ask about the role, a required skill, or the reported interview process.'
 ].filter(Boolean).join('\n\n');
}
export function JobReviewChat(){
 const {token}=useProfile(),session=useCareerSession(),router=useRouter();
 const [workspace,setWorkspace]=useState<CareerWorkspace>(),[editing,setEditing]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[code,setCode]=useState('');
 const [reload,setReload]=useState(0),[pendingMessage,setPendingMessage]=useState<string|null>(null);
 const transcript=useRef<HTMLDivElement|null>(null);
 const [retryAt,setRetryAt]=useState<number|null>(null),[secondsLeft,setSecondsLeft]=useState(0);
 function reportError(cause:unknown,fallback:string){
  setError(cause instanceof Error?cause.message:fallback);setCode(errorCode(cause));
  setRetryAt(cause instanceof Error&&'retryAt' in cause&&typeof cause.retryAt==='number'&&Number.isFinite(cause.retryAt)?cause.retryAt:null);
 }
 useEffect(()=>{
  const update=()=>setSecondsLeft(retryAt?Math.max(0,Math.ceil((retryAt-Date.now())/1000)):0);
  update();if(!retryAt)return;const timer=setInterval(update,1000);return()=>clearInterval(timer);
 },[retryAt]);
 const [message,setMessage]=useState(''),[turns,setTurns]=useState<{message:string;reply:string}[]>([]),[proposals,setProposals]=useState<ReviewSkill[]|null>(null),[details,setDetails]=useState(false);
 const saveReceipt=useRef<{body:string;key:string}|null>(null);
 const controller=useRef<AbortController|null>(null),key=useRef(crypto.randomUUID()),revision=useRef(''),source=useRef(session.jd),latest=useRef(session);latest.current=session;
 const review=workspace?.review;const ready=workspace?.phase==='ready'&&!!workspace.research;
 function receive(value:CareerWorkspace){
  if(revision.current!==value.session_id){setTurns([]);setProposals(null);setMessage('');setEditing(false);revision.current=value.session_id||'';}
  setRetryAt(value.phase==='waiting_quota'?Date.now()+(value.retry_after||60)*1000:null);
  setWorkspace(value);
 }
 useEffect(()=>{
  if(!token)return;const abort=new AbortController();controller.current=abort;setBusy(true);setError('');setCode('');
  void (async()=>{try{
   const jd=source.current;
   const value=await careerApi<CareerWorkspace>(jd?'/workspace/jd':'/workspace',token,{signal:abort.signal,...(jd?{method:'POST',headers:{'Idempotency-Key':key.current},body:JSON.stringify({text:jd.text,source_url:jd.url||null,source_kind:jd.kind})}:{})});
   if(abort.signal.aborted)return;receive(value);
   if(jd){source.current=null;latest.current.chooseJD(null);}
  }catch(cause){if(!abort.signal.aborted)reportError(cause,'Could not open your career goal.');}
   finally{if(!abort.signal.aborted)setBusy(false);}})();return()=>abort.abort();
 },[token,reload]);
 useEffect(()=>{
  if(!token||!workspace||!['research_pending','researching','waiting_quota'].includes(workspace.phase))return;
  const abort=new AbortController(),timer=setTimeout(()=>{void careerApi<CareerWorkspace>('/workspace',token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted)receive(v);}).catch(c=>{if(!abort.signal.aborted)reportError(c,'Could not refresh your career goal.');});},workspace.phase==='waiting_quota'?Math.max(2000,Math.min(workspace.retry_after||60,3600)*1000):2000);
  return()=>{clearTimeout(timer);abort.abort();};
 },[token,workspace]);
 useEffect(()=>()=>controller.current?.abort(),[]);
 useEffect(()=>{const log=transcript.current;log?.scrollTo?.({top:turns.length||pendingMessage?log.scrollHeight:0,behavior:'instant'});},[workspace?.phase,turns,pendingMessage,error]);
 const dirty=useRef(false);dirty.current=!!message||editing;
 useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirty.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
 function followReply(){const log=transcript.current;if((turns.length||pendingMessage)&&log&&log.scrollHeight-log.scrollTop-log.clientHeight<120)log.scrollTo?.({top:log.scrollHeight,behavior:'instant'});}
 async function retry(){if(!token||busy||secondsLeft>0)return;setBusy(true);setError('');setCode('');try{receive(await careerApi<CareerWorkspace>('/workspace/retry',token,{method:'POST'}));}catch(c){reportError(c,'Retry failed.');}finally{setBusy(false);}}
 async function save(content:JDExtraction,ack=false){
  if(!review||!token||busy)return;setBusy(true);setError('');setCode('');
  const body=JSON.stringify({session_id:workspace?.session_id,expected_version:review.version,content,acknowledge_context:ack});
  if(saveReceipt.current?.body!==body)saveReceipt.current={body,key:crypto.randomUUID()};
  try{receive(await careerApi<CareerWorkspace>('/workspace/review',token,{method:'PATCH',headers:{'Idempotency-Key':saveReceipt.current.key},body}));setEditing(false);setProposals(null);saveReceipt.current=null;}
  catch(c){reportError(c,'Could not save; your edits are retained.');}finally{setBusy(false);}
 }
 async function send(){
  if(!workspace?.session_id||!review||!ready||!token||busy||editing||!message.trim()||secondsLeft>0)return;
  const input=message.trim(),abort=new AbortController();controller.current=abort;setPendingMessage(input);setBusy(true);setError('');setCode('');
  try{const result=await careerApi<{reply:string;proposed_skills:ReviewSkill[]|null}>('/workspace/messages',token,{method:'POST',signal:abort.signal,body:JSON.stringify({session_id:workspace.session_id,expected_version:review.version,message:input,conversation:turns.slice(-1).flatMap(t=>[{role:'user',content:t.message},{role:'assistant',content:t.reply}])})});
   if(!abort.signal.aborted){setTurns(p=>[...p,{message:input,reply:result.reply}].slice(-30));setMessage('');setProposals(result.proposed_skills);}}
  catch(c){if(!abort.signal.aborted)reportError(c,'Could not answer. Your message is retained.');}finally{if(!abort.signal.aborted){setBusy(false);setPendingMessage(null);}}
 }
 return <section className="page on career-agent-page">
  <header className="agent-page-header"><div><p className="small">Your direction, one conversation</p><h1>Career Goal</h1></div><button className="btn ghost sm" disabled={busy} onClick={()=>{if(!dirty.current||window.confirm('Leave and discard unsent edits? Your saved goal stays current.'))router.push('/career-goal');}}>← Career Goal</button></header>
  <div className="agent-workspace"><div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true">C</span><div><strong>Coachify agent</strong><p className="small">{review?.extraction.role||'Understanding your career goal'}</p></div></div><button className="btn ghost sm" onClick={()=>setDetails(v=>!v)}>{details?'Hide details':'Role and research details'}</button></div>
   {workspace?.phase==='empty'&&<p role="status">No job description is available. Import a JD from Career Goal or explore a direction.</p>}
   {details&&review&&<aside className="agent-details"><h2>{review.extraction.role}</h2><p>{review.extraction.company||'General career direction'} · v{review.version} · Saved automatically</p>
    <h3>Main job skills</h3><ul>{review.extraction.skills.map((s,i)=><li key={s.item_id||i}>{s.name} · {s.priority}</li>)}</ul>
    {workspace?.research&&<><h3>Interview preparation</h3><p>Reported rounds: {workspace.research.process?.round_count??'Unknown'}</p>{workspace.research.process?.stages.map((stage,i)=><p key={i}>{stage.name}{stage.assessment_type?` · ${stage.assessment_type}`:''}</p>)}{workspace.research.summaries?.map(summary=><details key={summary.summary_id}><summary>Brave AI interview summary</summary><p className="small">AI synthesis · linked sources · findings may be uncertain</p><AgentMarkdown>{summary.text}</AgentMarkdown>{summary.source_ids.map(id=>{const source=workspace.research!.sources.find(s=>s.source_id===id);return source?<p key={id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.platform}</a></p>:null;})}</details>)}{workspace.research.skills.map((s,i)=><article key={i}><strong>{s.name}</strong>{s.evidence_origin==='brave_summary'&&<p className="small">Brave AI synthesis · source-linked, not a direct website quotation</p>}<p>{s.interview_stage||'Stage unknown'} · {s.assessment_type||'Assessment unknown'} · Difficulty: {s.difficulty||'Unknown'}</p><p className="small">Independent reports: {workspace.research!.sources.filter(v=>s.source_ids.includes(v.source_id)).some(v=>!v.report_group)?'Unknown':s.independent_report_count}</p>{s.source_ids.map(id=>{const evidence=workspace.research!.sources.find(v=>v.source_id===id);return evidence?<details key={id}><summary>{evidence.title||evidence.platform}</summary><p>{evidence.evidence}</p><a href={evidence.url} target="_blank" rel="noopener noreferrer">View source</a><p className="small">{evidence.reliability} · Context: {evidence.role_match} · Published: {evidence.published_date||'Unknown'} · Reported: {evidence.reported_date||'Unknown'} · Retrieved: {evidence.retrieved_at||'Unknown'}</p></details>:null;})}</article>)}</>}

   </aside>}
   <div ref={transcript} className="agent-transcript" role="log" aria-label="Career agent conversation" aria-live="polite">
    <div className="agent-message assistant" key="initial-answer"><span className="agent-message-label">Coachify</span>
     {ready?<AgentReply onProgress={followReply}>{introduction(workspace!)}</AgentReply>:<>
      {(!workspace||['research_pending','researching','waiting_quota'].includes(workspace.phase))&&!error&&<AgentActivity
       label={workspace?.phase==='waiting_quota'?'Waiting for the AI token budget':workspace?.phase==='researching'||workspace?.phase==='research_pending'?'Researching interview expectations with Brave…':source.current?'Extracting your career goal…':'Opening your career goal…'}
       detail={workspace?.phase==='waiting_quota'?(secondsLeft>0?`Resuming in ${secondsLeft} seconds.`:'Retrying research…'):workspace?.review?'Job skills are extracted. Preparing source-backed interview findings.':undefined}/>}
      {workspace?.error&&(workspace.phase==='waiting_quota'||isTokenLimit(workspace.error_code))&&<p role="alert" className="small">{workspace.error}</p>}
      {workspace&&['research_failed','expired'].includes(workspace.phase)&&<button className="btn pri" disabled={busy} onClick={()=>void retry()}>Resume research</button>}
     </>}
    </div>
    {turns.map((turn,i)=><div className="agent-exchange" key={i}><div className="agent-message user"><span className="agent-message-label">You</span><p>{turn.message}</p></div><div className="agent-message assistant"><span className="agent-message-label">Coachify</span><AgentReply animate={i===turns.length-1} onProgress={followReply}>{turn.reply}</AgentReply></div></div>)}
    {pendingMessage&&<div className="agent-exchange"><div className="agent-message user"><span className="agent-message-label">You</span><p>{pendingMessage}</p></div><div className="agent-message assistant"><span className="agent-message-label">Coachify</span><AgentActivity label="Preparing your answer…" detail="Using your career goal and saved interview research."/></div></div>}
    {review&&<><p className="small">Validated updates are saved as your latest career goal automatically.</p>{editing?<RequirementEditor review={review} busy={busy} onSave={(v,a)=>void save(v,a)} onCancel={()=>setEditing(false)}/>:<button className="btn ghost sm" disabled={busy} onClick={()=>setEditing(true)}>Edit career goal</button>}</>}
    {proposals&&review&&<section className="agent-review"><h2>Suggested skill changes</h2><ul>{proposals.map((s,i)=><li key={i}>{s.name} · {s.priority}</li>)}</ul><button className="btn pri" disabled={busy} onClick={()=>void save({...review.extraction,skills:proposals})}>Apply skill changes</button><button className="btn ghost" onClick={()=>setProposals(null)}>Dismiss</button></section>}
    {error&&<AgentRecovery message={error} code={code} seconds={retryAt?secondsLeft:undefined} disabled={busy||editing||secondsLeft>0} onRetry={()=>{if(source.current)setReload(v=>v+1);else if(ready&&message.trim())void send();else void retry();}}/>}
   </div>
   <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}><div className="agent-compose-row"><textarea aria-label="Message Coachify" placeholder="Ask about the role, skills or interview preparation…" value={message} maxLength={600} disabled={busy||!ready||editing} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={busy||!ready||editing||!message.trim()||secondsLeft>0}>↑</button></div><p className="small">Enter to send · Shift+Enter for a new line</p></form>
  </div>
 </section>;
}

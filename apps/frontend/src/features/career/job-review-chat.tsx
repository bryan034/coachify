"use client";
import {ChatScrollControl,useChatScroll} from './use-chat-scroll';
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {useCareerSession} from './career-session';
import {AgentMarkdown,AgentActivity,AgentProgress,AgentReply,AgentRecovery,errorCode,isTokenLimit} from './agent-message';
import {sourceCitations} from './source-links';
import {careerOperation,type CareerOperation} from '@/lib/api/career-operation';
import {careerApi,refreshWorkspace,type OpportunityView,type CareerWorkspace} from '@/lib/api/career';

function introduction(workspace:CareerWorkspace){
 const c=workspace.current.goal;if(!c)return '';
 return [
  workspace.current.goal?.requirements_need_review?'> The role context changed; the listed requirements may belong to the earlier role. Tell the agent which requirements to keep or change.':'',
  '## Your career goal',`Let’s look at ${c.role}${c.company?' at '+c.company:''}.`,
  [c.location?`**Location:** ${c.location}`:'',c.seniority_level?`**Level:** ${c.seniority_level}`:''].filter(Boolean).join(' · '),
  '### Role overview',c.summary||`This role focuses on ${c.field||'the responsibilities in your description'}.`,
  c.responsibilities?.length?'**Main responsibilities**\n'+c.responsibilities.slice(0,4).map(v=>`- ${v}`).join('\n'):'',
  '### Skills for this role',
  workspace.current.goal?.target_type==='career_exploration'?'These skills are general AI planning suggestions, not employer-stated requirements.':'',
  c.skills.length?c.skills.slice(0,8).map(s=>`- **${s.name}** — ${s.priority}`).join('\n'):'No supported skills were identified in the description.',
  c.non_skill_requirements?.length?'### Qualifications and conditions\n'+c.non_skill_requirements.slice(0,6).map(v=>`- ${v.description}`).join('\n'):'',
 ].filter(Boolean).join('\n\n');
}
function researchPending(workspace:CareerWorkspace){
 return ['research_pending','researching','waiting_quota'].includes(workspace.phase);
}
function responseReady(workspace:CareerWorkspace,research?:OpportunityView){
 return !!workspace.current.goal&&workspace.phase==='ready'&&!!research&&research.career_target_id===workspace.current.goal._id&&research.research_id===workspace.research_id&&research.finished!==false&&research.status==='completed'&&Object.values(research.categories).every(category=>category?.status==='completed'||category?.status==='not_applicable');
}
function researchSummary(research?:OpportunityView,coverage:CareerWorkspace['coverage']=[]){
 if(!research)return '';
 const ranked=[...(research.summary?.overview_refs||[]),...(research.summary?.key_takeaway_refs||[]),...(research.summary?.consideration_refs||[])];
 const labels={interview_intelligence:'Interview findings',internship_insights:'Internship experience',career_progression:'Career progression and conversion salary',conversion_outcomes:'Historical full-time conversion rates',company_intelligence:'Company and team culture'};
 const reach=[...coverage].reverse().find(v=>v.target_sources!=null);
 const sections:string[]=reach?[`Research found useful interview information from **${reach.useful_sources||0} distinct sources**.${(reach.useful_sources||0)<(reach.target_sources||3)?' Findings remain limited.':''}`]:[];
 for(const [key,category] of Object.entries(research.categories)){
  if(!category)continue;
  sections.push('### '+labels[key as keyof typeof labels]);
  const selected=[...category.findings].sort((a,b)=>(ranked.includes(a.finding_id)?ranked.indexOf(a.finding_id):ranked.length)-(ranked.includes(b.finding_id)?ranked.indexOf(b.finding_id):ranked.length)).slice(0,5);
  sections.push(selected.map(f=>'- '+f.value+(f.scope!=='exact'?' (related context)':'')+' '+sourceCitations(f.source_ids,research.sources||[])).join('\n')||'Information pertaining to this category was not found in the retrieved sources.');
  if(category.status==='failed')sections.push('This category could not finish. Your goal is saved; you can retry research.');
 }
 sections.push('Your career goal and its category cards are saved. Ask about this role, its requirements or the findings, or tell me how you want to refine your goal.');
 return sections.join('\n\n');
}
export function JobReviewChat(){
 const {token}=useProfile(),session=useCareerSession(),router=useRouter();
 const [research,setResearch]=useState<OpportunityView>();
 const [workspace,setWorkspace]=useState<CareerWorkspace>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[code,setCode]=useState('');
 const [reload,setReload]=useState(0),[pendingMessage,setPendingMessage]=useState<string|null>(null);
 const {transcript,followReply,showJump,jumpToLatest,scrollProps}=useChatScroll();
 const [operation,setOperation]=useState<CareerOperation|null>(null);
 const [extractionSteps,setExtractionSteps]=useState<string[]>([]);
 const [retryAt,setRetryAt]=useState<number|null>(null),[secondsLeft,setSecondsLeft]=useState(0);
 function operationProgress(job:CareerOperation){
  if(source.current)setExtractionSteps(previous=>[...new Set([...previous,...(job.activities||[])])]);
  setOperation(job);setRetryAt(job.status==='waiting_quota'?Date.now()+(job.retry_after||1)*1000:null);
 }
 function reportError(cause:unknown,fallback:string){
  setError(cause instanceof Error?cause.message:fallback);setCode(errorCode(cause));
  setRetryAt(cause instanceof Error&&'retryAt' in cause&&typeof cause.retryAt==='number'&&Number.isFinite(cause.retryAt)?cause.retryAt:null);
 }
 useEffect(()=>{
  const update=()=>setSecondsLeft(retryAt?Math.max(0,Math.ceil((retryAt-Date.now())/1000)):0);
  update();if(!retryAt)return;const timer=setInterval(update,1000);return()=>clearInterval(timer);
 },[retryAt]);
 const [message,setMessage]=useState(''),[turns,setTurns]=useState<{message:string;reply:string}[]>([]),[details,setDetails]=useState(false);
 const messageReceipt=useRef<{body:string;key:string}|null>(null);
 const controller=useRef<AbortController|null>(null),key=useRef(session.jdKey||crypto.randomUUID()),revision=useRef(''),source=useRef(session.jd),latest=useRef(session);latest.current=session;
 const refining=useRef(typeof window!=='undefined'&&new URLSearchParams(window.location.search).get('refine')==='1');
 const chatCooldown=!!error&&isTokenLimit(code)&&secondsLeft>0;
 const waitLabel=(operation?.limit_scope||workspace?.limit_scope)==='user'?'Waiting for the AI service to resume':'Waiting for the research service to resume';
 const goal=workspace?.current.goal;const ready=!!workspace&&responseReady(workspace,research);
 const detailsReady=!!goal&&(ready||workspace?.phase==='research_failed'||workspace?.phase==='expired');
 useEffect(()=>{
  if(!token||!goal||!workspace?.research_id)return;const abort=new AbortController();
  void careerApi<OpportunityView>(`/goals/${goal._id}/opportunity-research?research_id=${workspace.research_id}`,token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted)setResearch(v);}).catch(c=>{if(!abort.signal.aborted)reportError(c,'Could not load research.');});
  return()=>abort.abort();
 },[token,goal?._id,workspace?.research_id]);
 function receive(value:CareerWorkspace){
  if(revision.current!==value.session_id){setTurns([]);setMessage('');messageReceipt.current=null;revision.current=value.session_id||'';}
  setRetryAt(value.phase==='waiting_quota'?Date.now()+(value.retry_after||60)*1000:null);
  setWorkspace(value);
 }
 useEffect(()=>{
  if(!token)return;const abort=new AbortController();controller.current=abort;setBusy(true);setError('');setCode('');
  void (async()=>{try{
   const jd=source.current;
   const value=jd?await careerOperation<CareerWorkspace>('/workspace/jd',token,{signal:abort.signal,method:'POST',headers:{'Idempotency-Key':key.current},body:JSON.stringify({text:jd.text,source_url:jd.url||null,source_kind:jd.kind})},operationProgress):await careerApi<CareerWorkspace>('/workspace',token,{signal:abort.signal});
   if(abort.signal.aborted)return;receive(value);
   if(jd){setExtractionSteps(previous=>[...new Set([...previous,'saving_goal'])]);source.current=null;latest.current.chooseJD(null);}
  }catch(cause){if(!abort.signal.aborted)reportError(cause,'Could not open your career goal.');}
   finally{if(!abort.signal.aborted){setBusy(false);setOperation(null);}}})();return()=>abort.abort();
 },[token,reload]);
 useEffect(()=>{
  if(!token||!workspace||!researchPending(workspace))return;
  const abort=new AbortController(),timer=setTimeout(()=>{void refreshWorkspace(workspace,token,abort.signal).then(v=>{if(!abort.signal.aborted)receive(v);}).catch(c=>{if(!abort.signal.aborted)reportError(c,'Could not refresh your career goal.');});},workspace.phase==='waiting_quota'?Math.max(2000,Math.min(workspace.retry_after||60,3600)*1000):2000);
  return()=>{clearTimeout(timer);abort.abort();};
 },[token,workspace]);
 useEffect(()=>()=>controller.current?.abort(),[]);
 const dirty=useRef(false);dirty.current=!!message;
 useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirty.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
 async function retry(){if(!token||busy||secondsLeft>0)return;setBusy(true);setError('');setCode('');try{receive(await careerApi<CareerWorkspace>('/workspace/retry',token,{method:'POST'}));}catch(c){reportError(c,'Retry failed.');}finally{setBusy(false);}}
 async function send(){
  if(!workspace?.session_id||!goal||!ready||!token||busy||!message.trim()||chatCooldown)return;
  const input=message.trim(),abort=new AbortController();controller.current=abort;setPendingMessage(input);setBusy(true);setError('');setCode('');
  const body=JSON.stringify({session_id:workspace.session_id,expected_version:goal.version,message:input,mode:refining.current?'refine':'question',conversation:turns.slice(-1).flatMap(t=>[{role:'user',content:t.message},{role:'assistant',content:t.reply}])});
  if(messageReceipt.current?.body!==body)messageReceipt.current={body,key:crypto.randomUUID()};
  try{const result=await careerOperation<{reply:string;workspace?:CareerWorkspace;edit_status?:string}>('/workspace/messages',token,{method:'POST',signal:abort.signal,headers:{'Idempotency-Key':messageReceipt.current.key},body},operationProgress);
   if(!abort.signal.aborted){if(result.workspace)receive(result.workspace);setTurns(p=>[...p,{message:input,reply:result.reply}].slice(-30));setMessage('');setRetryAt(null);messageReceipt.current=null;}}
  catch(c){if(!abort.signal.aborted)reportError(c,'Could not answer. Your message is retained.');}finally{if(!abort.signal.aborted){setBusy(false);setPendingMessage(null);setOperation(null);}}
 }
 return <section className="page on career-agent-page">
  <header className="agent-page-header"><div><p className="small">Your direction, one conversation</p><h1>Career Goal</h1></div><button className="btn ghost sm" disabled={busy} onClick={()=>{if(!dirty.current||window.confirm('Leave and discard unsent edits? Your saved goal stays current.'))router.push('/career-goal');}}>← Career Goal</button></header>
  <div className="agent-workspace"><div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true">C</span><div><strong>Coachify agent</strong><p className="small">{goal?.role||'Understanding your career goal'}</p></div></div><button className="btn ghost sm" disabled={!detailsReady} onClick={()=>setDetails(v=>!v)}>{details?'Hide details':'Role and research details'}</button></div>
   {workspace?.phase==='empty'&&<p role="status">No job description is available. Import a JD from Career Goal or explore a direction.</p>}
   {details&&detailsReady&&goal&&<aside className="agent-details"><h2>{goal.role}</h2><p>{goal.company||'General career direction'} · v{goal.version} · Saved automatically</p>
    <h3>Main job skills</h3><ul>{goal.skills.map((s,i)=><li key={s.item_id||i}>{s.name} · {s.priority}</li>)}</ul>
    {ready?<AgentMarkdown>{researchSummary(research,workspace?.coverage)}</AgentMarkdown>:<p className="small">Research is incomplete. Your saved goal details remain available.</p>}
   </aside>}

   <div ref={transcript} className="agent-transcript" {...scrollProps} role="log" aria-label="Career agent conversation" aria-live="polite">
    <AgentProgress steps={[...extractionSteps,...(operation?.activities||[]),...(workspace?.activities||[])]}/>
    <div className="agent-message assistant" key="initial-answer"><span className="agent-message-label">Coachify</span>
     {ready&&<AgentReply onProgress={followReply}>{refining.current?'What would you like to refine in your career goal? We can work through your role, location, skills, qualifications or responsibilities. Tell me what feels different, and I’ll ask for any details needed before saving the update.':[introduction(workspace!),researchSummary(research,workspace?.coverage)].filter(Boolean).join('\n\n')}</AgentReply>}{<>
      {(!workspace||researchPending(workspace))&&!error&&<AgentActivity
       label={operation?.status==='waiting_quota'||workspace?.phase==='waiting_quota'?waitLabel:operation?.status==='repairing'?'Refining the response…':workspace?.phase==='researching'||workspace?.phase==='research_pending'?'Researching interview expectations…':source.current?'Extracting your career goal…':'Opening your career goal…'}
       detail={operation?.status==='waiting_quota'||workspace?.phase==='waiting_quota'?(secondsLeft>0?`Resuming in ${secondsLeft} seconds.`:'Retrying research…'):workspace?.current.goal?'Your goal is saved. I’m finishing the research so I can present both results together.':undefined}/>}
      {workspace?.error&&(workspace.phase==='waiting_quota'||isTokenLimit(workspace.error_code))&&<p role="alert" className="small">{workspace.phase==='waiting_quota'?'Research is waiting for the service quota to reset. Your career goal remains saved.':workspace.error}</p>}
      {workspace&&(['research_failed','expired'].includes(workspace.phase)||workspace.phase==='ready'&&!ready&&!researchPending(workspace))&&<button className="btn pri" disabled={busy} onClick={()=>void retry()}>Resume research</button>}
     </>}
    </div>
    {ready&&workspace?.edit_question&&!turns.length&&!pendingMessage&&<div className="agent-message assistant"><span className="agent-message-label">Coachify</span><AgentReply onProgress={followReply}>{workspace.edit_question}</AgentReply></div>}
    {turns.map((turn,i)=><div className="agent-exchange" key={i}><div className="agent-message user"><span className="agent-message-label">You</span><p>{turn.message}</p></div><div className="agent-message assistant"><span className="agent-message-label">Coachify</span><AgentReply animate={i===turns.length-1} onProgress={followReply}>{turn.reply}</AgentReply></div></div>)}
    {pendingMessage&&<div className="agent-exchange"><div className="agent-message user"><span className="agent-message-label">You</span><p>{pendingMessage}</p></div><div className="agent-message assistant"><span className="agent-message-label">Coachify</span><AgentActivity label={operation?.status==='waiting_quota'?waitLabel:operation?.status==='repairing'?'Refining the response…':'Preparing your answer…'} detail={operation?.status==='waiting_quota'?`Resuming automatically in ${secondsLeft} seconds.`:'Using your career goal and saved interview research.'}/></div></div>}
    {ready&&<p className="small">Want to change your career goal? Tell the agent what to update. Clear requests are saved automatically.</p>}
    {error&&<AgentRecovery message={error} code={code} seconds={retryAt?secondsLeft:undefined} disabled={busy||chatCooldown} onRetry={()=>{if(source.current)setReload(v=>v+1);else if(ready&&message.trim())void send();else void retry();}}/>}
   </div>
   <ChatScrollControl visible={showJump} onClick={jumpToLatest}/>
   <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}><div className="agent-compose-row"><textarea aria-label="Message Coachify" placeholder="Ask a question or describe a change to your career goal…" value={message} maxLength={600} disabled={busy||!ready} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={busy||!ready||!message.trim()||chatCooldown}>↑</button></div><p className="small">Enter to send · Shift+Enter for a new line</p></form>
  </div>
 </section>;
}

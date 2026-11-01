"use client";
import { BrandLogo } from '@/components/ui/brand-logo';
import {ChatScrollControl,useChatScroll} from './use-chat-scroll';
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {useCareerSession} from './career-session';
import {AgentMarkdown,AgentActivity,AgentProgress,AgentReply,AgentRecovery,errorCode,isTokenLimit,observedActivity} from './agent-message';
import {sourceCitations} from './source-links';
import {careerOperation,type CareerOperation} from '@/lib/api/career-operation';
import {retryCareerRead} from '@/lib/api/career-polling';
import {careerApi,refreshWorkspace,type OpportunityView,type CareerWorkspace} from '@/lib/api/career';

type QueuedMessage={id:string;input:string;key:string;body?:string;session?:string|null};
function researchPending(workspace:CareerWorkspace){
 return ['research_pending','researching','waiting_quota'].includes(workspace.phase);
}
function reportPending(research:OpportunityView){
 return research.finished===false||['pending','running'].includes(research.status)||Object.values(research.categories).some(category=>category&&['pending','running'].includes(category.status));
}
function responseReady(workspace:CareerWorkspace,research?:OpportunityView){
 return !!workspace.current.goal&&['ready','research_failed'].includes(workspace.phase)&&!!research&&research.career_target_id===workspace.current.goal._id&&research.research_id===workspace.research_id&&research.finished!==false&&['completed','partial','failed'].includes(research.status)&&Object.values(research.categories).every(category=>category&&!['pending','running'].includes(category.status));
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
  const selected=[...category.findings].sort((a,b)=>(ranked.includes(a.finding_id)?ranked.indexOf(a.finding_id):ranked.length)-(ranked.includes(b.finding_id)?ranked.indexOf(b.finding_id):ranked.length));
  sections.push(selected.map(f=>'- '+f.value+(f.scope!=='exact'?' (related context)':'')+' '+sourceCitations(f.source_ids,research.sources||[])).join('\n')||(category.status==='failed'?'No validated findings are available for this category.':'Information pertaining to this category was not found in the retrieved sources.'));
  if(category.status==='failed')sections.push('This category could not finish. Your goal is saved; you can retry research.');
 }
 for(const saved of research.question_research||[]){
  sections.push('### Saved follow-up: '+saved.focus.replaceAll('_',' '));
  sections.push(saved.findings.map(f=>'- '+f.value+' (related or general context) '+sourceCitations(f.source_ids,saved.sources)).join('\n'));
 }
 sections.push('Your career goal and its category cards are saved. Ask about this role, its requirements or the findings, or tell me how you want to refine your goal.');
 return sections.join('\n\n');
}
export function JobReviewChat(){
 const {token}=useProfile(),session=useCareerSession(),router=useRouter();
 const [research,setResearch]=useState<OpportunityView>();
 const [researchRetry,setResearchRetry]=useState(0);
 const [summary,setSummary]=useState<{key:string;reply:string}>();
 const [summaryRetry,setSummaryRetry]=useState(0);
 const [summaryOperation,setSummaryOperation]=useState<CareerOperation|null>(null);
 const summaryReceipt=useRef<{body:string;key:string}|null>(null);
 const [workspace,setWorkspace]=useState<CareerWorkspace>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[code,setCode]=useState('');
 const workspaceRef=useRef<CareerWorkspace|undefined>(undefined);workspaceRef.current=workspace;
 const [reload,setReload]=useState(0),[pendingMessage,setPendingMessage]=useState<string|null>(null);
 const {transcript,followReply,showJump,jumpToLatest,scrollProps}=useChatScroll();
 const [operation,setOperation]=useState<CareerOperation|null>(null);
 const [extractionSteps,setExtractionSteps]=useState<string[]>([]);
 const [connectionIssue,setConnectionIssue]=useState(false);
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
 const [message,setMessage]=useState(''),[turns,setTurns]=useState<{id:string;message:string;reply:string|null;failed?:boolean}[]>([]),[details,setDetails]=useState(false);
 const failedTurn=useRef<string|null>(null);
 const [pendingTurn,setPendingTurn]=useState<string|null>(null);
 const queue=useRef<QueuedMessage[]>([]),failedJobs=useRef(new Map<string,QueuedMessage>());
 const [queueRevision,setQueueRevision]=useState(0);
 const turnsRef=useRef(turns);turnsRef.current=turns;
 const sending=useRef(false);
 const [failedMessage,setFailedMessage]=useState('');
 const controller=useRef<AbortController|null>(null),key=useRef(session.jdKey||crypto.randomUUID()),revision=useRef(''),source=useRef(session.jd),latest=useRef(session);latest.current=session;
 const refining=useRef(typeof window!=='undefined'&&new URLSearchParams(window.location.search).get('refine')==='1');
 const chatCooldown=!!error&&isTokenLimit(code)&&secondsLeft>0;
 const waitLabel=(operation?.limit_scope||workspace?.limit_scope)==='user'?'Waiting for the AI service to resume':'Waiting for the research service to resume';
 const goal=workspace?.current.goal;const researchReady=!!workspace&&responseReady(workspace,research);
 const matchingResearch=!!research&&research.career_target_id===goal?._id&&research.research_id===workspace?.research_id;
 const loadingResearch=!!goal&&!!workspace?.research_id&&(!matchingResearch||!!research&&reportPending(research));
 const summaryKey=JSON.stringify([workspace?.session_id,goal?.version,workspace?.research_id]);
 const ready=researchReady&&summary?.key===summaryKey;
 const activeOperation=pendingTurn?operation:summaryOperation||operation;
 useEffect(()=>{
  if(!token||!researchReady||!workspace?.session_id||!goal||!workspace.research_id)return;
  const abort=new AbortController();setError('');setCode('');
  const body=JSON.stringify({session_id:workspace.session_id,expected_version:goal.version,research_id:workspace.research_id});
  if(summaryReceipt.current?.body!==body)summaryReceipt.current={body,key:crypto.randomUUID()};
  void careerOperation<{reply:string}>('/workspace/summary',token,{method:'POST',signal:abort.signal,headers:{'Idempotency-Key':summaryReceipt.current.key},body},setSummaryOperation)
   .then(value=>{if(!abort.signal.aborted){setSummary({key:summaryKey,reply:value.reply});}})
   .catch(cause=>{if(!abort.signal.aborted&&!sending.current)reportError(cause,'Could not prepare your goal summary.');})
   .finally(()=>{if(!abort.signal.aborted)setSummaryOperation(null);});
  return()=>abort.abort();
 },[token,researchReady,summaryKey,summaryRetry]);
 const detailsReady=!!goal;
 useEffect(()=>{
  if(!token||!goal||!workspace?.research_id)return;const abort=new AbortController();
  let timer:ReturnType<typeof setTimeout>;setError('');setCode('');
  async function load(){try{
   const value=await retryCareerRead(()=>careerApi<OpportunityView>(`/goals/${goal!._id}/opportunity-research?research_id=${workspace!.research_id}`,token!,{signal:abort.signal}),abort.signal,()=>setConnectionIssue(true));
   if(abort.signal.aborted)return;setConnectionIssue(false);setResearch(value);
   // A versioned report can be an early snapshot with pending categories even
   // when that snapshot itself is marked finished. Keep reading until usable.
   if(reportPending(value))timer=setTimeout(()=>void load(),2000);
  }catch(c){if(!abort.signal.aborted){setConnectionIssue(false);reportError(c,'Could not load research.');}}}
  void load();return()=>{abort.abort();clearTimeout(timer);};
 },[token,goal?._id,workspace?.research_id,workspace?.phase,researchRetry]);
 function receive(value:CareerWorkspace,preserveDraft=false){
  const current=workspaceRef.current;
  if(current?.session_id===value.session_id&&(current?.current.goal?.version||0)>(value.current.goal?.version||0))return;
  if(revision.current!==value.session_id){
   if(revision.current){queue.current=[];failedJobs.current.clear();setTurns([]);if(!preserveDraft)setMessage('');setFailedMessage('');failedTurn.current=null;}
   revision.current=value.session_id||'';
  }
  setRetryAt(value.phase==='waiting_quota'?Date.now()+(value.retry_after||60)*1000:null);
  workspaceRef.current=value;setWorkspace(value);
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
  const abort=new AbortController(),timer=setTimeout(()=>{void retryCareerRead(()=>refreshWorkspace(workspace,token,abort.signal),abort.signal,()=>setConnectionIssue(true)).then(v=>{if(!abort.signal.aborted){setConnectionIssue(false);receive(v);}}).catch(c=>{if(!abort.signal.aborted){setConnectionIssue(false);reportError(c,'Could not refresh your career goal.');}});},workspace.phase==='waiting_quota'?Math.max(2000,Math.min(workspace.retry_after||60,3600)*1000):2000);
  return()=>{clearTimeout(timer);abort.abort();};
 },[token,workspace]);
 useEffect(()=>()=>controller.current?.abort(),[]);
 const dirty=useRef(false);dirty.current=!!message||queue.current.length>0;
 useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(dirty.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
 async function retry(){if(!token||busy||secondsLeft>0)return;setBusy(true);setError('');setCode('');try{receive(await careerApi<CareerWorkspace>('/workspace/retry',token,{method:'POST'}));}catch(c){reportError(c,'Retry failed.');}finally{setBusy(false);}}
 function send(text=message,retryId?:string){
  if(!token||!text.trim())return;
  const input=text.trim();
  const previous=retryId?failedJobs.current.get(retryId):failedMessage===input&&failedTurn.current?failedJobs.current.get(failedTurn.current):undefined;
  const job=previous||{id:crypto.randomUUID(),input,key:crypto.randomUUID(),session:workspace?.session_id};
  if(queue.current.some(item=>item.id===job.id)||pendingTurn===job.id)return;
  queue.current.push(job);failedJobs.current.delete(job.id);
  setTurns(current=>current.some(turn=>turn.id===job.id)?current.map(turn=>turn.id===job.id?{...turn,failed:false}:turn):[...current,{id:job.id,message:input,reply:null}]);
  setMessage(current=>current.trim()===input?'':current);
  setQueueRevision(value=>value+1);
 }
 useEffect(()=>{
  if(!token||busy||sending.current||chatCooldown||!workspace?.session_id||!goal||source.current||workspace.phase==='expired'||!queue.current.length)return;
  const job=queue.current.shift()!;
  if(job.session&&job.session!==workspace.session_id){setQueueRevision(value=>value+1);return;}
  job.session=workspace.session_id;
  const abort=new AbortController();sending.current=true;controller.current=abort;
  setPendingTurn(job.id);setPendingMessage(job.input);setBusy(true);setError('');setCode('');setFailedMessage('');
  // Build queued turns only when dispatched, after any preceding edit/reply.
  job.body??=JSON.stringify({session_id:workspace.session_id,expected_version:goal.version,message:job.input,mode:refining.current?'refine':'question',conversation:turnsRef.current.filter(turn=>turn.reply!==null).slice(-1).flatMap(turn=>[{role:'user',content:turn.message},{role:'assistant',content:turn.reply}])});
  void careerOperation<{reply:string;workspace?:CareerWorkspace;edit_status?:string}>('/workspace/messages',token,{method:'POST',signal:abort.signal,headers:{'Idempotency-Key':job.key},body:job.body},operationProgress)
   .then(result=>{if(!abort.signal.aborted){if(result.workspace)receive(result.workspace,true);setResearchRetry(value=>value+1);setTurns(current=>current.map(turn=>turn.id===job.id?{...turn,reply:result.reply,failed:false}:turn));setRetryAt(null);failedJobs.current.delete(job.id);failedTurn.current=null;}})
   .catch(cause=>{if(!abort.signal.aborted){failedJobs.current.set(job.id,job);failedTurn.current=job.id;setFailedMessage(job.input);setTurns(current=>current.map(turn=>turn.id===job.id?{...turn,failed:true}:turn));setMessage(current=>current||job.input);reportError(cause,'Could not answer. Your message is retained.');}})
   .finally(()=>{sending.current=false;if(!abort.signal.aborted){setBusy(false);setPendingMessage(null);setPendingTurn(null);setOperation(null);setQueueRevision(value=>value+1);}});
 },[token,workspace,busy,queueRevision,chatCooldown]);
 return <section className="page on career-agent-page">
  <header className="agent-page-header"><div><p className="small">Your direction, one conversation</p><h1>Career Goal</h1></div><button className="btn ghost sm" disabled={busy} onClick={()=>{if(!dirty.current||window.confirm('Leave and discard unsent edits? Your saved goal stays current.'))router.push('/career-goal');}}>← Career Goal</button></header>
  <div className="agent-workspace"><div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true"><BrandLogo compact decorative/></span><div><strong>elo agent</strong><p className="small">{goal?.role||'Understanding your career goal'}</p></div></div><button className="btn ghost sm" disabled={!detailsReady} onClick={()=>setDetails(v=>!v)}>{details?'Hide details':'Role and research details'}</button></div>
   {workspace?.phase==='empty'&&<p role="status">No job description is available. Import a JD from Career Goal or explore a direction.</p>}
   {details&&detailsReady&&goal&&<aside className="agent-details"><h2>{goal.role}</h2><p>{goal.company||'General career direction'} · v{goal.version} · Saved automatically</p>
    <h3>Main job skills</h3><ul>{goal.skills.map((s,i)=><li key={s.item_id||i}>{s.name} · {s.priority}</li>)}</ul>
    {!!goal.job_dates?.length&&<><h3>Job dates</h3><ul>{goal.job_dates.map((date,index)=><li key={index}>{date.kind.replaceAll('_',' ')}: {date.text}</li>)}</ul></>}
    {researchReady?<AgentMarkdown>{researchSummary(research,workspace?.coverage)}</AgentMarkdown>:<p className="small">Research is incomplete. Your saved goal details remain available.</p>}
   </aside>}

   <div ref={transcript} className="agent-transcript" {...scrollProps} role="log" aria-label="Career agent conversation" aria-live="polite">
    {connectionIssue&&<p role="status" className="small">Connection interrupted. Reconnecting to task updates…</p>}
    {!ready&&<AgentProgress steps={[...extractionSteps,...(activeOperation?.activities||[]),...(workspace?.activities||[])]}/>}
    <div className="agent-message assistant" key="initial-answer"><span className="agent-message-label">elo</span>
     {ready&&<AgentReply onProgress={followReply}>{refining.current?'What would you like to refine in your career goal? We can work through your role, location, skills, qualifications or responsibilities. Tell me what feels different, and I’ll ask for any details needed before saving the update.':summary!.reply}</AgentReply>}{<>
      {(!workspace||researchPending(workspace)||loadingResearch||researchReady&&!ready)&&!error&&<AgentActivity step
       label={activeOperation?.status==='waiting_quota'||workspace?.phase==='waiting_quota'?waitLabel:activeOperation?.status==='repairing'?'Refining the response…':activeOperation?observedActivity(activeOperation.activities)||(source.current?'Extracting your career goal…':'Preparing your career-goal summary…'):researchReady&&!ready?'Preparing your career-goal summary…':workspace&&researchPending(workspace)?observedActivity(workspace?.activities)||'Researching interview expectations…':loadingResearch?'Loading your saved research…':source.current?'Extracting your career goal…':'Opening your career goal…'}
       detail={activeOperation?.status==='waiting_quota'||workspace?.phase==='waiting_quota'?(secondsLeft>0?`Resuming in ${secondsLeft} seconds.`:'Retrying research…'):researchReady?'Your goal and research are saved. I’m preparing your summary.':workspace?.current.goal?'Your goal is saved. You can ask questions while research continues.':undefined}/>}
      {!researchReady&&workspace?.error&&(workspace.phase==='waiting_quota'||isTokenLimit(workspace.error_code))&&<p role="alert" className="small">{workspace.phase==='waiting_quota'?'Research is waiting for the service quota to reset. Your career goal remains saved.':workspace.error}</p>}
      {workspace&&!loadingResearch&&(matchingResearch&&research?.status==='failed'||!researchReady&&(['research_failed','expired'].includes(workspace.phase)||workspace.phase==='ready'&&!workspace.research_id))&&<button className="btn pri" disabled={busy} onClick={()=>void retry()}>Resume research</button>}
     </>}
    </div>
    {ready&&workspace?.edit_question&&!turns.length&&!pendingMessage&&<div className="agent-message assistant"><span className="agent-message-label">elo</span><AgentReply onProgress={followReply}>{workspace.edit_question}</AgentReply></div>}
    {turns.map((turn,i)=><div className="agent-exchange" key={turn.id}><div className="agent-message user"><span className="agent-message-label">You</span><p>{turn.message}</p></div>{turn.reply!==null?<div className="agent-message assistant"><span className="agent-message-label">elo</span><AgentReply animate={i===turns.length-1} onProgress={followReply}>{turn.reply}</AgentReply></div>:turn.id===pendingTurn?<div className="agent-message assistant"><span className="agent-message-label">elo</span><AgentProgress steps={activeOperation?.activities||[]}/><AgentActivity step label={activeOperation?.status==='waiting_quota'?waitLabel:activeOperation?.status==='repairing'?'Refining the response…':observedActivity(activeOperation?.activities)||'Preparing your answer…'} detail={activeOperation?.status==='waiting_quota'?`Resuming automatically in ${secondsLeft} seconds.`:'Using your career goal and saved interview research.'}/></div>:turn.failed?<p className="small">Message failed. <button type="button" className="btn ghost sm" onClick={()=>send(turn.message,turn.id)}>Retry message</button></p>:<p role="status" className="small">Message queued…</p>}</div>)}
    {error&&<AgentRecovery message={error} code={code} seconds={retryAt?secondsLeft:undefined} disabled={busy||chatCooldown} onRetry={()=>{if(source.current)setReload(v=>v+1);else if(failedMessage)void send(failedMessage);else if(goal&&message.trim())void send();else if(researchReady&&!ready)setSummaryRetry(v=>v+1);else if(loadingResearch)setResearchRetry(v=>v+1);else void retry();}}/>}
   </div>
   <ChatScrollControl visible={showJump} onClick={jumpToLatest}/>
   <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}><div className="agent-compose-row"><textarea aria-label="Message elo" placeholder="Ask a question or describe a change to your career goal…" value={message} maxLength={600} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={!token||!message.trim()}>↑</button></div><p className="small">Enter to send · Shift+Enter for a new line</p></form>
  </div>
 </section>;
}

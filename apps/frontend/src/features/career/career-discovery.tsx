"use client";
import { BrandLogo } from '@/components/ui/brand-logo';
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {useSearchParams} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type CurrentGoal,type SavedReview,type ResearchSource} from '@/lib/api/career';
import {AgentActivity,AgentMarkdown,AgentReply} from './agent-message';
import {ChatScrollControl,useChatScroll} from './use-chat-scroll';
import { ChatSkeleton } from '@/components/ui/workspace-ui';

type Scope={field:string;area:string;specificity:'field'|'role_area'|'specialisation';career_stage:'internship'|'entry_level'|'experienced'|'unspecified';location:string|null};
type DiscoveryAnswer={status:'unanswered'|'known'|'unsure'|'skipped';value:string|null;evidence:string|null};
type Understanding=Record<'field'|'role_family_or_work'|'interest'|'other_interests'|'career_stage'|'location'|'avoided_activities'|'work_preferences'|'skill_ambiguity',DiscoveryAnswer>;
type Decision={understanding?:Understanding;action:string;scope:Scope|null;question:string|null;reply:string;recommendations:{area:string;explanation:string;typical_work:string;difference:string}[]};
type Summary={skills:{name:string;requirement_type:string;learning_priority:string;relevance:string;skill_refs:number[]}[];specialisations:string[];question:string|null};
type Session={messages?:{role:'user'|'assistant';content:string}[];summary?:Summary|null;id:string;version:number;status:string;stage:string|null;decision:Decision|null;scope:Scope|null;related_roles:string[];sources:ResearchSource[];stats:{name:string;requirement_type:string;mention_count:number;sample_size:number;source_ids:string[]}[];warnings:string[];listings_analysed:number;employers_analysed:number;coverage:string|null;error_code:string|null;limit_scope:string|null;provider:string|null;retry_after:number|null;review:SavedReview|null};
type View={available:boolean;session:Session|null;introduction?:string};
const phases:Record<string,string>={plan_research:'Planning job-listing searches',search_job_listings:'Finding relevant job listings',assess_job_listings:'Checking listing relevance and employer coverage',extract_requirements:'Extracting supported requirements',aggregate_requirements:'Comparing requirements across listings',generate_career_target:'Preparing your target for review'};
export function CareerDiscovery(){
 const {token}=useProfile();
 return <DiscoveryConversation key={token||''} token={token}/>;
}
function DiscoveryConversation({token}:{token:string|undefined}){
 const params=useSearchParams();
 const requestedSession=params.get('session');
 const [sessions,setSessions]=useState<{id:string;title:string;last_message:string}[]>([]),[historyOpen,setHistoryOpen]=useState(false);
 useEffect(()=>{if(!token||!historyOpen)return;const abort=new AbortController();void careerApi<{items:typeof sessions}>('/discoveries',token,{signal:abort.signal}).then(value=>{if(!abort.signal.aborted)setSessions(value.items);}).catch(()=>{});return()=>abort.abort();},[token,historyOpen]);
 async function openHistory(id:string){if(!token)return;try{receive(await careerApi<View>(`/discoveries/${id}`,token));setHistoryOpen(false);}catch{setError('This conversation could not be loaded. Try again.');}}
 async function publishDirection(){if(!token||!view?.session)return;setBusy(true);setError('');try{const current=await careerApi<CurrentGoal>('/goals/current',token);const next=await post<View>(`/discoveries/${view.session.id}/publish`,{expected_version:view.session.version,expected_selection_version:current.selection_version});receive(next);}catch{setError('Your goal or discovery changed. Reload before trying again.');}finally{setBusy(false);}}

 const [introduction,setIntroduction]=useState('');
 const [view,setView]=useState<View>(),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[reload,setReload]=useState(0);
 const [pending,setPending]=useState(''),[failedMessage,setFailedMessage]=useState(''),[details,setDetails]=useState(false);
 const {transcript,followReply,showJump,jumpToLatest,scrollProps}=useChatScroll();
 const restored=useRef<{id:string;count:number;reply:string|null}|null>(null);
 const generation=useRef(0);
 const sending=useRef(false),currentView=useRef<View|undefined>(undefined);
 const [seconds,setSeconds]=useState(0);
 const receipt=useRef<{signature:string;key:string}|null>(null);const active=useRef(true);const session=view?.session;
 function receive(value:View,restore=false){
  if(value.session&&currentView.current?.session?.id===value.session.id&&value.session.version<currentView.current.session.version)return;
  if(restore){
   restored.current=value.session?{id:value.session.id,count:value.session.messages?.length||0,reply:JSON.stringify(value.session.decision)}:null;
   setIntroduction(value.introduction||'');
  }else if(value.introduction)setIntroduction(value.introduction);
  currentView.current=value;setSeconds(value.session?.retry_after||0);setView(value);
 }
 useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
 useEffect(()=>{if(!token)return;const abort=new AbortController();const requestGeneration=generation.current;const id=currentView.current?.session?.id;void careerApi<View>(id?`/discoveries/${id}`:requestedSession?`/discoveries/${requestedSession}`:'/discoveries/current',token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted&&requestGeneration===generation.current){receive(v,true);setError('');}}).catch(()=>{if(!abort.signal.aborted&&requestGeneration===generation.current)setError('Could not load your discovery. Retry to recover saved progress.');});return()=>abort.abort();},[token,reload]);
 useEffect(()=>{if(!token||!session||busy||!['researching','waiting'].includes(session.status))return;const abort=new AbortController();const timer=setTimeout(()=>{void careerApi<View>(`/discoveries/${session.id}`,token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted)receive(v);}).catch(()=>{if(!abort.signal.aborted)setError('Connection interrupted. Saved research can resume when you reload.');});},2000);return()=>{clearTimeout(timer);abort.abort();};},[token,session,busy]);
 useEffect(()=>{setSeconds(session?.retry_after||0);const timer=setInterval(()=>setSeconds(v=>Math.max(0,v-1)),1000);return()=>clearInterval(timer);},[session?.retry_after]);
 async function post<T>(path:string,body:unknown,method='POST'){
  const signature=path+JSON.stringify(body);if(receipt.current?.signature!==signature)receipt.current={signature,key:crypto.randomUUID()};
  return careerApi<T>(path,token!,{method,headers:{'Idempotency-Key':receipt.current.key},body:JSON.stringify(body)});
 }
 async function send(text=message,retry=false){
  const input=text.trim();
  if(!token||!view?.available||!input||sending.current||busy)return;
  sending.current=true;setBusy(true);setError('');setPending(input);setFailedMessage('');
  // Clear immediately; leave the composer editable while the response is pending.
  if(!retry)setMessage('');
  try{let current=currentView.current?.session;
   if(!current){const started=await post<View>('/discoveries',{consent:true});current=started.session;receive(started);}
   const result=await post<View>(`/discoveries/${current!.id}/messages`,{expected_version:current!.version,message:input});
   if(active.current){receive(result);receipt.current=null;}
  }catch(c){if(active.current){setFailedMessage(input);setError(c instanceof Error?c.message:'Your message could not be completed. Retry.');}}
  finally{sending.current=false;if(active.current){setBusy(false);setPending('');}}
 }
 async function newChat(){
  if(!token||!view||busy||sending.current)return;
  generation.current++;sending.current=true;setBusy(true);setError('');
  try{
   const value=await post<View>('/discoveries',{consent:true});
   if(!active.current)return;
   receipt.current=null;
   setMessage('');setPending('');setFailedMessage('');
   setDetails(false);setSeconds(0);receive(value,true);
  }catch(c){if(active.current)setError(c instanceof Error?c.message:'A new chat could not be started. Try New chat again.');}
  finally{sending.current=false;if(active.current)setBusy(false);}
 }
 async function research(refresh=false){
  if(!session?.decision?.scope||!token||busy)return;setBusy(true);setError('');
  try{const value=await post<View>(`/discoveries/${session.id}/research`,{expected_version:session.version,scope:session.decision.scope,confirmed:true,refresh});if(active.current)receive(value);}
  catch(c){if(active.current)setError(c instanceof Error?c.message:'Research could not start.');}finally{if(active.current)setBusy(false);}
 }
 const working=!!session&&['researching','waiting'].includes(session.status);
 return <section className="page on career-agent-page career-discovery-page">
  <header className="agent-page-header"><div><p className="small">A career direction, grounded in real jobs</p><h1>Career discovery</h1></div><div className="agent-compose-meta"><button type="button" className="btn ghost sm" onClick={()=>setHistoryOpen(value=>!value)}>Previous sessions</button><button type="button" className="btn ghost sm" disabled={busy||!view} onClick={()=>void newChat()}>New chat</button><Link className="btn ghost sm" href="/career-goal">← Career Goal</Link></div></header>
  {historyOpen&&<aside className="card pad" aria-label="Previous discovery sessions"><h2>Previous sessions</h2>{sessions.length?sessions.map(item=><button type="button" className="btn ghost" key={item.id} onClick={()=>void openHistory(item.id)}>{item.title}</button>):<p>No previous sessions are available.</p>}</aside>}
  {session?.stage==='awaiting_goal_confirmation'&&<section className="notice"><h2>Replace your current goal?</h2><p>This direction is saved. Making it your Career Goal will replace the current goal.</p><button className="btn pri" disabled={busy} onClick={()=>void publishDirection()}>Replace current goal</button></section>}
  <div className="agent-workspace">
   <div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true"><BrandLogo compact decorative/></span><div><strong>elo agent</strong><p className="small">{session?.scope?.area||'Career discovery'}</p></div></div><button className="btn ghost sm" onClick={()=>setDetails(v=>!v)}>{details?'Hide details':'Conversation details'}</button></div>
   {details&&<aside className="agent-details"><p>{session?.scope?`${session.scope.area} · ${session.scope.career_stage.replaceAll('_',' ')} · ${session.scope.location||'Location unspecified'}`:'Your direction is taking shape.'}</p><p>No CV or skills assessment is required. Research uses representative listings across employers. Completed guidance stays saved here. You confirm before it replaces an existing Career Goal.</p>{!!session?.related_roles.length&&<p>Roles considered: {session.related_roles.join(' · ')}</p>}</aside>}
   <div className="agent-transcript" ref={transcript} {...scrollProps} role="log" aria-label="Career agent conversation" aria-live="polite">
    {introduction&&<div className="agent-message assistant"><span className="agent-message-label">elo</span><AgentMarkdown>{introduction}</AgentMarkdown></div>}
    {!view&&<ChatSkeleton label="Opening career discovery…"/>}
    {view&&!view.available&&<p role="alert">Discovery needs the configured Gemini and Brave services. Saved progress remains available.</p>}
    {session?.messages?.map((turn,index)=><div className={`agent-message ${turn.role==='user'?'user':'assistant'}`} key={`${session.id}-${index}`}><span className="agent-message-label">{turn.role==='user'?'You':'elo'}</span>{turn.role==='user'?<p>{turn.content}</p>:<AgentReply animate={restored.current?.id!==session.id||index>=restored.current.count} onProgress={followReply}>{turn.content}</AgentReply>}</div>)}
    {!session?.messages?.length&&session?.decision&&<div className="agent-message assistant"><span className="agent-message-label">elo</span><AgentReply animate={restored.current?.id!==session.id||restored.current.reply!==JSON.stringify(session.decision)} onProgress={followReply}>{[session.decision.reply,session.decision.question].filter(Boolean).join("\n\n")}</AgentReply></div>}
    {pending&&<div className="agent-message user"><span className="agent-message-label">You</span><p>{pending}</p></div>}
    {busy&&pending&&<div className="agent-message assistant"><AgentActivity label="Considering your message…"/></div>}
    {session?.decision?.recommendations.map(option=><article className="agent-message assistant" key={option.area}><h2>{option.area}</h2><p>{option.explanation}</p><p>{option.typical_work}</p><p className="small">{option.difference}</p><button className="btn ghost" disabled={busy} onClick={()=>void send(`I want to explore ${option.area}.`)}>Choose {option.area}</button></article>)}
    {working&&<AgentActivity label={session?.status==='waiting'?(session.limit_scope==='user'?'Waiting for the AI service to resume':`${session.provider||'Research provider'} is rate limiting requests`):phases[session!.stage||'']||'Researching your career area'} detail={session?.status==='waiting'?`Resuming in ${seconds} seconds. You can keep chatting.`:`${session?.sources.length||0} source excerpts retrieved. You can keep chatting, or leave and return.`}/>}
    {session?.status==='failed'&&<div role="alert"><p>Research could not finish. Completed evidence is retained.</p><button className="btn ghost" disabled={busy} onClick={()=>void research()}>Retry research</button></div>}
    {error&&<div role="alert" className="goal-error"><p>{error}</p>{failedMessage&&<><p>Message not sent: {failedMessage}</p><button className="btn ghost sm" disabled={busy} onClick={()=>void send(failedMessage,true)}>Retry message</button></>}<button className="btn ghost sm" disabled={busy} onClick={()=>setReload(v=>v+1)}>Reload saved progress</button></div>}
   </div>
   <ChatScrollControl visible={showJump} onClick={jumpToLatest}/>
   <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}>
    <div className="agent-compose-row"><textarea id="discovery-message" aria-label="Message elo" rows={2} maxLength={600} placeholder="Share your interests, ask a question or refine your direction…" value={message} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={busy||!message.trim()||!view?.available}>↑</button></div>
    <p className="small">Enter to send · Shift+Enter for a new line</p>
   </form>
  </div>
 </section>;
}

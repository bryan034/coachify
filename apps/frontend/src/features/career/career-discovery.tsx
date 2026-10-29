"use client";
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type SavedReview,type JDExtraction,type CurrentGoal,type ResearchSource} from '@/lib/api/career';
import {AgentActivity,AgentMarkdown} from './agent-message';
import {ChatScrollControl,useChatScroll} from './use-chat-scroll';

type Scope={field:string;area:string;specificity:'field'|'role_area'|'specialisation';career_stage:'internship'|'entry_level'|'experienced'|'unspecified';location:string|null};
type Decision={action:string;scope:Scope|null;question:string|null;reply:string;recommendations:{area:string;explanation:string;typical_work:string;difference:string}[]};
function goalContent(goal:import('@/lib/api/career').SavedGoal):JDExtraction{return {role:goal.role,field:goal.field,company:goal.company,location:goal.location,seniority_level:goal.seniority_level,job_url:goal.job_url,employment_type:goal.employment_type,summary:goal.summary||null,responsibilities:goal.responsibilities||[],skills:goal.skills,non_skill_requirements:goal.non_skill_requirements||[]};}
type Summary={skills:{name:string;requirement_type:string;learning_priority:string;relevance:string;skill_refs:number[]}[];specialisations:string[];question:string|null};
type Session={messages?:{role:'user'|'assistant';content:string}[];summary?:Summary|null;id:string;version:number;status:string;stage:string|null;decision:Decision|null;scope:Scope|null;related_roles:string[];sources:ResearchSource[];stats:{name:string;requirement_type:string;mention_count:number;sample_size:number;source_ids:string[]}[];warnings:string[];listings_analysed:number;employers_analysed:number;coverage:string|null;error_code:string|null;limit_scope:string|null;provider:string|null;retry_after:number|null;review:SavedReview|null};
type View={available:boolean;session:Session|null};
const phases:Record<string,string>={plan_research:'Planning job-listing searches',search_job_listings:'Finding relevant job listings',extract_requirements:'Extracting supported requirements',aggregate_requirements:'Comparing requirements across listings',generate_career_target:'Preparing your target for review'};
export function CareerDiscovery(){
 const {token}=useProfile(),router=useRouter();
 const [view,setView]=useState<View>(),[message,setMessage]=useState(''),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[reload,setReload]=useState(0);
 const [pending,setPending]=useState(''),[failedMessage,setFailedMessage]=useState(''),[details,setDetails]=useState(false);
 const {transcript,showJump,jumpToLatest,scrollProps}=useChatScroll();
 const sending=useRef(false),currentView=useRef<View|undefined>(undefined);
 const [content,setContent]=useState<JDExtraction>(),[seconds,setSeconds]=useState(0),[acknowledge,setAcknowledge]=useState(false);
 const receipt=useRef<{signature:string;key:string}|null>(null);const active=useRef(true);const revision=useRef('');const session=view?.session;
 function receive(value:View){if(value.session&&currentView.current?.session?.id===value.session.id&&value.session.version<currentView.current.session.version)return;currentView.current=value;setSeconds(value.session?.retry_after||0);setView(value);const key=value.session?.review?`${value.session.review.current.goal._id}:${value.session.review.current.goal.version}`:'';if(key!==revision.current){revision.current=key;setContent(value.session?.review?goalContent(value.session.review.current.goal):undefined);setAcknowledge(false);}}
 useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
 useEffect(()=>{if(!token)return;const abort=new AbortController();void careerApi<View>('/discoveries/current',token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted){receive(v);setError('');}}).catch(()=>{if(!abort.signal.aborted)setError('Could not load your discovery. Retry to recover saved progress.');});return()=>abort.abort();},[token,reload]);
 useEffect(()=>{if(!token||!session||busy||!['researching','waiting'].includes(session.status))return;const abort=new AbortController();const timer=setTimeout(()=>{void careerApi<View>(`/discoveries/${session.id}`,token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted)receive(v);}).catch(()=>{if(!abort.signal.aborted)setError('Connection interrupted. Saved research can resume when you reload.');});},2000);return()=>{clearTimeout(timer);abort.abort();};},[token,session,busy]);
 useEffect(()=>{setSeconds(session?.retry_after||0);const timer=setInterval(()=>setSeconds(v=>Math.max(0,v-1)),1000);return()=>clearInterval(timer);},[session?.retry_after]);
 async function post<T>(path:string,body:unknown,method='POST'){
  const signature=path+JSON.stringify(body);if(receipt.current?.signature!==signature)receipt.current={signature,key:crypto.randomUUID()};
  return careerApi<T>(path,token!,{method,headers:{'Idempotency-Key':receipt.current.key},body:JSON.stringify(body)});
 }
 async function send(text=message,retry=false){
  const input=text.trim();
  if(!token||!input||!consent||sending.current||busy)return;
  sending.current=true;setBusy(true);setError('');setPending(input);setFailedMessage('');
  // Clear immediately; leave the composer editable while the response is pending.
  if(!retry)setMessage('');
  try{let current=currentView.current?.session;
   if(!current||current.status==='confirmed'){const started=await post<View>('/discoveries',{consent:true});current=started.session;receive(started);}
   const result=await post<View>(`/discoveries/${current!.id}/messages`,{expected_version:current!.version,message:input});
   if(active.current){receive(result);receipt.current=null;}
  }catch(c){if(active.current){setFailedMessage(input);setError(c instanceof Error?c.message:'Your message could not be completed. Retry.');}}
  finally{sending.current=false;if(active.current){setBusy(false);setPending('');}}
 }
 async function research(refresh=false){
  if(!session?.decision?.scope||!token||busy)return;setBusy(true);setError('');
  try{const value=await post<View>(`/discoveries/${session.id}/research`,{expected_version:session.version,scope:session.decision.scope,confirmed:true,refresh});if(active.current)receive(value);}
  catch(c){if(active.current)setError(c instanceof Error?c.message:'Research could not start.');}finally{if(active.current)setBusy(false);}
 }
 async function confirm(){
  if(!session?.review||!content||!token||!acknowledge||busy)return;setBusy(true);setError('');
  try{
   let review=session.review;
   if(JSON.stringify(content)!==JSON.stringify(goalContent(review.current.goal)))review=await post<SavedReview>(`/goals/${review.current.goal._id}/review`,{expected_version:review.current.goal.version,content,acknowledge_context:true},'PATCH');
   // Keep the saved review version on a retry if final confirmation fails.
   receive({...view!,session:{...session,review}});
   const current=await careerApi<CurrentGoal>('/goals/current',token);
   await post<CurrentGoal>('/goals/confirm',{expected_selection_version:current.selection_version,target_type:'career_exploration',review_id:review.current.goal._id,expected_review_version:review.current.goal.version,
    role:review.current.goal.role,field:review.current.goal.field,company:null,job_url:null,location:review.current.goal.location,seniority_level:review.current.goal.seniority_level,employment_type:review.current.goal.employment_type||'unknown',replace_current:true});
   router.push('/career-goal');
  }catch(c){if(active.current)setError(c instanceof Error?c.message:'Your target could not be saved.');}finally{if(active.current)setBusy(false);}
 }
 const working=!!session&&['researching','waiting'].includes(session.status);
 const review=session?.review;
 return <section className="page on career-agent-page career-discovery-page">
  <header className="agent-page-header"><div><p className="small">A career direction, grounded in real jobs</p><h1>Career discovery</h1></div><Link className="btn ghost sm" href="/career-goal">← Career Goal</Link></header>
  <div className="agent-workspace">
   <div className="agent-chat-top"><div className="agent-identity"><span className="agent-avatar" aria-hidden="true">C</span><div><strong>Coachify agent</strong><p className="small">{session?.scope?.area||'Career discovery'}</p></div></div><button className="btn ghost sm" onClick={()=>setDetails(v=>!v)}>{details?'Hide details':'Conversation details'}</button></div>
   {details&&<aside className="agent-details"><p>{session?.scope?`${session.scope.area} · ${session.scope.career_stage.replaceAll('_',' ')} · ${session.scope.location||'Location unspecified'}`:'Your direction is taking shape.'}</p><p>No CV or skills assessment is required. Research uses representative listings across employers. You choose when to confirm and save.</p>{!!session?.related_roles.length&&<p>Roles considered: {session.related_roles.join(' · ')}</p>}</aside>}
   <div className="agent-transcript" ref={transcript} {...scrollProps} role="log" aria-label="Career agent conversation" aria-live="polite">
    <div className="agent-message assistant"><span className="agent-message-label">Coachify</span><p>What kind of work interests you, or is there a career direction you already have in mind? You can keep it broad. No CV is needed.</p></div>
    {!view&&<p role="status">Opening your saved discovery…</p>}
    {view&&!view.available&&<p role="alert">Discovery needs the configured Gemini and Brave services. Saved progress remains available.</p>}
    {session?.messages?.map((turn,index)=><div className={`agent-message ${turn.role==='user'?'user':'assistant'}`} key={`${session.id}-${index}`}><span className="agent-message-label">{turn.role==='user'?'You':'Coachify'}</span>{turn.role==='user'?<p>{turn.content}</p>:<AgentMarkdown>{turn.content}</AgentMarkdown>}</div>)}
    {!session?.messages?.length&&session?.decision&&<div className="agent-message assistant"><span className="agent-message-label">Coachify</span><AgentMarkdown>{session.decision.reply}</AgentMarkdown>{session.decision.question&&<p>{session.decision.question}</p>}</div>}
    {pending&&<div className="agent-message user"><span className="agent-message-label">You</span><p>{pending}</p></div>}
    {busy&&pending&&<div className="agent-message assistant"><AgentActivity label="Considering your message…"/></div>}
    {session?.decision?.recommendations.map(option=><article className="agent-message assistant" key={option.area}><h2>{option.area}</h2><p>{option.explanation}</p><p>{option.typical_work}</p><p className="small">{option.difference}</p><button className="btn ghost" disabled={busy||!consent} onClick={()=>void send(`I want to explore ${option.area}.`)}>Choose {option.area}</button></article>)}
    {working&&<AgentActivity label={session?.status==='waiting'?(session.limit_scope==='user'?'Waiting for the AI service to resume':`${session.provider||'Research provider'} is rate limiting requests`):phases[session!.stage||'']||'Researching your career area'} detail={session?.status==='waiting'?`Resuming in ${seconds} seconds. You can keep chatting.`:`${session?.sources.length||0} source excerpts retrieved. You can keep chatting, or leave and return.`}/>}
    {session?.status==='failed'&&<div role="alert"><p>Research could not finish. Completed evidence is retained.</p><button className="btn ghost" disabled={busy} onClick={()=>void research()}>Retry research</button></div>}
    {error&&<div role="alert" className="goal-error"><p>{error}</p>{failedMessage&&<><p>Message not sent: {failedMessage}</p><button className="btn ghost sm" disabled={busy} onClick={()=>void send(failedMessage,true)}>Retry message</button></>}<button className="btn ghost sm" disabled={busy} onClick={()=>setReload(v=>v+1)}>Reload saved progress</button></div>}
   </div>
   <ChatScrollControl visible={showJump} onClick={jumpToLatest}/>
   <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}>
    <label className="agent-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>Allow Coachify to send this career conversation to the configured AI provider and automatically research public job listings.</label>
    <div className="agent-compose-row"><textarea id="discovery-message" aria-label="Message Coachify" rows={2} maxLength={600} placeholder="Share your interests, ask a question or refine your direction…" value={message} onChange={e=>setMessage(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/><button className="btn pri" aria-label="Send message" disabled={busy||!consent||!message.trim()||!view?.available}>↑</button></div>
    <p className="small">Enter to send · Shift+Enter for a new line</p>
   </form>
  </div>
  {review&&content&&!working&&session?.status!=='conversation'&&<div className="card pad"><h2>Review your career target</h2><p>{session?.listings_analysed} listings · {session?.employers_analysed} employers · {session?.coverage} coverage</p>{session?.warnings.map(w=><p className="goal-notice" key={w}>{w}</p>)}
   <label htmlFor="target-title">Career title</label><input id="target-title" maxLength={160} value={content.role||''} onChange={e=>setContent({...content,role:e.target.value})}/>
   <label htmlFor="target-overview">Career overview</label><textarea id="target-overview" maxLength={600} value={content.summary||''} onChange={e=>setContent({...content,summary:e.target.value})}/>
   {['core','specialisation','optional'].map(group=><article className="card pad" key={group}><h3>{group==='core'?'Core skills':group==='specialisation'?'Specialisation-specific skills':'Optional skills'}</h3><ul>{content.skills.filter(skill=>(session?.summary?.skills.find(v=>v.name===skill.name)?.requirement_type||session?.stats.find(v=>v.name===skill.name)?.requirement_type)===group).map(skill=>{const stats=session?.stats.find(v=>v.name===skill.name);return <li key={skill.item_id||skill.name}><strong>{skill.name}</strong> · {skill.origin==='generated_guidance'?'Gemini learning recommendation':skill.origin==='user_declaration'?'User-requested skill':`${stats?.mention_count}/${stats?.sample_size} sampled listings`} <button className="btn ghost sm" onClick={()=>setContent({...content,skills:content.skills.filter(v=>v!==skill)})} aria-label={`Remove ${skill.name}`}>Remove</button>{skill.context&&<p>{skill.context}</p>}{skill.evidence&&<blockquote>{skill.evidence}</blockquote>}{skill.source_urls?.map(url=><a key={url} href={url} target="_blank" rel="noopener noreferrer"> Source </a>)}</li>;})}</ul></article>)}
   <h3>Responsibilities</h3><ul>{content.responsibilities.map((v,i)=><li key={i}>{v}<button className="btn ghost sm" aria-label={`Remove responsibility ${i+1}`} onClick={()=>setContent({...content,responsibilities:content.responsibilities.filter((_,j)=>i!==j)})}>Remove</button></li>)}</ul>
   <h3>Qualifications</h3><ul>{content.non_skill_requirements.map(v=><li key={v.requirement_id}>{v.description}<button className="btn ghost sm" aria-label={`Remove ${v.description}`} onClick={()=>setContent({...content,non_skill_requirements:content.non_skill_requirements.filter(c=>c!==v)})}>Remove</button></li>)}</ul>
   <details><summary>Research sources</summary><ul>{session?.sources.map(source=><li key={source.source_id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.url}</a><p className="small">{source.published_date||'Publication date unknown'}</p></li>)}</ul></details>
   <label><input type="checkbox" checked={acknowledge} onChange={e=>setAcknowledge(e.target.checked)}/>I have reviewed this target and want to use it as my current career goal.</label><div className="row"><button className="btn pri" disabled={busy||!acknowledge||!content.role?.trim()} onClick={()=>void confirm()}>Confirm and save goal</button><button className="btn ghost" disabled={busy} onClick={()=>void research(true)}>Refresh research</button></div>
   <p className="small">After saving, your goal page will offer CV assessment or the next step based on your saved skills profile.</p>
  </div>}
 </section>;
}

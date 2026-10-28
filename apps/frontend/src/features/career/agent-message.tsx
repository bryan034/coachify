"use client";

import Markdown from 'react-markdown';
import {sourceLink} from './source-links';
import {useEffect,useState} from 'react';

/** Model text is Markdown, never executable HTML or remote images. */
export function AgentMarkdown({children}:{children:string}){
 return <div className="agent-markdown"><Markdown skipHtml disallowedElements={['img']} components={{
  a:({href,children})=>{
   const source=href&&sourceLink(href);
   if(source)return <a className="agent-citation" href={source.url} title={source.url} target="_blank" rel="noopener noreferrer">{source.domain}</a>;
   return href&&/^(\/(?!\/)|#)/.test(href)?<a href={href}>{children}</a>:<span>{children}</span>;
  },
 }}>{children}</Markdown></div>;
}

/** Observable work only: no simulated reasoning, timers or invented tool results. */
export function AgentActivity({label,detail}:{label:string;detail?:string}){
 return <div className="agent-activity" role="status" aria-live="polite">
  <div className="agent-activity-heading"><span className="agent-activity-dot" aria-hidden="true"/><span>{label}</span></div>
  {detail&&<p>{detail}</p>}
 </div>;
}

const activities:Record<string,string>={
 understanding_question:'Understanding your question about this goal…',
 searching_question:'Searching public sources for your question…',
 answering_question:'Structuring an answer from the available evidence…',
 identifying_job:'Identifying the job title, employer, location and position…',
 extracting_requirements:'Extracting skills, responsibilities and other requirements…',
 planning_research:'Planning research for this role…',
 searching_progression:'Researching career progression and full-time compensation…',
 searching_conversion:'Looking for historical full-time conversion figures…',
 searching_interviews:'Searching for relevant interview experiences…',
 searching_internship:'Searching for relevant workplace and internship experiences…',
 searching_company:'Looking up company and team culture…',
 checking_sources:'Checking sources against this career goal…',
 saving_goal:'Saving your career goal and its category cards…',
 preparing_summary:'Preparing your career-goal summary…',
 research_complete:'Research is complete. Available findings have been saved.',
};
/** Only known server-observed steps are shown, never model reasoning or tool names. */
export function AgentProgress({steps}:{steps:string[]}){
 const labels=[...new Set(steps)].map(step=>activities[step]).filter(Boolean);
 return labels.length?<div className="agent-progress" role="status" aria-label="Career goal progress"><p className="small">Career goal progress</p><ul>{labels.map(label=><li key={label}>{label}</li>)}</ul></div>:null;
}

export function isTokenLimit(code:unknown){return code==='rate_limited'||code==='input_limit';}
export function errorCode(cause:unknown){return cause&&typeof cause==='object'&&'code' in cause&&typeof cause.code==='string'?cause.code:'';}

/** Technical details stay in API responses; recovery controls never repeat them. */
export function AgentRecovery({message,code,onRetry,disabled=false,label='Retry',seconds}:{message:string;code:string;onRetry:()=>void;disabled?:boolean;label?:string;seconds?:number}){
 const tokenLimit=isTokenLimit(code);
 const conflict=code==='operation_in_progress'||code==='operation_key_reused';
 const unavailable=code==='not_configured';
 const scope=code==='career_scope';
 return <div role={tokenLimit||conflict||unavailable||scope?'alert':undefined} className={tokenLimit?'goal-error':'agent-recovery'}>
  {scope&&<p>Please provide a job description to set your career goal. This assistant cannot process unrelated documents or carry out unrelated tasks.</p>}
  {unavailable&&<p>AI is disabled. Configure the Career service to enable the assistant, then retry.</p>}
  {conflict&&<p>{code==='operation_in_progress'?'Another request is still being processed. Wait for it to finish before submitting different input.':'This request changed after it started. Return to Career Goal and submit the updated description again.'}</p>}
  {tokenLimit&&<p>{seconds!==undefined?message.replace(/ Retry after [\d.]+ seconds\./,''):message}</p>}
  {tokenLimit&&seconds!==undefined&&<p role="status">{seconds>0?`Try again in ${seconds} seconds.`:'You can retry now.'}</p>}
  <p className="small">Your inputs are kept.</p><button className="btn ghost sm" disabled={disabled} onClick={onRetry}>{label}</button>
 </div>;
}

/** Display animation after a validated response arrives; this is not provider streaming. */
export function AgentReply({children,animate=true,onProgress}:{children:string;animate?:boolean;onProgress?:()=>void}){
 const [shown,setShown]=useState({text:children,count:0});
 const [reduced,setReduced]=useState(()=>typeof window!=='undefined'&&!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
 const words=children.match(/\s*\S+/g)||[];
 useEffect(()=>{
  const media=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  if(!media)return;const update=()=>setReduced(media.matches);update();
  media.addEventListener?.('change',update);return()=>media.removeEventListener?.('change',update);
 },[]);
 useEffect(()=>{
  if(!animate||reduced)return;
  setShown({text:children,count:1});
  const timer=setInterval(()=>setShown(current=>{
   const count=current.text===children?current.count+1:1;
   if(count>=words.length)clearInterval(timer);
   return {text:children,count};
  }),20);
  return()=>clearInterval(timer);
 },[children,animate,reduced]);
 const count=shown.text===children?shown.count:0;
 const complete=!animate||reduced||count>=words.length;
 const visible=complete?children:words.slice(0,count).join('');
 useEffect(()=>{onProgress?.();},[visible,onProgress]);
 return <div className="agent-reply" aria-busy={!complete}>
  <AgentMarkdown>{visible}</AgentMarkdown>
  {!complete&&<button type="button" className="agent-reveal" onClick={()=>setShown({text:children,count:words.length})}>Show full response</button>}
 </div>;
}

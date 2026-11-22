"use client";
import {useEffect,useState} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type OpportunityView,type OpportunityAvailabilityIssue,type IntelligenceCategory} from '@/lib/api/career';
import {formatDayMonthYear} from '@/lib/format';
import {EstimatedTag,SectionPanel,Toggle} from './research-brief';
import {InterviewResearch,interviewSources} from './interview-research';
import {RoleResearch,roleCategories,roleSources} from './role-research';
import '@/styles/research-brief.css';

type Section='interview'|'role';
const availabilityMessages:Record<OpportunityAvailabilityIssue,string>={
 research_disabled:'Opportunity research is turned off on the server.',
 reasoning_disabled:'The research reasoning provider is disabled on the server.',
 brave_not_configured:'Web search is not connected to the Career service.',
 model_not_configured:'The configured model is not connected to the Career service.',
 search_not_configured:'The configured search provider is not connected to the Career service.',
 brave_llm_context_required:'The Brave connection needs LLM Context mode for opportunity research.'
};
const VISIBLE_DUTIES=4;
function Duties({duties,id}:{duties:string[];id:string}){
 const [open,setOpen]=useState(false);
 const extra=duties.length-VISIBLE_DUTIES;
 return <>
  <ul className="brief-duties" id={id}>{(open?duties:duties.slice(0,VISIBLE_DUTIES)).map(duty=><li key={duty}>
   <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
   <span>{duty}</span>
  </li>)}</ul>
  {extra>0&&<div><Toggle expanded={open} controls={id} onClick={()=>setOpen(value=>!value)}>{open?'Show fewer':`Show ${extra} more`}</Toggle></div>}
 </>;
}

export type GoalBasics={requirements:string[];duties:string[]};
function GoalOnly({goal}:{goal:GoalBasics}){
 return <>
  {goal.requirements.length>0&&<SectionPanel id="goal-requirements-title" title="Who can apply" description="From your saved goal.">
   <ul className="brief-duties">{goal.requirements.map(item=><li key={item}><span>{item}</span></li>)}</ul>
  </SectionPanel>}
  {goal.duties.length>0&&<SectionPanel id="goal-duties-title" title="What you would do" description="From your saved goal."><Duties id="goal-duties" duties={goal.duties}/></SectionPanel>}
 </>;
}

export function OpportunityIntelligence({goalId,section='interview',goal}:{goalId:string;section?:Section;goal?:GoalBasics}){
 const {token}=useProfile();const [data,setData]=useState<OpportunityView>(),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 const path=`/goals/${goalId}/opportunity-research`;
 useEffect(()=>{
  if(!token)return;const abort=new AbortController();let timer:ReturnType<typeof setTimeout>;
  let loaded=false,stamp:string|null|undefined;
  async function load(){try{
   const progress=await careerApi<{result_version:string|null;finished:boolean}>(path+'/progress',token!,{signal:abort.signal});
   if(!loaded||progress.result_version!==stamp){
    const value=await careerApi<OpportunityView>(path,token!,{signal:abort.signal});if(abort.signal.aborted)return;
    loaded=true;stamp=progress.result_version;setData(value);setError('');
   }
   if(!progress.finished)timer=setTimeout(()=>void load(),2000);
  }catch{if(!abort.signal.aborted)setError('Opportunity research could not be loaded. Your goal and available findings are preserved.');}}
  void load();return()=>{abort.abort();clearTimeout(timer);};
 },[token,path,attempt]);
 const keys:IntelligenceCategory[]=section==='interview'?['interview_intelligence']:[...roleCategories];
 const states=keys.map(key=>data?.categories?.[key]).filter((v):v is NonNullable<typeof v>=>!!v);
 const pending=states.some(v=>['pending','running'].includes(v.status));
 const interview=data?.categories.interview_intelligence;
 const sources=section==='interview'?interviewSources(interview,data?.sources||[]):roleSources(data?.categories||{},data?.sources||[]);
 const notices:string[]=[];
 if(states.some(v=>v.status==='not_applicable'))notices.push('No company is specified, so employer-specific research was skipped.');
 const title=section==='interview'?'Interview preparation':'About the role';
 const sourceCount=sources.length;
 const researchedAt=states.flatMap(state=>state.researched_at?[state.researched_at]:[]).sort((a,b)=>Date.parse(b)-Date.parse(a))[0];
 const estimated=states.some(state=>state.findings.some(finding=>finding.evidence_type==='inferred'));
 return <section className="brief" id={section==='interview'?'interview-preparation':'about-role'} aria-labelledby={`${section}-research-heading`}>
  <h2 id={`${section}-research-heading`} className="brief-sr">{title}</h2>
  <header className="brief-head">
   <div className="brief-head-row">
    <p className="brief-meta" role="note">
     {researchedAt?`Researched ${formatDayMonthYear(researchedAt)} from ${sourceCount} public source${sourceCount===1?'':'s'}. `:'No completed research yet. '}
     AI can get details wrong, so check the sources before relying on them.
     {estimated&&<> Items tagged <EstimatedTag/> are AI suggestions, not from a source.</>}
    </p>
   </div>
  </header>
  {!data&&!error&&<p role="status" className="small">Checking opportunity research…</p>}
  {data&&!data.available&&<div className="notice"><p>Opportunity research is unavailable on this server. Saved findings remain readable.</p>{!!data.availability_issues?.length&&<ul>{data.availability_issues.map(issue=><li key={issue}>{availabilityMessages[issue]}</li>)}</ul>}</div>}
  {error&&<div role="alert" className="notice"><p>{error}</p><button className="btn ghost sm" onClick={()=>setAttempt(v=>v+1)}>Retry loading research</button></div>}
  {pending&&<p role="status" className="notice">{states.some(v=>['rate_limited','source_rate_limited'].includes(v.error_code||''))?`Waiting for the AI allowance${data?.retry_after?`; resuming in about ${data.retry_after} seconds`:''}.`:'Researching…'} Available findings stay visible.</p>}
  {notices.map(notice=><p key={notice} className="notice">{notice}</p>)}
  {section==='interview'&&interview&&<InterviewResearch result={interview} sources={sources} roundTitles={data?.round_titles}/>}
  {section==='role'&&<>{goal&&<GoalOnly goal={goal}/>}<RoleResearch categories={data?.categories||{}} sources={sources}/></>}
 </section>;
}

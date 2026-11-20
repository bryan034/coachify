"use client";
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type BriefView,type InterviewBrief,type RoleBrief,type OpportunityView,type OpportunityAvailabilityIssue,type IntelligenceCategory} from '@/lib/api/career';
import {formatDayMonthYear} from '@/lib/format';
import {Icon} from '@/components/ui/icon';
import {CitationChips,CitationProvider,DifficultyBar,EstimatedTag,EvidenceList,FactStrip,ProcessStepper,QuestionAccordion,SectionPanel,SourceList,SummaryLead,Toggle,TopicCard} from './research-brief';
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
const briefPath={role:'role-research',interview:'interview-research'} as const;
const isBrief=(value:unknown):value is RoleBrief|InterviewBrief=>{
 const brief=value as Partial<RoleBrief&InterviewBrief>|null;
 return !!brief&&typeof brief.summary==='string'&&typeof brief.researchedAt==='string'&&Array.isArray(brief.sources)&&Array.isArray(brief.notFound);
};
const unique=(values:string[])=>[...new Map(values.map(value=>[value.toLowerCase(),value])).values()];

function NotFound({id,items}:{id:string;items:string[]}){
 if(!items.length)return null;
 return <SectionPanel id={id} title="Not found yet" description="Ask current or past interns." dashed>
  <ul className="brief-gaps">{items.map(item=><li key={item}>{item}</li>)}</ul>
 </SectionPanel>;
}

function Sources({id,sources}:{id:string;sources:RoleBrief['sources']}){
 if(!sources.length)return null;
 return <SectionPanel id={id} title="Sources" description="Numbered to match the citations above."><SourceList sources={sources}/></SectionPanel>;
}

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

/** About the role: facts strip, duties, what it is like, pay, gaps and sources. Empty sections are hidden and named under Not found yet. */
export function RoleResearch({brief}:{brief:RoleBrief}){
 const missing=[...(brief.duties.length?[]:['What you would do']),...(brief.topics.length?[]:['What it is like']),...(brief.pay.length?[]:['Pay and what comes after'])];
 return <CitationProvider prefix="role" sources={brief.sources}>
  {brief.facts.length>0&&<FactStrip facts={brief.facts}/>}
  {brief.duties.length>0&&<SectionPanel id="role-duties-title" title="What you would do" description="From the job description."><Duties id="role-duties" duties={brief.duties}/></SectionPanel>}
  {brief.topics.length>0&&<SectionPanel id="role-topics-title" title="What it is like" description="From intern and employee reviews.">
   <div className="brief-cards">{brief.topics.map(topic=><TopicCard key={topic.id} topic={topic}/>)}</div>
  </SectionPanel>}
  {brief.pay.length>0&&<SectionPanel id="role-pay-title" title="Pay and what comes after">
   <div className="brief-pay">{brief.pay.map(item=><div key={item.label} className="brief-card brief-pay-item">
    <span className="brief-pay-label">{item.label}</span>
    <span className="brief-pay-value">{item.value}</span>
    <span className="brief-pay-caveat">{item.caveat}{item.citations.length?<CitationChips citations={item.citations}/>:<EstimatedTag/>}</span>
   </div>)}</div>
  </SectionPanel>}
  <NotFound id="role-gaps-title" items={unique([...brief.notFound,...missing])}/>
  <Sources id="role-sources-title" sources={brief.sources}/>
 </CitationProvider>;
}

function CandidateReports({reports}:{reports:InterviewBrief['candidateReports']}){
 const [open,setOpen]=useState(false),id='interview-reports';
 const count=reports.reports.length;
 return <div className="brief-reports">
  {reports.askedAbout.length>0&&<div className="brief-card">
   <span className="brief-card-label">Asked about</span>
   <ul className="brief-chips">{reports.askedAbout.map(item=><li key={item.label}>{item.label}<CitationChips citations={item.citations}/></li>)}</ul>
  </div>}
  {(reports.situational||reports.tone)&&<div className="brief-pair">
   {reports.situational&&<div className="brief-card"><span className="brief-card-label">Situational example</span><p>{reports.situational.text}<CitationChips citations={reports.situational.citations}/></p></div>}
   {reports.tone&&<div className="brief-card"><span className="brief-card-label">Tone</span><p>{reports.tone.text}<CitationChips citations={reports.tone.citations}/></p></div>}
  </div>}
  {count>0&&<div><Toggle expanded={open} controls={id} onClick={()=>setOpen(value=>!value)}>{open?'Hide reports':`Show all ${count} report${count===1?'':'s'}`}</Toggle></div>}
  {count>0&&<div id={id} hidden={!open}><EvidenceList items={reports.reports}/></div>}
 </div>;
}

export type GoalBasics={requirements:string[];duties:string[]};
/** Before a brief exists (or without research), About the role still shows what the saved goal states. */
function GoalOnly({goal}:{goal:GoalBasics}){
 return <>
  {goal.requirements.length>0&&<SectionPanel id="goal-requirements-title" title="Who can apply" description="From your saved goal.">
   <ul className="brief-duties">{goal.requirements.map(item=><li key={item}><span>{item}</span></li>)}</ul>
  </SectionPanel>}
  {goal.duties.length>0&&<SectionPanel id="goal-duties-title" title="What you would do" description="From your saved goal."><Duties id="goal-duties" duties={goal.duties}/></SectionPanel>}
 </>;
}

/** Interview preparation: process stepper, difficulty, questions with how to prepare, candidate reports, gaps and sources. */
export function InterviewResearch({brief}:{brief:InterviewBrief}){
 const reports=brief.candidateReports;
 const hasReports=reports.askedAbout.length>0||!!reports.situational||!!reports.tone||reports.reports.length>0;
 const allEstimated=brief.questions.length>0&&brief.questions.every(question=>question.estimated);
 const missing=[...(brief.process.length?[]:['Interview process']),...(brief.difficulty?[]:['Difficulty']),...(brief.questions.length?[]:['Practise these']),...(hasReports?[]:['What candidates reported'])];
 return <CitationProvider prefix="interview" sources={brief.sources}>
  {brief.process.length>0&&<ProcessStepper steps={brief.process}/>}
  {brief.difficulty&&<DifficultyBar difficulty={brief.difficulty}/>}
  {brief.questions.length>0&&<SectionPanel id="interview-questions-title" title="Practise these" tag={allEstimated?<EstimatedTag/>:undefined} description="Open a question to see how to prepare.">
   <QuestionAccordion questions={brief.questions} markEach={!allEstimated}/>
  </SectionPanel>}
  {hasReports&&<SectionPanel id="interview-reports-title" title="What candidates reported" description="From candidate interview reviews.">
   <CandidateReports reports={reports}/>
  </SectionPanel>}
  <NotFound id="interview-gaps-title" items={unique([...brief.notFound,...missing])}/>
  <Sources id="interview-sources-title" sources={brief.sources}/>
 </CitationProvider>;
}

export function OpportunityIntelligence({goalId,version,selectionVersion,section='interview',goal}:{goalId:string;version:number;selectionVersion:number;section?:Section;goal?:GoalBasics}){
 const {token}=useProfile();const [data,setData]=useState<OpportunityView>(),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[busy,setBusy]=useState<IntelligenceCategory|'all'|null>(null);
 const command=useRef<{signature:string;key:string}|null>(null),controller=useRef<AbortController|null>(null);
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
 useEffect(()=>()=>controller.current?.abort(),[]);
 async function research(category?:IntelligenceCategory){
  if(!token||busy)return;const abort=new AbortController();controller.current=abort;setBusy(category||'all');setError('');
  const body=JSON.stringify({expected_version:version,expected_selection_version:selectionVersion,refresh:!!data?.job_id,category:category||null});
  if(command.current?.signature!==body)command.current={signature:body,key:crypto.randomUUID()};
  try{const value=await careerApi<OpportunityView>(path,token,{method:'POST',signal:abort.signal,headers:{'Idempotency-Key':command.current.key},body});if(!abort.signal.aborted){setData(value);command.current=null;setAttempt(v=>v+1);}}
  catch{if(!abort.signal.aborted)setError('Research could not start. Check that the opportunity is current and the research providers are available, then retry.');}
  finally{if(!abort.signal.aborted)setBusy(null);}
 }
 const keys:IntelligenceCategory[]=section==='interview'?['interview_intelligence']:['internship_insights','career_progression','conversion_outcomes','company_intelligence'];
 const states=keys.map(key=>data?.categories?.[key]).filter((v):v is NonNullable<typeof v>=>!!v);
 const running=!!data?.job_id&&!data.finished&&['pending','running'].includes(data.status);
 const pending=states.some(v=>['pending','running'].includes(v.status));
 const done=!!data&&!pending&&!running;
 const researchId=data?.research_id??null;
 const [brief,setBrief]=useState<{key:string;value:RoleBrief|InterviewBrief}|null>(null),[generating,setGenerating]=useState(false),[briefError,setBriefError]=useState(''),[briefAttempt,setBriefAttempt]=useState(0);
 const briefKey=`${section}:${version}:${researchId}`;
 useEffect(()=>{
  // Once research settles, read the saved brief for this goal version and research, generating it when missing.
  if(!token||!done)return;const abort=new AbortController();const url=`/goals/${goalId}/v2/${briefPath[section]}`;
  (async()=>{try{
   let view=await careerApi<BriefView<RoleBrief|InterviewBrief>>(url,token,{signal:abort.signal});
   if(view.status==='missing'){if(abort.signal.aborted)return;setGenerating(true);setBriefError('');
    view=await careerApi<BriefView<RoleBrief|InterviewBrief>>(url,token,{method:'POST',signal:abort.signal,body:JSON.stringify({expected_version:version})});}
   if(abort.signal.aborted)return;
   if(view.brief&&!isBrief(view.brief))throw new Error('Malformed brief');
   if(view.brief)setBrief({key:briefKey,value:view.brief});
  }catch{if(!abort.signal.aborted)setBriefError('The research summary could not be prepared. Retry, or refresh research.');}
  finally{if(!abort.signal.aborted)setGenerating(false);}})();
  return()=>abort.abort();
 },[section,token,done,goalId,version,briefKey,briefAttempt]);
 const current=brief?.key===briefKey?brief.value:null;
 const notices:string[]=[];
 if(states.some(v=>v.status==='not_applicable'))notices.push('No company is specified, so employer-specific research was skipped.');
 const title=section==='interview'?'Interview preparation':'About the role';
 const refreshLabel=busy?'Starting research…':running?'Research in progress…':data?.job_id?'Refresh research':'Research opportunity';
 const sourceCount=current?.sourceCount??0;
 const estimated=!!current&&(section==='role'?hasRoleEstimates(current as RoleBrief):hasInterviewEstimates(current as InterviewBrief));
 let body:ReactNode=null;
 if(current)body=section==='role'?<RoleResearch brief={current as RoleBrief}/>:<InterviewResearch brief={current as InterviewBrief}/>;
 else if(section==='role'&&goal)body=<GoalOnly goal={goal}/>;
 return <section className="brief" id={section==='interview'?'interview-preparation':'about-role'} aria-labelledby={`${section}-research-heading`}>
  <h2 id={`${section}-research-heading`} className="brief-sr">{title}</h2>
  <header className="brief-head">
   <div className="brief-head-row">
    <p className="brief-meta" role="note">
     {current?`Researched ${formatDayMonthYear(current.researchedAt)} from ${sourceCount} public source${sourceCount===1?'':'s'}. `:'No completed research yet. '}
     AI can get details wrong, so check the sources before relying on them.
     {estimated&&<> Items tagged <EstimatedTag/> are AI suggestions, not from a source.</>}
    </p>
    <button type="button" className="brief-refresh" disabled={!data?.available||!!busy||running} onClick={()=>void research(section==='interview'?'interview_intelligence':undefined)}><Icon name="refresh"/>{refreshLabel}</button>
   </div>
   {current&&<SummaryLead>{current.summary}</SummaryLead>}
  </header>
  {!data&&!error&&<p role="status" className="small">Checking opportunity research…</p>}
  {data&&!data.available&&<div className="notice"><p>Opportunity research is unavailable on this server. Saved findings remain readable.</p>{!!data.availability_issues?.length&&<ul>{data.availability_issues.map(issue=><li key={issue}>{availabilityMessages[issue]}</li>)}</ul>}</div>}
  {error&&<div role="alert" className="notice"><p>{error}</p><button className="btn ghost sm" onClick={()=>setAttempt(v=>v+1)}>Retry loading research</button></div>}
  {pending&&<p role="status" className="notice">{states.some(v=>['rate_limited','source_rate_limited'].includes(v.error_code||''))?`Waiting for the AI allowance${data?.retry_after?`; resuming in about ${data.retry_after} seconds`:''}.`:'Researching…'} Available findings stay visible.</p>}
  {notices.map(notice=><p key={notice} className="notice">{notice}</p>)}
  {generating&&!current&&<p role="status" className="notice">Summarising the research…</p>}
  {briefError&&<div role="alert" className="notice"><p>{briefError}</p><button className="btn ghost sm" onClick={()=>setBriefAttempt(v=>v+1)}>Retry summary</button></div>}
  {body}
 </section>;
}

const hasRoleEstimates=(brief:RoleBrief)=>brief.topics.some(topic=>topic.estimated)||[...brief.facts,...brief.pay].some(item=>!item.citations.length);
const hasInterviewEstimates=(brief:InterviewBrief)=>!!brief.difficulty?.estimated||brief.questions.some(question=>question.estimated)||brief.process.some(step=>!step.citations.length);

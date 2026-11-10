"use client";
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type OpportunityView,type OpportunityAvailabilityIssue,type IntelligenceCategory,type IntelligenceFinding,type ResearchSource} from '@/lib/api/career';
import { formatDateTime } from '@/lib/format';
import { Icon } from '@/components/ui/icon';

const categories:[IntelligenceCategory,string,string][]=[
 ['interview_intelligence','Interview Intelligence','Recruitment stages, assessments, reported questions and preparation.'],
 ['internship_insights','Internship Insights','Intern experiences, projects, responsibilities, mentorship and workload.'],
 ['career_progression','Career Progression','Roles after internship, progression and reported full-time conversion salary.'],
 ['conversion_outcomes','Historical Conversion Rates','Yearly return offers, cohort evidence and full-time conversion percentages.'],
 ['company_intelligence','Company and Team Culture','Company-wide and team-specific culture, management and working hours.']];
const words=(value:string)=>value.replaceAll('_',' ');
const availabilityMessages:Record<OpportunityAvailabilityIssue,string>={
 research_disabled:'Opportunity research is turned off on the server.',
 reasoning_disabled:'The research reasoning provider is disabled on the server.',
 gemini_not_configured:'Gemini is not connected to the Career service.',
 brave_not_configured:'Brave is not connected to the Career service.',
 model_not_configured:'The configured model is not connected to the Career service.',
 search_not_configured:'The configured search provider is not connected to the Career service.',
 brave_llm_context_required:'The Brave connection needs LLM Context mode for opportunity research.'
};
function outcomeMessage(result:{outcome?:string|null;error_code:string|null}){
 switch(result.outcome){
  case 'no_relevant_sources':return 'The searches did not find sources relevant to this category.';
  case 'information_not_found':return 'Relevant sources were found, but they did not provide supported information for this category.';
  case 'validation_failed':return 'Proposed findings could not be verified. Available findings are preserved; refresh this section to retry.';
  case 'provider_failed':return result.error_code?.includes('timeout')?'The research provider timed out. Available findings are preserved; refresh this section to retry.':'A research provider could not complete the request. Available findings are preserved; refresh this section to retry.';
  default:return null;
 }
}
type Links=(ids:string[])=>ReactNode[];
const roundFields={questions:'interview_questions',prepare:'preparation_topics'};
/** Headline facts are process-wide; everything tied to one round sits under that round. */
function InterviewRounds({findings,links,done}:{findings:IntelligenceFinding[];links:Links;done:boolean}){
 const [open,setOpen]=useState<number|null>(null);
 const general=findings.filter(f=>f.round_number==null);
 const headline=general.filter(f=>['recruitment_stages','application_timeline','difficulty'].includes(f.field)).slice(0,4);
 const otherGeneral=general.filter(f=>!headline.includes(f));
 const numbers=[...new Set(findings.map(f=>f.round_number).filter((n):n is number=>n!=null))].sort((a,b)=>a-b);
 const rounds=numbers.map(n=>{const items=findings.filter(f=>f.round_number===n);return {n,name:items.find(f=>f.round_name)?.round_name||`Round ${n}`,items};});
 const shown=open??rounds[0]?.n??null;
 const list=(items:IntelligenceFinding[])=><ul className="round-list">{items.map(f=><li key={f.finding_id}><span>{f.value}</span><FindingLabels finding={f}/> {links(f.source_ids)}</li>)}</ul>;
 if(!findings.length)return done?<p className="small">elo couldn’t find interview details for this role in public sources. Refresh research to look again.</p>:null;
 return <>
  {headline.length>0&&<ul className="fact-tiles" aria-label="Interview headline facts">{headline.map(f=><li key={f.finding_id} className="fact-tile"><strong>{f.value}</strong><span className="small">{fieldTitles[f.field]??words(f.field)}</span><FindingLabels finding={f}/>{links(f.source_ids)}</li>)}</ul>}
  <h3 className="rounds-title">The rounds</h3>
  {rounds.length?<><p className="small">{rounds.length===1?'Sources describe one round.':`Sources describe ${rounds.length} rounds.`} Open a round to see what to expect and how to prepare.</p>
   <ol className="rounds">{rounds.map(round=>{const expanded=shown===round.n;const format=round.items.filter(f=>f.field==='round_format');const questions=round.items.filter(f=>f.field===roundFields.questions),prepare=round.items.filter(f=>f.field===roundFields.prepare),other=round.items.filter(f=>![...Object.values(roundFields),'round_format'].includes(f.field));
    return <li key={round.n} className={`round${expanded?' open':''}`}>
     <button type="button" className="round-head" aria-expanded={expanded} onClick={()=>setOpen(expanded?-1:round.n)}><span className="round-num" aria-hidden="true">{round.n}</span><span><strong>{round.name}</strong>{format[0]&&<span className="small">{format[0].value}</span>}</span><Icon name="chevron"/></button>
     {expanded&&<div className="round-body">
      {format.length>1&&list(format.slice(1))}
      <div><p className="briefing-detail-label">Questions to expect</p>{questions.length?list(questions):<p className="small">No reported questions for this round.</p>}</div>
      <div><p className="briefing-detail-label">How to prepare</p>{prepare.length?list(prepare):<p className="small">No reported preparation advice for this round.</p>}</div>
      {other.length>0&&<div><p className="briefing-detail-label">Candidate reports</p>{list(other)}</div>}
     </div>}
    </li>;})}</ol></>:<p className="small">Sources don’t break this process down by round yet. Refresh research to look again.</p>}
  {otherGeneral.length>0&&<><h3 className="rounds-title">Across the process</h3>{list(otherGeneral)}</>}
 </>;
}
const fieldTitles:Record<string,string>={recruitment_stages:'Stages',application_timeline:'Timeline',difficulty:'Difficulty',compensation:'Salary',benefits:'Benefits',projects:'What interns work on',mentorship:'Mentorship',work_life_balance:'Hours and workload',full_time_role:'Role after the internship',career_path:'Career path',conversion_salary:'Full-time salary',conversion_rate:'Conversion rate',historical_cohort:'Intake',offer_acceptance:'Offers and acceptances',company_culture:'Company culture',team_culture:'Team culture',management:'Management',candidate_experience:'Candidate reports',interview_questions:'Questions',preparation_topics:'Preparation',round_format:'Format'};
function FindingLabels({finding}:{finding:IntelligenceFinding}){
 return <>{finding.confidence==='low'&&<span className="finding-flag">low confidence</span>}{finding.scope!=='exact'&&<span className="finding-flag">{words(finding.scope)} context</span>}{finding.conflict_group&&<span className="finding-flag intelligence-conflict">Conflicting reports</span>}</>;
}
/** One card per field the research found; fields with nothing found are hidden. */
function RoleFacts({findings,links,details,done}:{findings:IntelligenceFinding[];links:Links;details?:ReactNode;done:boolean}){
 const fields=[...new Set(findings.map(f=>f.field))];
 return <>
  {details&&<div className="role-details">{details}</div>}
  {fields.length>0&&<div className="fact-cards">{fields.map(field=><article key={field} className="fact-card"><h3>{fieldTitles[field]??words(field)}</h3>{findings.filter(f=>f.field===field).map(f=><div key={f.finding_id} className="fact-card-item"><p>{f.value}</p><FindingLabels finding={f}/><p className="fact-sources">{links(f.source_ids)}</p></div>)}</article>)}</div>}
  {done&&<p className="small">Fields elo couldn’t find are hidden.</p>}
 </>;
}
export function OpportunityIntelligence({goalId,version,selectionVersion,roleDetails,section='interview'}:{goalId:string;version:number;selectionVersion:number;roleDetails?:ReactNode;section?:'interview'|'role'}){
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
 const results=data?.categories||{},sources=data?.sources||[];
 const running=!!data?.job_id&&!data.finished&&['pending','running'].includes(data.status);
 const keys=section==='interview'?['interview_intelligence'] as IntelligenceCategory[]:categories.map(([key])=>key).filter(key=>key!=='interview_intelligence');
 const findings=keys.flatMap(key=>results[key]?.findings||[]);
 const states=keys.map(key=>results[key]).filter((v):v is NonNullable<typeof v>=>!!v);
 const researchedAt=states.map(v=>v.researched_at).filter((v):v is string=>!!v).sort().at(-1);
 const pending=states.some(v=>['pending','running'].includes(v.status));
 const notices:string[]=[...new Set(states.map(v=>outcomeMessage(v)).filter((v):v is NonNullable<typeof v>=>!!v))];
 const failed=states.some(v=>v.status==='failed')&&!notices.length;
 if(states.some(v=>v.status==='not_applicable'))notices.push('No company is specified, so employer-specific research was skipped.');
 const links=(ids:string[])=>ids.map(id=>sources.find(source=>source.source_id===id)).filter((source):source is ResearchSource=>!!source).map(source=><a key={source.source_id} className="fact-source" href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.platform} ↗</a>);
 const status=<div className="research-status">
  <p className="small">{researchedAt?`Researched ${formatDateTime(researchedAt)}`:'No completed research yet.'}</p>
  <button className="btn ghost sm" disabled={!data?.available||!!busy||running} onClick={()=>void research(section==='interview'?'interview_intelligence':undefined)}>{busy?'Starting research…':running?'Research in progress…':data?.job_id?'Refresh research':'Research opportunity'}</button>
 </div>;
 return <section className="card goal-research" id={section==='interview'?'interview-preparation':'about-role'} aria-labelledby={`${section}-research-heading`}>
  <div className="goal-research-head"><h2 id={`${section}-research-heading`}>{section==='interview'?'Interview preparation':'About the role'}</h2>{status}</div>
  <p className="research-warning" role="note"><Icon name="warn"/>This comes from AI research and public websites and may be inaccurate or out of date. Double-check before relying on it.</p>
  {!data&&!error&&<p role="status" className="small">Checking opportunity research…</p>}
  {data&&!data.available&&<div className="notice"><p>Opportunity research is unavailable on this server. Saved findings remain readable.</p>{!!data.availability_issues?.length&&<ul>{data.availability_issues.map(issue=><li key={issue}>{availabilityMessages[issue]}</li>)}</ul>}</div>}
  {error&&<div role="alert" className="notice"><p>{error}</p><button className="btn ghost sm" onClick={()=>setAttempt(v=>v+1)}>Retry loading research</button></div>}
  {pending&&<p role="status" className="notice">{states.some(v=>['rate_limited','source_rate_limited'].includes(v.error_code||''))?`Waiting for the AI allowance${data?.retry_after?`; resuming in about ${data.retry_after} seconds`:''}.`:'Researching…'} Available findings stay visible.</p>}
  {notices.map(notice=><p key={notice} className="notice">{notice}</p>)}
  {failed&&<p className="notice">Part of this research could not finish. Other results are preserved; refresh to retry.</p>}
  {section==='interview'?<InterviewRounds findings={findings} links={links} done={!!data&&!pending}/>:<RoleFacts findings={findings} links={links} details={roleDetails} done={!!data&&!pending}/>}
 </section>;
}

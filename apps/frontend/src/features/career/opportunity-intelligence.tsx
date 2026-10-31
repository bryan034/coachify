"use client";
import {useEffect,useRef,useState} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type OpportunityView,type OpportunityAvailabilityIssue,type IntelligenceCategory,type IntelligenceFinding,type ResearchSource} from '@/lib/api/career';

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
function Finding({finding,sources,goalId,researchId}:{finding:IntelligenceFinding;sources:ResearchSource[];goalId:string;researchId?:string|null}){
 const {token}=useProfile();const [evidence,setEvidence]=useState<{quotes:string[];sources:ResearchSource[]}>(),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const request=useRef<AbortController|null>(null);
 useEffect(()=>()=>request.current?.abort(),[]);
 async function load(){
  if(!token||!researchId||evidence||loading)return;
  const abort=new AbortController();request.current=abort;setLoading(true);setError('');
  try{const result=await careerApi<{quotes:string[];sources:ResearchSource[]}>(`/goals/${goalId}/opportunity-research/findings/${finding.finding_id}/evidence?research_id=${researchId}`,token,{signal:abort.signal});if(!abort.signal.aborted)setEvidence(result);}
  catch{if(!abort.signal.aborted)setError('Evidence could not be loaded.');}finally{if(!abort.signal.aborted)setLoading(false);}
 }
 return <article className="intelligence-finding"><p>{finding.value}</p><div className="intelligence-labels"><span>{words(finding.confidence)} confidence</span><span>{words(finding.evidence_type)}</span>{finding.scope!=='exact'&&<span>{words(finding.scope)} context</span>}{finding.conflict_group&&<span className="intelligence-conflict">Conflicting reports</span>}</div>
  <details onToggle={event=>{if(event.currentTarget.open)void load();}}><summary>Evidence and sources</summary>
   {loading&&<p role="status">Loading evidence…</p>}{error&&<p role="alert">{error} <button onClick={()=>void load()}>Retry evidence</button></p>}
   {finding.source_ids.map((id,i)=>{const source=(evidence?.sources||sources).find(s=>s.source_id===id);return <div className="intelligence-citation" key={id}>
    {source&&<><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.platform} ↗</a><p className="small">Published: {source.published_date?new Date(source.published_date).toLocaleDateString():'Unknown'} · Retrieved: {source.retrieved_at?new Date(source.retrieved_at).toLocaleDateString():'Unknown'}</p></>}
    {evidence?.quotes[i]&&<blockquote>{evidence.quotes[i]}</blockquote>}{source?.evidence&&<details><summary>Full retrieved excerpt</summary><blockquote>{source.evidence}</blockquote></details>}
   </div>;})}<p className="small">Verified {new Date(finding.last_verified_at).toLocaleDateString()}. Reports may differ from your opportunity.</p>
  </details>
 </article>;
}
export function OpportunityIntelligence({goalId,version,selectionVersion}:{goalId:string;version:number;selectionVersion:number}){
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
 const all=Object.values(results).flatMap(v=>v?.findings||[]),summary=data?.summary;
 const refs=(ids:string[]|undefined)=>[...new Set(ids||[])].map(id=>all.find(f=>f.finding_id===id)).filter((v):v is IntelligenceFinding=>!!v);
 const takeaways=refs(summary?.key_takeaway_refs),considerations=refs(summary?.consideration_refs),overview=refs(summary?.overview_refs);
 const running=!!data?.job_id&&!data.finished&&['pending','running'].includes(data.status);
 return <section className="goal-section opportunity-intelligence" aria-labelledby="opportunity-heading">
  <div className="goal-section-heading"><div><p className="small">Beyond the job description</p><h2 id="opportunity-heading">Opportunity Intelligence</h2></div><button className="btn ghost sm" disabled={!data?.available||!!busy||running} onClick={()=>void research()}>{busy==='all'?'Starting research…':running?'Research in progress…':data?.job_id?'Refresh research':'Research opportunity'}</button></div>
  <p className="small intelligence-intro">Source-backed public research, separate from your job requirements and personal skill assessment. Reports describe experiences and statements, not guaranteed outcomes.</p>
  {!data&&!error&&<p role="status" className="small">Checking opportunity research…</p>}
  {data&&!data.available&&<div className="notice"><p>Opportunity research is unavailable on this server. Saved findings remain readable.</p>{!!data.availability_issues?.length&&<ul>{data.availability_issues.map(issue=><li key={issue}>{availabilityMessages[issue]}</li>)}</ul>}</div>}
  {error&&<div role="alert" className="notice"><p>{error}</p><button className="btn ghost sm" onClick={()=>setAttempt(v=>v+1)}>Retry loading research</button></div>}
  {!!overview.length&&<div className="intelligence-overview"><h3>Opportunity overview</h3>{overview.map(f=><p key={f.finding_id}>{f.value}</p>)}</div>}
  {(!!takeaways.length||!!considerations.length)&&<div className="intelligence-takeaways">{!!takeaways.length&&<div><h3>Key takeaways</h3><ul>{takeaways.map(f=><li key={f.finding_id}>{f.value}</li>)}</ul></div>}{!!considerations.length&&<div><h3>Considerations</h3><ul>{considerations.map(f=><li key={f.finding_id}>{f.value}</li>)}</ul></div>}</div>}
  <div className="intelligence-sections">{categories.map(([key,title,description])=>{
   const result=results[key],notice=result?outcomeMessage(result):null,fields=[...new Set(result?.findings.map(f=>f.field)||[])];
   return <details key={key} className="card intelligence-section" open={key==='interview_intelligence'}><summary><span><strong>{title}</strong><span className="small">{description}</span></span><span className={`intelligence-status status-${result?.status||'pending'}`}>{words(result?.status||'Not researched')}</span></summary>
    <div className="intelligence-section-body"><div className="row between"><p className="small">{result?.researched_at?`Researched ${new Date(result.researched_at).toLocaleString()}`:'No completed research yet.'}</p><button className="btn ghost sm" disabled={!data?.available||!!busy||running||result?.status==='not_applicable'} onClick={()=>void research(key)}>{busy===key?'Starting…':'Refresh this section'}</button></div>
    {result&&['pending','running'].includes(result.status)&&<p role="status" className="notice">{['rate_limited','source_rate_limited'].includes(result.error_code||'')?`Waiting for the AI allowance${data?.retry_after?`; resuming in about ${data.retry_after} seconds`:''}.`:'Researching this category…'} Available findings stay visible.</p>}
    {notice&&<p className="notice">{notice}</p>}
    {result?.status==='failed'&&!notice&&<p className="notice">This category could not finish. Other results are preserved; refresh this section to retry.</p>}
    {result?.warnings.filter(w=>!notice||w!=='Information pertaining to this category was not found in the retrieved sources.').map((warning,i)=><p className="small intelligence-warning" key={i}>{warning}</p>)}
    {fields.map(field=><div className="intelligence-field" key={field}><h4>{words(field)}</h4>{result!.findings.filter(f=>f.field===field).map(f=><Finding key={f.finding_id} finding={f} sources={sources} goalId={goalId} researchId={data?.research_id}/>)}</div>)}
    {!notice&&!result?.findings.length&&!result?.warnings.some(w=>w==='Information pertaining to this category was not found in the retrieved sources.')&&<p className="small">{result?.status==='not_applicable'?'No company is specified for employer-specific research.':result?.status==='completed'?'Information pertaining to this category was not found in the retrieved sources.':'No supported findings are available yet.'}</p>}

    </div>
   </details>;
  })}</div>
 </section>;
}

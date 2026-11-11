"use client";
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type InterviewSuggestions,type InterviewSuggestionsView,type RoleSummary,type RoleSummaryView,type PrepGapField,type OpportunityView,type OpportunityAvailabilityIssue,type IntelligenceCategory,type IntelligenceFinding,type ResearchSource} from '@/lib/api/career';
import { formatDateTime } from '@/lib/format';
import { Icon } from '@/components/ui/icon';
import {sourceLink} from './source-links';

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
type Links=(ids:string[])=>ReactNode[];
type Generated={items:InterviewSuggestions['items'];busy:boolean;error:string};
const roundFields={questions:'interview_questions',prepare:'preparation_topics'} as const;
const headlineFields=['recruitment_stages','application_timeline','difficulty'];
const NotFilled=({busy=false}:{busy?:boolean})=>busy?<p className="small" role="status">Generating…</p>:<p className="small not-filled">Not filled yet.</p>;
const AI_MADE='Made by an AI model from the context it was provided, not found in any sources.';
/** Small marker on every field the model wrote; the legend under the page warning explains it. */
export const AiMark=()=><span className="ai-made" role="img" aria-label={AI_MADE} title={AI_MADE}><Icon name="warn"/></span>;
const AiLegend=()=><p className="ai-made-legend" role="note"><AiMark/>Fields marked with this icon were made by an AI model based on the context it was provided, and were not found in any sources.</p>;
/** Sourced findings first; an empty slot shows AI-made predictions with the marker, or says it is not filled. */
function Slot({label,sourced,generated,round,field,list}:{label:string;sourced:IntelligenceFinding[];generated:Generated;round:number|null;field:PrepGapField;list:(items:IntelligenceFinding[])=>ReactNode}){
 const predicted=generated.items.filter(item=>item.round_number===round&&item.field===field);
 return <div><p className="briefing-detail-label">{label}{!sourced.length&&predicted.length>0&&<AiMark/>}</p>
  {sourced.length?list(sourced):predicted.length?<ul className="round-list is-ai-made">{predicted.map(item=><li key={item.value}>{item.value}</li>)}</ul>:<NotFilled busy={generated.busy}/>}
 </div>;
}
/** Headline facts are process-wide; everything tied to one round sits under that round. All rounds stay open. */
function InterviewRounds({findings,links,generated}:{findings:IntelligenceFinding[];links:Links;generated:Generated}){
 const general=findings.filter(f=>f.round_number==null);
 const headline=general.filter(f=>headlineFields.includes(f.field)).slice(0,4);
 const missingHeadline=headlineFields.filter(field=>!headline.some(f=>f.field===field));
 const slotFields:string[]=Object.values(roundFields);
 const numbers=[...new Set(findings.map(f=>f.round_number).filter((n):n is number=>n!=null))].sort((a,b)=>a-b);
 // Without rounds, the questions and preparation slots belong to the whole process.
 const otherGeneral=general.filter(f=>!headline.includes(f)&&(numbers.length>0||!slotFields.includes(f.field)));
 const rounds=numbers.map(n=>{const items=findings.filter(f=>f.round_number===n);return {n,name:items.find(f=>f.round_name)?.round_name||`Round ${n}`,items};});
 const list=(items:IntelligenceFinding[])=><ul className="round-list">{items.map(f=><li key={f.finding_id}><span>{f.value}</span><FindingLabels finding={f}/> {links(f.source_ids)}</li>)}</ul>;
 const slots=(items:IntelligenceFinding[],round:number|null)=><>
  <Slot label="Questions to expect" sourced={items.filter(f=>f.field===roundFields.questions)} generated={generated} round={round} field={roundFields.questions} list={list}/>
  <Slot label="How to prepare" sourced={items.filter(f=>f.field===roundFields.prepare)} generated={generated} round={round} field={roundFields.prepare} list={list}/>
 </>;
 return <>
  <ul className="fact-tiles" aria-label="Interview headline facts">
   {headline.map(f=><li key={f.finding_id} className="fact-tile"><strong>{f.value}</strong><span className="small">{fieldTitles[f.field]??words(f.field)}</span><FindingLabels finding={f}/>{links(f.source_ids)}</li>)}
   {missingHeadline.map(field=>{const made=generated.items.find(item=>item.round_number==null&&item.field===field);
    return made?<li key={field} className="fact-tile is-ai-made"><strong>{made.value}</strong><span className="small">{fieldTitles[field]} <AiMark/></span></li>
     :<li key={field} className="fact-tile is-empty"><strong>{generated.busy?'Generating…':'Not filled yet'}</strong><span className="small">{fieldTitles[field]}</span></li>;})}
  </ul>
  {generated.error&&<p className="notice" role="alert">{generated.error}</p>}
  <h3 className="rounds-title">The rounds</h3>
  {rounds.length?<><p className="small">{rounds.length===1?'Sources describe one round.':`Sources describe ${rounds.length} rounds.`}</p>
   <ol className="rounds">{rounds.map(round=>{const format=round.items.filter(f=>f.field==='round_format');const other=round.items.filter(f=>![...slotFields,'round_format'].includes(f.field));
    return <li key={round.n} className="round open">
     <div className="round-head"><span className="round-num" aria-hidden="true">{round.n}</span><span><strong>{round.name}</strong>{format[0]&&<span className="small">{format[0].value}</span>}</span></div>
     <div className="round-body">
      {format.length>1&&list(format.slice(1))}
      {slots(round.items,round.n)}
      {other.length>0&&<div><p className="briefing-detail-label">Candidate reports</p>{list(other)}</div>}
     </div>
    </li>;})}</ol></>:<><p className="small">Not filled yet: sources don’t break this process down by round. Refresh research to look again.</p>
   <div className="round-body is-process">{slots(general,null)}</div></>}
  {otherGeneral.length>0&&<><h3 className="rounds-title">Across the process</h3>{list(otherGeneral)}</>}
 </>;
}
const fieldTitles:Record<string,string>={recruitment_stages:'Stages',application_timeline:'Timeline',difficulty:'Difficulty',compensation:'Salary',benefits:'Benefits',projects:'What interns work on',mentorship:'Mentorship',work_life_balance:'Hours and workload',full_time_role:'Role after the internship',career_path:'Career path',conversion_salary:'Full-time salary',conversion_rate:'Conversion rate',historical_cohort:'Intake',offer_acceptance:'Offers and acceptances',company_culture:'Company culture',team_culture:'Team culture',management:'Management',candidate_experience:'Candidate reports',interview_questions:'Questions',preparation_topics:'Preparation',round_format:'Format'};
function FindingLabels({finding}:{finding:IntelligenceFinding}){
 return <>{finding.confidence==='low'&&<span className="finding-flag">low confidence</span>}{finding.scope!=='exact'&&<span className="finding-flag">{words(finding.scope)} context</span>}{finding.conflict_group&&<span className="finding-flag intelligence-conflict">Conflicting reports</span>}</>;
}
/** A goal-derived card item; refs match the backend digest (req:<id>, summary, resp:<index>). */
export type RoleItem={ref:string;text:string;note?:string;urls?:string[]};
export type RoleCardInput={card_id:string;title:string;icon:string;items:RoleItem[]};
type CardItem=RoleItem&{finding?:IntelligenceFinding};
const fieldIcons:Record<string,string>={compensation:'money',conversion_salary:'money',benefits:'check',projects:'code',mentorship:'people',management:'people',team_culture:'people',company_culture:'building',work_life_balance:'cal',full_time_role:'up',career_path:'up',conversion_rate:'flag',historical_cohort:'flag',offer_acceptance:'flag'};
/** Fallback before (or without) the digest: one bullet per sentence, never a paragraph. */
export const toBullets=(text:string)=>text.split(/(?<=[.!?])\s+(?=[A-Z0-9"“(])|;\s+|\n+/).map(part=>part.trim()).filter(Boolean);
type SourceLinks=(ids:string[])=>{key:string;href:string;label:string}[];
/** One card per topic: scannable bullets, flags beside the bullet they qualify, sources once at the foot. */
function RoleCard({title,icon,items,digest,made,busy=false,sourceLinks}:{title:string;icon:string;items:CardItem[];digest?:{text:string;refs:string[]}[];made?:string[];busy?:boolean;sourceLinks:SourceLinks}){
 if(!items.length)return <article className={`fact-card role-card${made?.length?' is-ai-made':''}`}>
  <h3><span className="role-card-icon" aria-hidden="true"><Icon name={icon}/></span><span>{title}{made?.length?<AiMark/>:null}</span></h3>
  {made?.length?<ul className="role-bullets">{made.map(text=><li key={text}>{text}</li>)}</ul>:<NotFilled busy={busy}/>}
 </article>;
 const byRef=new Map(items.map(item=>[item.ref,item]));
 const usable=digest?.length&&digest.every(b=>b.refs.every(ref=>byRef.has(ref)))?digest:null;
 const bullets=usable?usable.map(b=>({text:b.text,items:b.refs.map(ref=>byRef.get(ref)!)})):items.flatMap(item=>toBullets(item.text).map(text=>({text,items:[item]})));
 const notes=[...new Set(items.map(item=>item.note).filter((n):n is string=>!!n))];
 const links=[...new Map(items.flatMap(item=>[...(item.urls??[]).map(sourceLink).filter(l=>l!==null).map(l=>({key:l.url,href:l.url,label:l.domain})),...(item.finding?sourceLinks(item.finding.source_ids):[])]).map(l=>[l.href,l])).values()];
 return <article className="fact-card role-card">
  <h3><span className="role-card-icon" aria-hidden="true"><Icon name={icon}/></span>{title}</h3>
  <ul className="role-bullets">{bullets.map((b,i)=>{const flagged=b.items.map(item=>item.finding).filter((f):f is IntelligenceFinding=>!!f);
   return <li key={i}><span>{b.text}</span>{flagged.slice(0,1).map(f=><FindingLabels key={f.finding_id} finding={f}/>)}</li>;})}</ul>
  {(notes.length>0||usable)&&<p className="small role-card-note">{[...notes,...(usable?['Summarised by AI from the sources']:[])].join(' · ')}</p>}
  {links.length>0&&<p className="briefing-sources">{links.map(l=><a key={l.key} href={l.href} target="_blank" rel="noopener noreferrer">{l.label} ↗</a>)}</p>}
 </article>;
}
// Every topic the page always shows, in page order (matches the backend digest).
const roleFields=['compensation','benefits','projects','mentorship','work_life_balance','full_time_role','career_path','conversion_salary','conversion_rate','historical_cohort','offer_acceptance','company_culture','team_culture','management'];
/** Goal cards first, then every role topic: sourced bullets, AI-made bullets with the marker, or not filled. */
function RoleFacts({findings,cards,digest,busy,loaded,sourceLinks}:{findings:IntelligenceFinding[];cards:RoleCardInput[];digest:RoleSummary|null;busy:boolean;loaded:boolean;sourceLinks:SourceLinks}){
 // Goal cards never wait for research; research topics appear once it has loaded.
 const fields=loaded?[...new Set([...roleFields,...findings.map(f=>f.field)])]:[];
 const all=[...cards,...fields.map(field=>({card_id:field,title:fieldTitles[field]??sentenceCase(words(field)),icon:fieldIcons[field]??'doc',
  items:findings.filter(f=>f.field===field).map(f=>({ref:f.finding_id,text:f.value,finding:f}))}))];
 const bulletsFor=(id:string)=>digest?.cards.find(card=>card.card_id===id)?.bullets;
 const madeFor=(id:string)=>digest?.generated?.find(card=>card.card_id===id)?.bullets;
 return <div className="fact-cards">{all.map(card=><RoleCard key={card.card_id} title={card.title} icon={card.icon} items={card.items} digest={bulletsFor(card.card_id)} made={madeFor(card.card_id)} busy={busy} sourceLinks={sourceLinks}/>)}</div>;
}
const sentenceCase=(value:string)=>value.charAt(0).toUpperCase()+value.slice(1);
export function OpportunityIntelligence({goalId,version,selectionVersion,roleCards=[],section='interview'}:{goalId:string;version:number;selectionVersion:number;roleCards?:RoleCardInput[];section?:'interview'|'role'}){
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
 // Outcome banners are replaced by AI-made fills and the legend; only the general-target note remains.
 const notices:string[]=[];
 if(states.some(v=>v.status==='not_applicable'))notices.push('No company is specified, so employer-specific research was skipped.');
 const done=!!data&&!pending&&!running;
 const researchId=data?.research_id??null;
 const [suggestions,setSuggestions]=useState<InterviewSuggestions|null>(null),[suggesting,setSuggesting]=useState(false),[suggestError,setSuggestError]=useState('');
 useEffect(()=>{
  // Once research settles, fill empty interview slots with labelled AI predictions (saved per goal version and research).
  if(section!=='interview'||!token||!done)return;const abort=new AbortController();const prep=`/goals/${goalId}/interview-prep`;
  (async()=>{try{
   let view=await careerApi<InterviewSuggestionsView>(prep,token,{signal:abort.signal});
   if(view.status==='missing'){if(abort.signal.aborted)return;setSuggesting(true);setSuggestError('');
    view=await careerApi<InterviewSuggestionsView>(prep,token,{method:'POST',signal:abort.signal,body:JSON.stringify({expected_version:version})});}
   if(!abort.signal.aborted)setSuggestions(view.suggestions);
  }catch{if(!abort.signal.aborted)setSuggestError('AI suggestions for the empty sections could not be generated. Refresh research to try again.');}
  finally{if(!abort.signal.aborted)setSuggesting(false);}})();
  return()=>abort.abort();
 },[section,token,done,goalId,version,researchId]);
 const [digest,setDigest]=useState<RoleSummary|null>(null),[digesting,setDigesting]=useState(false);
 useEffect(()=>{
  // Once research settles, condense each card into short cited bullets (saved per goal version and research).
  if(section!=='role'||!token||!done)return;const abort=new AbortController();const url=`/goals/${goalId}/role-summary`;
  (async()=>{try{
   let view=await careerApi<RoleSummaryView>(url,token,{signal:abort.signal});
   if(view.status==='missing'){if(abort.signal.aborted)return;setDigesting(true);
    view=await careerApi<RoleSummaryView>(url,token,{method:'POST',signal:abort.signal,body:JSON.stringify({expected_version:version})});}
   if(!abort.signal.aborted)setDigest(view.summary);
  }catch{/* Cards keep their sentence bullets when the summary is unavailable. */}
  finally{if(!abort.signal.aborted)setDigesting(false);}})();
  return()=>abort.abort();
 },[section,token,done,goalId,version,researchId]);
 const currentDigest=digest&&digest.research_id===researchId&&digest.goal_version===version?digest:null;
 const generated={items:suggestions&&suggestions.research_id===researchId&&suggestions.goal_version===version?suggestions.items:[],busy:suggesting,error:suggestError};
 const sourceLinks=(ids:string[])=>ids.map(id=>sources.find(source=>source.source_id===id)).filter((source):source is ResearchSource=>!!source).map(source=>({key:source.source_id,href:source.url,label:source.title||source.platform}));
 const links=(ids:string[])=>ids.map(id=>sources.find(source=>source.source_id===id)).filter((source):source is ResearchSource=>!!source).map(source=><a key={source.source_id} className="fact-source" href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.platform} ↗</a>);
 const status=<div className="research-status">
  <p className="small">{researchedAt?`Researched ${formatDateTime(researchedAt)}`:'No completed research yet.'}</p>
  <button className="btn ghost sm" disabled={!data?.available||!!busy||running} onClick={()=>void research(section==='interview'?'interview_intelligence':undefined)}>{busy?'Starting research…':running?'Research in progress…':data?.job_id?'Refresh research':'Research opportunity'}</button>
 </div>;
 return <section className="card goal-research" id={section==='interview'?'interview-preparation':'about-role'} aria-labelledby={`${section}-research-heading`}>
  <div className="goal-research-head"><h2 id={`${section}-research-heading`}>{section==='interview'?'Interview preparation':'About the role'}</h2>{status}</div>
  <p className="research-warning" role="note"><Icon name="warn"/>This comes from AI research and public websites and may be inaccurate or out of date. Double-check before relying on it.</p>
  {(section==='interview'?generated.items.length>0:!!currentDigest?.generated?.length)&&<AiLegend/>}
  {!data&&!error&&<p role="status" className="small">Checking opportunity research…</p>}
  {data&&!data.available&&<div className="notice"><p>Opportunity research is unavailable on this server. Saved findings remain readable.</p>{!!data.availability_issues?.length&&<ul>{data.availability_issues.map(issue=><li key={issue}>{availabilityMessages[issue]}</li>)}</ul>}</div>}
  {error&&<div role="alert" className="notice"><p>{error}</p><button className="btn ghost sm" onClick={()=>setAttempt(v=>v+1)}>Retry loading research</button></div>}
  {pending&&<p role="status" className="notice">{states.some(v=>['rate_limited','source_rate_limited'].includes(v.error_code||''))?`Waiting for the AI allowance${data?.retry_after?`; resuming in about ${data.retry_after} seconds`:''}.`:'Researching…'} Available findings stay visible.</p>}
  {notices.map(notice=><p key={notice} className="notice">{notice}</p>)}
  {section==='interview'?data&&<InterviewRounds findings={findings} links={links} generated={generated}/>:<RoleFacts findings={findings} cards={roleCards} digest={currentDigest} busy={digesting} loaded={!!data} sourceLinks={sourceLinks}/>}
 </section>;
}

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
 brave_not_configured:'Web search is not connected to the Career service.',
 model_not_configured:'The configured model is not connected to the Career service.',
 search_not_configured:'The configured search provider is not connected to the Career service.',
 brave_llm_context_required:'The Brave connection needs LLM Context mode for opportunity research.'
};
type Generated={items:InterviewSuggestions['items'];busy:boolean;error:string};
const roundFields={questions:'interview_questions',prepare:'preparation_topics'} as const;
const headlineFields=['recruitment_stages','application_timeline','difficulty'];
const NotFilled=({busy=false}:{busy?:boolean})=>busy?<p className="small" role="status">Generating…</p>:<p className="small not-filled">Not filled yet.</p>;
const AI_MADE='Made by an AI model from the context it was provided, not found in any sources.';
/** "Estimated" chip on every field the model wrote; the page header explains it. */
export const AiMark=()=><span className="ai-made" role="img" aria-label={AI_MADE} title={AI_MADE}>Estimated</span>;

/** A cited source. Footnote pills number sources in reading order; the Sources list at the foot uses the same numbers. */
type Ref={href:string;label:string};
type Cite=Ref&{n:number};
type Fns=(refs:Ref[])=>ReactNode;
function citations(){
 const map=new Map<string,Cite>();
 return {add(ref:Ref){let cite=map.get(ref.href);if(!cite){cite={...ref,n:map.size+1};map.set(ref.href,cite);}return cite;},list:()=>[...map.values()]};
}
const unique=(refs:Ref[])=>[...new Map(refs.map(ref=>[ref.href,ref])).values()];

const fieldTitles:Record<string,string>={recruitment_stages:'Stages',application_timeline:'Timeline',difficulty:'Difficulty',compensation:'Salary',benefits:'Benefits',projects:'What interns work on',mentorship:'Mentorship',work_life_balance:'Hours and workload',full_time_role:'Role after the internship',career_path:'Career path',conversion_salary:'Full-time salary',conversion_rate:'Conversion rate',historical_cohort:'Intake',offer_acceptance:'Offers and acceptances',company_culture:'Company culture',team_culture:'Team culture',management:'Management',candidate_experience:'Candidate report',interview_questions:'Questions',preparation_topics:'Preparation',round_format:'Format'};
function FindingLabels({finding}:{finding:IntelligenceFinding}){
 return <>{finding.conflict_group&&<span className="finding-flag intelligence-conflict">Conflicting reports</span>}</>;
}
/** Renders **bold** key terms as <strong>; everything else stays escaped text. */
export const Rich=({text}:{text:string})=><>{text.split(/\*\*([^*]+)\*\*/).map((part,i)=>i%2?<strong key={i}>{part}</strong>:part.replaceAll('*',''))}</>;
/** Fact tiles are already bold, so their key-term markers are dropped. */
const plain=(text:string)=>text.replaceAll('*','');
/** Fallback before (or without) the digest: one bullet per sentence, never a paragraph. */
export const toBullets=(text:string)=>text.split(/(?<=[.!?])\s+(?=[A-Z0-9"“(])|;\s+|\n+/).map(part=>part.trim()).filter(Boolean);
const sentenceCase=(value:string)=>value.charAt(0).toUpperCase()+value.slice(1);

const CheckMark=()=><svg className="role-check" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>;
const QuoteMark=()=><svg className="round-quote-mark" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4 11h5v8H3v-6c0-3.3 1.6-6 4.5-7l.8 1.6C6.6 8.5 5.7 9.6 5.5 11H4zm10 0h5v8h-6v-6c0-3.3 1.6-6 4.5-7l.8 1.6c-1.7.9-2.6 2-2.8 3.4H14z"/></svg>;

// ---- Interview preparation ----
const difficultyLevels=['Easy','Average','Difficult'];
/** Places a difficulty finding on the three-step scale when its wording says where; otherwise only the text shows. */
const difficultyLevel=(text:string)=>/\b(average|moderate|medium)\b/i.test(text)?1:/\b(hard|difficult|challenging|tough)\b/i.test(text)?2:/\b(easy|straightforward)\b/i.test(text)?0:null;
function DifficultyScale({text}:{text:string}){
 const level=difficultyLevel(text);if(level==null)return null;
 return <div className="difficulty-scale" role="img" aria-label={`${difficultyLevels[level]}, on a scale of easy, average, difficult`}>{difficultyLevels.map((label,i)=><span key={label} className={i===level?'on':undefined}>{label}</span>)}</div>;
}
/** Process-wide facts sit in the timeline and tiles; everything tied to one round sits under that round. All rounds stay open. */
function interviewBody({findings,generated,src}:{findings:IntelligenceFinding[];generated:Generated;src:(ids:string[])=>ReactNode}){
 const general=findings.filter(f=>f.round_number==null);
 const headline=general.filter(f=>headlineFields.includes(f.field)).slice(0,4);
 const slotFields:string[]=Object.values(roundFields);
 const numbers=[...new Set(findings.map(f=>f.round_number).filter((n):n is number=>n!=null))].sort((a,b)=>a-b);
 // Without rounds, the questions and preparation slots belong to the whole process.
 const otherGeneral=general.filter(f=>!headline.includes(f)&&(numbers.length>0||!slotFields.includes(f.field)));
 // Rounds are shown by position; n stays the source key.
 const rounds=numbers.map((n,index)=>{const items=findings.filter(f=>f.round_number===n);return {n,position:index+1,name:items.find(f=>f.round_name)?.round_name||`Round ${index+1}`,items};});
 const fact=(field:string)=>{const finding=headline.find(f=>f.field===field);if(finding)return {field,value:finding.value,finding,made:false};
  const made=generated.items.find(item=>item.round_number==null&&item.field===field);return {field,value:made?.value??'',finding:undefined,made:!!made};};
 const list=(items:IntelligenceFinding[])=><ul className="round-list">{items.map(f=><li key={f.finding_id}><span><Rich text={f.value}/></span><FindingLabels finding={f}/>{src(f.source_ids)}</li>)}</ul>;
 const slot=(label:string,items:IntelligenceFinding[],round:number|null,field:PrepGapField)=>{
  const sourced=items.filter(f=>f.field===field),predicted=generated.items.filter(item=>item.round_number===round&&item.field===field);
  return <div key={field}><p className="slot-label">{label}{!sourced.length&&predicted.length>0&&<AiMark/>}</p>
   {sourced.length?list(sourced):predicted.length?<ul className="round-list is-ai-made">{predicted.map(item=><li key={item.value}><Rich text={item.value}/></li>)}</ul>:<NotFilled busy={generated.busy}/>}
  </div>;
 };
 const slots=(items:IntelligenceFinding[],round:number|null)=><div className="round-slots">
  {slot('Questions to expect',items,round,roundFields.questions)}
  {slot('How to prepare',items,round,roundFields.prepare)}
 </div>;
 const timeline=fact('application_timeline');
 // The timeline heads the process panel when there are rounds to draw; otherwise it is a tile.
 const tiles=[fact('difficulty'),fact('recruitment_stages'),...(rounds.length?[]:[timeline])];
 const missing=generated.busy?'Generating…':'Not filled yet';
 return <>
  {rounds.length>0&&<section className="process-panel" aria-label="The process">
   <div className="process-head"><h3>The process</h3>
    <p>{timeline.value?<><span>{plain(timeline.value)}</span>{timeline.made&&<AiMark/>}{timeline.finding&&src(timeline.finding.source_ids)}</>:`Timeline: ${missing.toLowerCase()}`}</p></div>
   <ol className="process-steps">{rounds.map((round,index)=>{const format=round.items.find(f=>f.field==='round_format');
    return <li key={round.n}><div className="process-dot" aria-hidden="true"><span/>{index<rounds.length-1&&<i/>}</div>
     <div><strong>{round.name}</strong>{format&&<span className="process-format">{plain(format.value)}</span>}</div></li>;})}</ol>
  </section>}
  <ul className="fact-tiles" aria-label="Interview headline facts">
   {tiles.map(tile=><li key={tile.field} className={`fact-tile${tile.made?' is-ai-made':''}${tile.value?'':' is-empty'}`}>
    <span className="fact-tile-label">{fieldTitles[tile.field]}{tile.made&&<AiMark/>}</span>
    {tile.field==='difficulty'&&tile.value&&<DifficultyScale text={plain(tile.value)}/>}
    <strong>{tile.value?plain(tile.value):missing}</strong>
    {tile.finding&&<span className="fact-tile-foot"><FindingLabels finding={tile.finding}/>{src(tile.finding.source_ids)}</span>}
   </li>)}
  </ul>
  {generated.error&&<p className="notice" role="alert">{generated.error}</p>}
  <h3 className="rounds-title">Stage by stage</h3>
  {rounds.length?<><p className="rounds-intro">What to expect at each step, and how to get ready. <span>{rounds.length===1?'Sources describe one round.':`Sources describe ${rounds.length} rounds.`}</span></p>
   <ol className="rounds">{rounds.map(round=>{const format=round.items.filter(f=>f.field==='round_format');const other=round.items.filter(f=>![...slotFields,'round_format'].includes(f.field));
    return <li key={round.n} className="round">
     <span className="round-num" aria-hidden="true">{round.position}</span>
     <div className="round-main">
      <h4>{round.name}</h4>
      {format[0]&&<p className="round-format"><span><Rich text={format[0].value}/></span>{src(format[0].source_ids)}</p>}
      {format.length>1&&list(format.slice(1))}
      {slots(round.items,round.n)}
      {other.map(f=><figure key={f.finding_id} className="round-quote"><QuoteMark/><div>
       <blockquote><Rich text={f.value}/></blockquote>
       <figcaption>{fieldTitles[f.field]??sentenceCase(words(f.field))}<FindingLabels finding={f}/>{src(f.source_ids)}</figcaption>
      </div></figure>)}
     </div>
    </li>;})}</ol></>:<><p className="rounds-intro">Not filled yet: sources don’t break this process down by round. Refresh research to look again.</p>
   <div className="round-main is-process">{slots(general,null)}</div></>}
  {otherGeneral.length>0&&<><h3 className="rounds-title">Across the process</h3>{list(otherGeneral)}</>}
 </>;
}

// ---- About the role ----
/** A goal-derived card item; refs match the backend digest (req:<id>, summary, resp:<index>). */
export type RoleItem={ref:string;text:string;note?:string;urls?:string[]};
export type RoleCardInput={card_id:string;title:string;icon:string;items:RoleItem[]};
type CardItem=RoleItem&{finding?:IntelligenceFinding};
type Card={card_id:string;title:string;icon:string;items:CardItem[]};
const fieldIcons:Record<string,string>={compensation:'money',conversion_salary:'money',benefits:'check',projects:'code',mentorship:'people',management:'people',team_culture:'people',company_culture:'building',work_life_balance:'cal',full_time_role:'up',career_path:'up',conversion_rate:'flag',historical_cohort:'flag',offer_acceptance:'flag'};
// Every topic the page always shows, in page order (matches the backend digest).
const roleFields=['compensation','benefits','projects','mentorship','work_life_balance','full_time_role','career_path','conversion_salary','conversion_rate','historical_cohort','offer_acceptance','company_culture','team_culture','management'];
const roleGroups=[
 {key:'pay',title:'Pay and benefits',fields:['compensation','conversion_salary','benefits']},
 {key:'work',title:'Day to day',fields:['projects','mentorship','work_life_balance','management']},
 {key:'future',title:'After the internship',fields:['full_time_role','career_path','conversion_rate','historical_cohort','offer_acceptance']},
 {key:'culture',title:'Team and culture',fields:['company_culture','team_culture']}];
// The at-a-glance strip: topics whose AI headline is a short fact.
const glanceFields=['compensation','conversion_rate','full_time_role','historical_cohort'];
/** Goal cards first, then every role topic as a labelled row: sourced bullets, AI-made bullets with the chip, or not found yet. */
function roleBody({findings,cards,digest,busy,loaded,fns,refsFor}:{findings:IntelligenceFinding[];cards:RoleCardInput[];digest:RoleSummary|null;busy:boolean;loaded:boolean;fns:Fns;refsFor:(ids:string[])=>Ref[]}){
 // Goal cards never wait for research; research topics appear once it has loaded.
 const fields=loaded?[...new Set([...roleFields,...findings.map(f=>f.field)])]:[];
 const all:Card[]=[...cards,...fields.map(field=>({card_id:field,title:fieldTitles[field]??sentenceCase(words(field)),icon:fieldIcons[field]??'doc',
  items:findings.filter(f=>f.field===field).map(f=>({ref:f.finding_id,text:f.value,finding:f}))}))];
 const bulletsFor=(id:string)=>digest?.cards.find(card=>card.card_id===id)?.bullets;
 const madeFor=(id:string)=>digest?.generated?.find(card=>card.card_id===id)?.bullets;
 const headlineFor=(id:string)=>digest?.cards.find(card=>card.card_id===id)?.headline??digest?.generated?.find(card=>card.card_id===id)?.headline;
 const empty=(card:Card)=>!card.items.length&&!madeFor(card.card_id)?.length;
 const filled=all.filter(card=>!empty(card)),blank=all.filter(empty);
 const groupOf=(id:string)=>roleGroups.find(g=>g.fields.includes(id))?.key??(cards.some(c=>c.card_id===id)?'role':'more');
 const groups=[{key:'role',title:'The role',fields:[] as string[]},...roleGroups,{key:'more',title:'More findings',fields:[] as string[]}]
  .map(g=>({...g,cards:filled.filter(card=>groupOf(card.card_id)===g.key)})).filter(g=>g.cards.length);
 const itemRefs=(item:CardItem):Ref[]=>[...(item.urls??[]).map(sourceLink).filter(l=>l!==null).map(l=>({href:l.url,label:l.domain})),...(item.finding?refsFor(item.finding.source_ids):[])];
 const usableDigest=(card:Card)=>{const digest=bulletsFor(card.card_id),ids=new Set(card.items.map(item=>item.ref));
  return digest?.length&&digest.every(b=>b.refs.every(ref=>ids.has(ref)))?digest:null;};
 const glance=glanceFields.map(id=>filled.find(card=>card.card_id===id)).filter((card):card is Card=>!!card)
  .map(card=>({card,headline:headlineFor(card.card_id),made:!card.items.length})).filter(g=>!!g.headline&&(g.made||!!usableDigest(g.card)));
 const strip=glance.length>0&&<dl className="role-glance" aria-label="At a glance">{glance.map(({card,headline,made})=><div key={card.card_id}>
  <dt>{card.title}</dt><dd>{plain(headline!)}{made&&<AiMark/>}</dd>
  {!made&&<dd className="role-glance-foot">{fns(card.items.flatMap(itemRefs))}</dd>}
 </div>)}</dl>;
 const roleItem=(card:Card)=>{
  const made=madeFor(card.card_id),headline=headlineFor(card.card_id);
  const check=card.card_id==='work';
  if(!card.items.length)return <article key={card.card_id} className="role-item is-ai-made">
   <h4>{card.title}<AiMark/></h4>
   {headline&&<p className="role-card-headline">{plain(headline)}</p>}
   <ul className="role-bullets">{(made??[]).map(text=><li key={text}><span><Rich text={text}/></span></li>)}</ul>
  </article>;
  const byRef=new Map(card.items.map(item=>[item.ref,item]));
  const usable=usableDigest(card);
  const bullets=usable?usable.map(b=>({text:b.text,items:b.refs.map(ref=>byRef.get(ref)!)})):card.items.flatMap(item=>toBullets(item.text).map(text=>({text,items:[item]})));
  const notes=[...new Set(card.items.map(item=>item.note).filter((n):n is string=>!!n))];
  return <article key={card.card_id} className="role-item">
   <h4>{card.title}</h4>
   {usable&&headline&&<p className="role-card-headline">{plain(headline)}</p>}
   <ul className={`role-bullets${check?' is-checks':''}`}>{bullets.map((b,i)=>{const flagged=b.items.map(item=>item.finding).filter((f):f is IntelligenceFinding=>!!f);
    return <li key={i}>{check&&<CheckMark/>}<span><Rich text={b.text}/></span>{flagged.slice(0,1).map(f=><FindingLabels key={f.finding_id} finding={f}/>)}{fns(b.items.flatMap(itemRefs))}</li>;})}</ul>
   {(notes.length>0||usable)&&<p className="small role-card-note">{[...notes,...(usable?['Summarised by AI from the sources']:[])].join(' · ')}</p>}
  </article>;
 };
 return <>
  {strip}
  <div className="role-rows">
   {groups.map(g=><section key={g.key} className="role-row" aria-label={g.title}>
    <h3>{g.title}</h3>
    <div className="role-row-body">{g.cards.map(roleItem)}</div>
   </section>)}
   {blank.length>0&&<section className="role-row" aria-label="Not found yet">
    <h3>Not found yet</h3>
    <div className="role-row-body is-single">
     <p className="small">{busy?'No source covered these. elo is filling them in now.':'No source covered these. Try asking current or past interns.'}</p>
     <ul className="role-empty">{blank.map(card=><li key={card.card_id}><Icon name={card.icon}/>{card.title}{busy&&<span className="visually-hidden" role="status"> Generating…</span>}</li>)}</ul>
    </div>
   </section>}
  </div>
 </>;
}

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
  }catch{}
  finally{if(!abort.signal.aborted)setDigesting(false);}})();
  return()=>abort.abort();
 },[section,token,done,goalId,version,researchId]);
 const currentDigest=digest&&digest.research_id===researchId&&digest.goal_version===version?digest:null;
 const generated={items:suggestions&&suggestions.research_id===researchId&&suggestions.goal_version===version?suggestions.items:[],busy:suggesting,error:suggestError};

 const cites=citations(),anchor=section==='interview'?'i-src':'a-src';
 const refsFor=(ids:string[]):Ref[]=>ids.map(id=>sources.find(source=>source.source_id===id)).filter((source):source is ResearchSource=>!!source)
  .flatMap(source=>{const link=sourceLink(source.url);return link?[{href:link.url,label:source.title||source.platform}]:[];});
 const fns:Fns=refs=>unique(refs).map(ref=>{const cite=cites.add(ref);
  return <a key={cite.n} className="fn" href={`#${anchor}-${cite.n}`} aria-label={`Source ${cite.n}: ${cite.label}`} title={cite.label}>{cite.n}</a>;});
 const body=section==='interview'
  ?data?interviewBody({findings,generated,src:ids=>fns(refsFor(ids))}):null
  :roleBody({findings,cards:roleCards,digest:currentDigest,busy:digesting,loaded:!!data,fns,refsFor});
 const cited=cites.list();
 const hasAi=section==='interview'?generated.items.length>0:!!currentDigest?.generated?.length;
 const title=section==='interview'?'Interview preparation':'About the role';
 const refreshLabel=busy?'Starting research…':running?'Research in progress…':data?.job_id?'Refresh research':'Research opportunity';
 return <section className="card goal-research" id={section==='interview'?'interview-preparation':'about-role'} aria-labelledby={`${section}-research-heading`}>
  <header className="goal-research-head">
   <div>
    <h2 id={`${section}-research-heading`}>{title}</h2>
    <p className="research-meta" role="note">
     {researchedAt?`Researched ${formatDateTime(researchedAt)}${cited.length?` from ${cited.length} public source${cited.length===1?'':'s'}`:''} by AI.`:'No completed research yet.'}
     {' '}Some details may be inaccurate or out of date, so check the sources before relying on them.
     {hasAi&&<> Items marked <AiMark/> were filled in by AI and aren’t from a source.</>}
    </p>
   </div>
   <button type="button" className="btn ghost research-refresh" disabled={!data?.available||!!busy||running} onClick={()=>void research(section==='interview'?'interview_intelligence':undefined)}><Icon name="refresh"/>{refreshLabel}</button>
  </header>
  {!data&&!error&&<p role="status" className="small">Checking opportunity research…</p>}
  {data&&!data.available&&<div className="notice"><p>Opportunity research is unavailable on this server. Saved findings remain readable.</p>{!!data.availability_issues?.length&&<ul>{data.availability_issues.map(issue=><li key={issue}>{availabilityMessages[issue]}</li>)}</ul>}</div>}
  {error&&<div role="alert" className="notice"><p>{error}</p><button className="btn ghost sm" onClick={()=>setAttempt(v=>v+1)}>Retry loading research</button></div>}
  {pending&&<p role="status" className="notice">{states.some(v=>['rate_limited','source_rate_limited'].includes(v.error_code||''))?`Waiting for the AI allowance${data?.retry_after?`; resuming in about ${data.retry_after} seconds`:''}.`:'Researching…'} Available findings stay visible.</p>}
  {notices.map(notice=><p key={notice} className="notice">{notice}</p>)}
  {body}
  {cited.length>0&&<footer className="research-sources">
   <h3>Sources</h3>
   <ol>{cited.map(cite=><li key={cite.n} id={`${anchor}-${cite.n}`}><a href={cite.href} target="_blank" rel="noopener noreferrer">{cite.label} ↗</a></li>)}</ol>
  </footer>}
 </section>;
}

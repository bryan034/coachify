"use client";
import {useEffect,useState} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type InterviewPrepGuide,type InterviewPrepView,type PrepBasis} from '@/lib/api/career';

const basisLabel:Record<PrepBasis,string>={confirmed:'Confirmed',candidate_report:'Reported',prediction:'Predicted'};
const kindLabel={behavioural:'Behavioural',technical:'Technical',case:'Case',ask:'Ask them'} as const;
const companyLabel={model:'Model',products:'Products',customers:'Customers',competitors:'Competitors',risks:'Risks'} as const;
const Chips=({items}:{items:string[]})=>items.length?<ul className="prep-chips">{items.map(item=><li key={item}>{item}</li>)}</ul>:null;
const Basis=({value}:{value:PrepBasis})=><span className={`prep-basis is-${value}`}>{basisLabel[value]}</span>;
const Group=({title,children}:{title:string;children:React.ReactNode})=><section className="prep-group"><h3>{title}</h3>{children}</section>;

/** Keyword-only guide for a specific job: labels and chips, never paragraphs. */
export function InterviewPrepGuideCard({goalId,version}:{goalId:string;version:number}){
 const {token}=useProfile();
 const [guide,setGuide]=useState<InterviewPrepGuide|null>(null),[date,setDate]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[loaded,setLoaded]=useState(false);
 const path=`/goals/${goalId}/interview-prep`;
 useEffect(()=>{
  if(!token)return;const abort=new AbortController();
  careerApi<InterviewPrepView>(path,token,{signal:abort.signal}).then(value=>{if(abort.signal.aborted)return;setGuide(value.guide);setDate(value.guide?.interview_date??'');setLoaded(true);})
   .catch(()=>{if(!abort.signal.aborted){setError('The guide could not be loaded.');setLoaded(true);}});
  return()=>abort.abort();
 },[token,path]);
 async function generate(){
  if(!token||busy)return;setBusy(true);setError('');
  try{const value=await careerApi<InterviewPrepView>(path,token,{method:'POST',body:JSON.stringify({expected_version:version,interview_date:date||null,refresh:!!guide})});setGuide(value.guide);}
  catch{setError('The guide could not be generated. Check that the AI service is available, then retry.');}
  finally{setBusy(false);}
 }
 const sources=new Map((guide?.sources??[]).map(source=>[source.source_id,source]));
 const links=(ids:string[])=>ids.map(id=>sources.get(id)).filter(<T,>(v:T|undefined):v is T=>!!v).map((source,i)=><a key={source.source_id} className="fact-source" href={source.url} target="_blank" rel="noopener noreferrer" aria-label={`Source ${i+1}: ${source.title||source.url}`}>↗</a>);
 const company=guide?(Object.keys(companyLabel) as (keyof typeof companyLabel)[]).filter(key=>guide.company[key].length):[];
 return <section className="card prep-guide" id="interview-prep" aria-labelledby="prep-guide-heading">
  <div className="prep-head">
   <h2 id="prep-guide-heading">Interview prep</h2>
   <div className="prep-actions">
    <label className="small">Interview date <input type="date" value={date} onChange={event=>setDate(event.target.value)}/></label>
    <button type="button" className="btn ghost sm" disabled={busy||!loaded} onClick={()=>void generate()}>{busy?'Preparing…':guide?'Refresh guide':'Create guide'}</button>
   </div>
  </div>
  {error&&<p role="alert" className="notice">{error}</p>}
  {!guide&&loaded&&!error&&<p className="small">Keywords only: process, topics, resume fit, questions and a prep plan.</p>}
  {guide&&<>
   <div className="prep-grid">
    {guide.role.length>0&&<Group title="Role"><Chips items={guide.role}/></Group>}
    {guide.success.length>0&&<Group title="Rewarded"><Chips items={guide.success}/></Group>}
    {company.map(key=><Group key={key} title={companyLabel[key]}><Chips items={guide.company[key]}/></Group>)}
   </div>
   {guide.process.length>0&&<Group title="Process"><ol className="prep-rows">{guide.process.map(stage=><li key={`${stage.round}-${stage.name}`}>
    {stage.round!=null&&<span className="round-num" aria-hidden="true">{stage.round}</span>}<strong>{stage.name}</strong><Chips items={stage.format}/><Basis value={stage.basis}/>{links(stage.source_ids)}</li>)}</ol></Group>}
   {guide.syllabus.length>0&&<Group title="Revise"><ul className="prep-rows">{guide.syllabus.map(topic=><li key={topic.name}>
    <strong>{topic.name}</strong><span className={`prep-priority is-${topic.priority}`}>{topic.priority}</span><span className="small">{topic.depth}</span><Chips items={topic.terms}/><Basis value={topic.basis}/>{links(topic.source_ids)}</li>)}</ul></Group>}
   {guide.resume.length>0&&<Group title="Resume fit"><ul className="prep-rows">{guide.resume.map(link=><li key={link.competency}>
    <strong>{link.competency}</strong><span className={`prep-fit is-${link.status}`}>{link.status==='gap'?'Gap':link.skill}</span><Chips items={link.signals}/></li>)}</ul></Group>}
   {guide.questions.length>0&&<Group title="Questions">{(Object.keys(kindLabel) as (keyof typeof kindLabel)[]).map(kind=>{const items=guide.questions.filter(q=>q.kind===kind);return items.length?
    <div key={kind}><p className="briefing-detail-label">{kindLabel[kind]}</p><ul className="prep-rows">{items.map(q=><li key={q.text}><span>{q.text}</span><Basis value={q.basis}/>{links(q.source_ids)}</li>)}</ul></div>:null;})}</Group>}
   {guide.schedule.length>0&&<Group title={guide.interview_date?'Plan to interview day':'Plan'}><ol className="prep-rows">{guide.schedule.map(step=><li key={step.when+step.focus[0]}><strong>{step.when}</strong><Chips items={step.focus}/></li>)}</ol></Group>}
   {guide.not_covered.length>0&&<p className="small">Not covered yet: {guide.not_covered.join(', ')}.</p>}
   <p className="small">Predicted items are not reported interview questions. AI-generated; verify before relying on it.</p>
  </>}
 </section>;
}

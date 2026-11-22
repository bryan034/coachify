"use client";
import type {IntelligenceFinding,IntelligenceResult,ResearchSource,OpportunityView} from '@/lib/api/career';
import {CitationProvider,SectionPanel,SourceList} from './research-brief';
import {FindingCard,FindingText,findingSources,type FindingSource} from './research-findings';

const sections=[
 ['recruitment_stages','Interview process'],
 ['application_timeline','Application timeline'],
 ['difficulty','Difficulty'],
 ['round_format','Interview format'],
 ['interview_questions','Questions reported'],
 ['preparation_topics','How to prepare'],
 ['candidate_experience','What candidates reported'],
] as const;
const overview=sections.slice(0,3),details=sections.slice(3);

function rounds(findings:IntelligenceFinding[],titles:Record<string,string>={}){
 const numbers=[...new Set(findings.flatMap(finding=>finding.round_number!=null?[finding.round_number]:[]))].sort((a,b)=>a-b);
 return numbers.map(number=>{
  const values=findings.filter(finding=>finding.round_number===number);
  const names=[...new Set(values.flatMap(finding=>finding.round_name?[finding.round_name]:[]))];
  const expectations=sections.filter(([field])=>!['interview_questions','preparation_topics'].includes(field)).flatMap(([field])=>values.filter(finding=>finding.field===field));
  const description=values.find(finding=>finding.field==='round_format')||values.find(finding=>finding.field==='recruitment_stages');
  const original=names.join(' / ');
  const name=titles[String(number)]||(original&&original.split(/\s+/).length<=3?original:`Round ${number}`);
  return {number,description,name,title:name===`Round ${number}`?name:`Round ${number}: ${name}`,expectations,
   questions:values.filter(finding=>finding.field==='interview_questions'),preparation:values.filter(finding=>finding.field==='preparation_topics')};
 });
}

function orderedFindings(findings:IntelligenceFinding[]){
 const general=(fields:typeof overview)=>fields.flatMap(([field])=>findings.filter(finding=>finding.round_number==null&&finding.field===field));
 return [...general(overview),...rounds(findings).flatMap(round=>[...round.expectations,...round.questions,...round.preparation]),...general(details)];
}

export function interviewSources(result:IntelligenceResult|undefined,available:ResearchSource[]):FindingSource[]{
 return findingSources(orderedFindings(result?.findings||[]),available);
}

export function InterviewResearch({result,sources,roundTitles,roundPreviews}:{result:IntelligenceResult;sources:FindingSource[];roundTitles?:Record<string,string>;roundPreviews?:OpportunityView['round_previews']}){
 const numbers=new Map(sources.map(source=>[source.source_id,source.index]));
 const grouped=rounds(result.findings,roundTitles);
 const missing=sections.filter(([field])=>!result.findings.some(finding=>finding.field===field)).map(([,title])=>title);
 const running=['pending','running'].includes(result.status);
 const generalSections=(fields:typeof overview)=>fields.map(([field,title])=>{
  const findings=result.findings.filter(finding=>finding.round_number==null&&finding.field===field);
  return findings.length>0&&<SectionPanel key={field} id={`interview-${field}-title`} title={title} description={grouped.length>0?'Not tied to a specific round.':undefined}>
   <ul className="brief-cards">{findings.map(finding=><FindingCard key={finding.finding_id} finding={finding} numbers={numbers}/>)}</ul>
  </SectionPanel>;
 });
 return <CitationProvider prefix="interview" sources={sources}>
  <section className="brief-round-overview" aria-labelledby="interview-round-count-title">
   <h3 id="interview-round-count-title">{grouped.length?`${grouped.length} reported interview round${grouped.length===1?'':'s'}`:running?'Researching interview rounds…':'Number of interview rounds not reported'}</h3>
   {grouped.length>0&&<ol className="brief-strip">{grouped.map((round,index)=><li key={round.number} className="brief-cell">
    <h4><a href={`#interview-round-${round.number}-title`} className="brief-round-link"><span className={`brief-step-dot${index===grouped.length-1?' is-last':''}`} aria-hidden="true">{round.number}</span><span>{round.name}</span></a></h4>
    <p className="brief-round-description">{round.description?<FindingText value={round.description.value}/>:running?'Research for this round is still in progress.':'A description of this round was not found in the sources.'}</p>
   </li>)}</ol>}
  </section>
  {['failed','partial'].includes(result.status)&&<p role="status" className="notice">Some interview research could not finish. Available findings are shown below.</p>}
  {generalSections(overview)}
  {grouped.length>0&&<section className="brief-rounds" aria-labelledby="interview-rounds-title">
   <h3 id="interview-rounds-title" className="brief-sr">Interview rounds</h3>
   {grouped.map(round=>{
    const preview=roundPreviews?.[String(round.number)];
    const select=(values:IntelligenceFinding[],id:string|null|undefined)=>values.find(finding=>finding.finding_id===id)||values[0];
    const expectation=select(round.expectations,preview?.expectation_id);
    const question=select(round.questions,preview?.question_id);
    const preparation=select(round.preparation,preview?.preparation_id);
    const all=[...round.expectations,...round.questions,...round.preparation];
    return <section key={round.number} className="brief-card brief-round" aria-label={round.title}>
     <div className="brief-round-heading"><span className="brief-round-number">Round {round.number}</span><h4 id={`interview-round-${round.number}-title`}>{round.name}</h4></div>
     <div className="brief-round-columns">
      <div><h5>What to expect</h5>
       {expectation?<ul className="brief-round-preview"><FindingCard finding={expectation} numbers={numbers} showRound={false} className="brief-round-finding"/></ul>:<p className="brief-card-label">{running?'Research for this round is still in progress.':'Round-specific expectations were not found in the sources.'}</p>}
      </div>
      <div><h5>Questions reported</h5>
       {question?<ul className="brief-round-preview"><FindingCard finding={question} numbers={numbers} showRound={false} className="brief-round-finding"/></ul>:<p className="brief-card-label">{running?'Question research is still in progress.':'No round-specific questions reported.'}</p>}
      </div>
     </div>
     {all.length>0&&<details className="brief-round-details">
      <summary>More about this round<span aria-hidden="true" className="brief-round-toggle"/></summary>
      <div className="brief-round-detail-content">
       {([{title:"Format, tasks and difficulty",values:round.expectations},{title:"Questions reported",values:round.questions},{title:"How to prepare",values:round.preparation}]).map(({title,values})=>values.length>0&&<div key={title}>
        <h5>{title}</h5><ul className="brief-round-detail-list">{values.map(finding=><FindingCard key={finding.finding_id} finding={finding} numbers={numbers} showRound={false} className="brief-round-finding"/>)}</ul>
       </div>)}
      </div>
     </details>}
     <div className="brief-round-preparation"><h5>How to prepare</h5>
      {preparation?<ul className="brief-round-preview"><FindingCard finding={preparation} numbers={numbers} showRound={false} className="brief-round-finding"/></ul>:<p className="brief-card-label">{running?'Preparation research is still in progress.':'Preparation guidance was not found for this round.'}</p>}
     </div>
    </section>;
   })}
  </section>}
  {generalSections(details)}
  {!running&&missing.length>0&&<SectionPanel id="interview-gaps-title" title="Not found yet" dashed><ul className="brief-gaps">{missing.map(title=><li key={title}>{title}</li>)}</ul></SectionPanel>}
  {sources.length>0&&<SectionPanel id="interview-sources-title" title="Sources" description="Numbered to match the citations above."><SourceList sources={sources}/></SectionPanel>}
 </CitationProvider>;
}

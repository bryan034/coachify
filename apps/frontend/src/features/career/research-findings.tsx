"use client";
import {Fragment} from 'react';
import type {BriefSource,IntelligenceFinding,ResearchSource} from '@/lib/api/career';
import {CitationChips,ConflictTag,EstimatedTag} from './research-brief';

const scopes:Record<string,string>={related_role:'Related role',related_location:'Related location',related_employment:'Related employment',general:'General role context'};
export type FindingSource=BriefSource&{source_id:string};

export function findingSources(findings:IntelligenceFinding[],available:ResearchSource[]):FindingSource[]{
 const pages=new Map(available.map(source=>[source.source_id,source]));
 const ids=new Set(findings.flatMap(finding=>finding.source_ids));
 return [...ids].flatMap(id=>{
  const source=pages.get(id);
  return source?[source]:[];
 }).map((source,index)=>({source_id:source.source_id,index:index+1,title:source.title||new URL(source.url).hostname,
  domain:new URL(source.url).hostname,url:source.url}));
}

export function FindingText({value}:{value:string}){
 return <>{value.split(/(\*\*[^*\n]+\*\*)/).map((part,index)=><Fragment key={index}>{part.startsWith('**')&&part.endsWith('**')?<strong>{part.slice(2,-2)}</strong>:part}</Fragment>)}</>;
}

export function FindingCard({finding,numbers,showRound=true,className="brief-card"}:{finding:IntelligenceFinding;numbers:Map<string,number>;showRound?:boolean;className?:string}){
 return <li className={className}>
  {showRound&&finding.round_number!=null&&<span className="brief-card-label">Round {finding.round_number}{finding.round_name&&` · ${finding.round_name}`}</span>}
  <p><FindingText value={finding.value}/><CitationChips citations={finding.source_ids.flatMap(id=>numbers.has(id)?[numbers.get(id)!]:[])}/></p>
  {(finding.scope!=='exact'||['low','insufficient_evidence'].includes(finding.confidence))&&<span className="brief-card-label">
   {[scopes[finding.scope],['low','insufficient_evidence'].includes(finding.confidence)?'Limited evidence':null].filter(Boolean).join(' · ')}
  </span>}
  {(finding.conflict_group||finding.evidence_type==='inferred')&&<p className="brief-tags">{finding.conflict_group&&<ConflictTag/>}{finding.evidence_type==='inferred'&&<EstimatedTag/>}</p>}
 </li>;
}

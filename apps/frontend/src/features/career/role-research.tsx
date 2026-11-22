"use client";
import type {OpportunityView,ResearchSource} from '@/lib/api/career';
import {CitationProvider,SectionPanel,SourceList} from './research-brief';
import {FindingCard,findingSources,type FindingSource} from './research-findings';

type Categories=OpportunityView['categories'];
export const roleCategories=['internship_insights','career_progression','conversion_outcomes','company_intelligence'] as const;
const sections=[
 {id:'role-topics',title:'What it is like',fields:[
  ['internship_insights','projects','Projects'],
  ['internship_insights','benefits','Benefits'],
  ['internship_insights','mentorship','Mentorship'],
  ['internship_insights','work_life_balance','Intern hours and workload'],
  ['company_intelligence','company_culture','Company culture'],
  ['company_intelligence','team_culture','Team culture'],
  ['company_intelligence','management','Management'],
  ['company_intelligence','work_life_balance','Company hours and workload'],
 ]},
 {id:'role-pay',title:'Pay and what comes after',fields:[
  ['internship_insights','compensation','Intern pay'],
  ['career_progression','full_time_role','Full-time opportunities'],
  ['career_progression','career_path','Career progression'],
  ['career_progression','conversion_salary','Full-time pay'],
  ['conversion_outcomes','conversion_rate','Conversion rate'],
  ['conversion_outcomes','historical_cohort','Historical cohorts'],
  ['conversion_outcomes','offer_acceptance','Offer acceptance'],
 ]},
] as const;

function groups(categories:Categories){
 return sections.map(section=>({...section,groups:section.fields.map(([category,field,title])=>({
  category,title,findings:categories[category]?.findings.filter(finding=>finding.field===field)||[],
 }))}));
}

export function roleSources(categories:Categories,available:ResearchSource[]):FindingSource[]{
 return findingSources(groups(categories).flatMap(section=>section.groups.flatMap(group=>group.findings)),available);
}

export function RoleResearch({categories,sources}:{categories:Categories;sources:FindingSource[]}){
 const numbers=new Map(sources.map(source=>[source.source_id,source.index]));
 const content=groups(categories);
 const missing=content.flatMap(section=>section.groups.filter(group=>categories[group.category]&&!['pending','running','not_applicable'].includes(categories[group.category]!.status)&&!group.findings.length).map(group=>group.title));
 return <CitationProvider prefix="role" sources={sources}>
  {roleCategories.some(category=>['failed','partial'].includes(categories[category]?.status||''))&&<p role="status" className="notice">Some role research could not finish. Available findings are shown below.</p>}
  {content.map(section=>section.groups.some(group=>group.findings.length>0)&&<SectionPanel key={section.id} id={`${section.id}-title`} title={section.title}>
   {section.groups.filter(group=>group.findings.length>0).map(group=><div key={`${group.category}-${group.title}`} className="brief-reports brief-topic">
    <h4>{group.title}</h4>
    <ul className="brief-cards">{group.findings.map(finding=><FindingCard key={finding.finding_id} finding={finding} numbers={numbers}/>)}</ul>
   </div>)}
  </SectionPanel>)}
  {missing.length>0&&<SectionPanel id="role-gaps-title" title="Not found yet" dashed><ul className="brief-gaps">{missing.map(title=><li key={title}>{title}</li>)}</ul></SectionPanel>}
  {sources.length>0&&<SectionPanel id="role-sources-title" title="Sources" description="Numbered to match the citations above."><SourceList sources={sources}/></SectionPanel>}
 </CitationProvider>;
}

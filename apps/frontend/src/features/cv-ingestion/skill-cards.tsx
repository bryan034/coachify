"use client";
import type { Assessment, EvaluatedSkill } from '@/features/roadmap/types';
import type {ReactNode} from 'react';
import {sameSkillName} from '@/lib/skill-identity';
import type {ApplicationLevel, ListedSkill, SkillLevelInfo, SkillList, SkillListSource} from './types';

const applicationLabel: Record<ApplicationLevel, string> = {guided_application: 'Guided', independent_application: 'Independent', complex_application: 'Complex work'};
const applicationRank = (value?: ApplicationLevel | null) => value ? Object.keys(applicationLabel).indexOf(value) + 1 : 0;
const basisLabel: Partial<Record<ListedSkill['basis'], string>> = {described: 'Described by you', draft: 'Proposed — review before saving', declared: 'Added by you'};
const readable = (value: string) => value.replaceAll('_', ' ');

export type Skill = {key: string; name: string; canonicalId?: string | null; ownLevel?: SkillLevelInfo | null; application?: ApplicationLevel | null; note?: string; added?: boolean; label: string; established: boolean; sources: string[]; details: ReactNode[]};

function label(skill: ListedSkill) {
 const level = skill.level?.level;
 if (level != null) return skill.level?.status === 'assumed' ? `${level} / 10 · estimated` : `${level} / 10`;
 if (skill.application) return applicationLabel[skill.application];
 if (skill.basis === 'proficiency' && skill.proficiency) return skill.proficiency;
 return basisLabel[skill.basis] ?? 'Level not established';
}

function detail(source: SkillListSource, index: number) {
 const key = `${source.kind}:${source.id}:${index}`;
 if (source.kind === 'cv') return <div className="skill-row-source" key={key}>
  <strong>{source.title ?? 'Source experience'}</strong>
  <p>{!source.attribution || source.attribution === 'unknown' ? 'Personal contribution needs clarification.' : `Contribution: ${source.attribution}. Support: ${source.assistance ?? 'unknown'}.`}</p>
  {source.evidence?.map((evidence, at) => <blockquote key={at}>{evidence.quote}</blockquote>)}
 </div>;
 if (source.kind === 'chat') return <div className="skill-row-source" key={key}>
  <p>{source.description}</p>
  <dl className="skills-facts">{source.facts?.map(fact => <div key={fact.field}><dt>{readable(fact.field)}</dt><dd>{fact.value ?? readable(fact.status)}</dd></div>)}</dl>
  <p className="small">Other dimensions remain unknown until discussed.</p>
  {source.evidence?.map((evidence, at) => <blockquote key={at}>{evidence.quote}</blockquote>)}
 </div>;
 return <div className="skill-row-source" key={key}><p>{source.description}</p></div>;
}

function card(skill: ListedSkill): Skill {
 const titles = skill.sources.filter(source => source.kind === 'chat' || (source.kind === 'cv' && source.item_kind !== 'skill')).flatMap(source => source.title ? [source.title] : []);
 return {key: skill.key, name: skill.name, canonicalId: skill.canonical_skill_id, ownLevel: skill.level, application: skill.application,
  note: skill.note ?? undefined, added: Boolean(skill.added_in_review), label: label(skill),
  established: ['level', 'application', 'proficiency'].includes(skill.basis) && !(skill.basis === 'level' && skill.level?.level == null),
  sources: [...new Set(titles)], details: skill.sources.map(detail)};
}

export const skillCards = (list: SkillList | null): Skill[] => list?.skills.map(card) ?? [];
export const skillCardGroups = (list: SkillList | null) => list?.skill_groups ?? {};

export const compareStrength = (a: Skill, b: Skill) =>
 (b.ownLevel?.level ?? 0) - (a.ownLevel?.level ?? 0) || applicationRank(b.application) - applicationRank(a.application) || Number(b.established) - Number(a.established);

export type Relevance='high'|'medium'|'low'|'none';
export type Status={relevance:Relevance|null;state:'score'|'not_needed'|'not_recorded'|'unknown'|'not_compared';score?:number;need?:number|null;explanation?:string|null};
export function evaluatedSkill(skill:Pick<Skill,'canonicalId'|'name'>,comparison?:Assessment|null):EvaluatedSkill|undefined{
 const skills=comparison?.skill_profile?.skills??[];
 return skills.find(item=>skill.canonicalId&&item.canonical_skill_id===skill.canonicalId)??skills.find(item=>(!skill.canonicalId || !item.canonical_skill_id) && sameSkillName(item.name,skill.name));
}
export function skillStatus(skill:Skill,comparison?:Assessment|null):Status{
 if(!comparison)return {relevance:null,state:'not_compared'};
 const judged=evaluatedSkill(skill,comparison);
 if(judged){
  if(judged.competence_score!=null)return {relevance:judged.relevance,state:'score',score:judged.competence_score,need:judged.required_score,explanation:judged.explanation};
  return {relevance:judged.relevance,state:judged.relevance==='none'?'not_needed':'unknown',explanation:judged.explanation};
 }
 const related=comparison.job_skill_gaps.filter(outcome=>skill.canonicalId&&outcome.canonical_skill_id===skill.canonicalId || outcome.components.some(component=>component.evidence_refs.some(ref=>{const name=comparison.evidence?.[ref]?.name;return Boolean(name&&sameSkillName(name,skill.name));})));
 if(!related.length)return {relevance:'none',state:'not_needed'};
 const order:Relevance[]=['high','medium','low','none'];
 const relevance=related.map(outcome=>outcome.relevance).filter((value):value is Relevance=>!!value).sort((a,b)=>order.indexOf(a)-order.indexOf(b))[0]??null;
 const scored=related.find(outcome=>outcome.competence_score!=null);
 if(scored)return {relevance,state:'score',score:scored.competence_score!,need:scored.required_score,explanation:scored.score_explanation};
 return {relevance,state:related.some(outcome=>outcome.score_status==='insufficient_evidence')?'unknown':'not_recorded'};
}

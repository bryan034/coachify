"use client";
import type { Assessment, EvaluatedSkill } from '@/features/roadmap/types';
import type {ReactNode} from 'react';
import type {CvDetail, Declarations, SkillEstimate, SkillLevelInfo, SkillsProfile} from './types';

// Steps follow the backend's evidence rubric. They are not a score or a test result.
const levels: Partial<Record<SkillEstimate['level'], {label: string; step: number}>> = {
 guided_application: {label: 'Guided', step: 1},
 independent_application: {label: 'Independent', step: 2},
 complex_application: {label: 'Complex work', step: 3},
};
const MAX_STEP = 3;
const readable = (value: string) => value.replaceAll('_', ' ');

/** A skill can have one estimate per experience; show the strongest supported one. */
function strongestLevel(estimates: SkillEstimate[] = [], skill: string) {
 return estimates.filter(estimate => estimate.skill_name.toLowerCase() === skill.toLowerCase())
  .map(estimate => levels[estimate.level])
  .reduce<{label: string; step: number} | undefined>((best, level) => level && (!best || level.step > best.step) ? level : best, undefined);
}

export type Skill = {ownLevel?:SkillLevelInfo|null;canonicalId?:string|null; note?:string; added?:boolean; key: string; name: string; label: string; step: number; established: boolean; sources: string[]; details: ReactNode[]};

function cvSkills(cv: CvDetail | null): Skill[] {
 if (!cv) return [];
 const review = cv.review_summary;
 return cv.skills.map(skill => {
  const titled = skill.sources?.map(source => ({source, item: cv.items.find(item => item.id === source.item_id)})) ?? [];
  const level = strongestLevel(cv.skill_estimates, skill.name);
  return {
   ownLevel:skill.skill_level,canonicalId:skill.canonical_skill_id,key: `cv:${skill.skill_id}`, name: skill.name,
   note: review?.skill_notes[skill.skill_id], added: review?.added_skill_ids.includes(skill.skill_id),
   label: skill.skill_level?.level != null ? `${skill.skill_level.level} / 10` : level?.label ?? skill.proficiency ?? 'Level not established', step: skill.skill_level?.level != null ? skill.skill_level.level * MAX_STEP / 10 : level?.step ?? 0, established: skill.skill_level?.level != null || Boolean(level ?? skill.proficiency),
   sources: titled.filter(({item}) => item && item.kind !== 'skill').map(({item}) => item!.title),
   details: titled.map(({source, item}) => <div className="skill-row-source" key={`cv:${source.item_id}`}>
    <strong>{item?.title ?? 'Source experience'}</strong>
    <p>{source.attribution === 'unknown' ? 'Personal contribution needs clarification.' : `Contribution: ${source.attribution}. Support: ${source.assistance}.`}</p>
    {source.evidence.map((evidence, index) => <blockquote key={`${evidence.id}:${index}`}>{evidence.excerpt}</blockquote>)}
   </div>),
  };
 });
}

function profileSkills(profile: SkillsProfile | null): Skill[] {
 if (!profile) return [];
 return profile.entries.flatMap(entry => entry.skills.map(skill => ({
  canonicalId:skill.canonical_skill_id,key: `profile:${entry.id}:${skill.name}`, name: skill.name,
  label: profile.status === 'draft' ? 'Proposed — review before saving' : 'Described by you', step: 0, established: false, sources: [entry.title],
  details: [<div className="skill-row-source" key={`profile:${entry.id}`}>
   <p>{skill.description}</p>
   <dl className="skills-facts">{Object.entries(skill.dimensions).map(([field, value]) => <div key={field}><dt>{readable(field)}</dt><dd>{value.value ?? readable(value.status)}</dd></div>)}</dl>
   <p className="small">Other dimensions remain unknown until discussed.</p>
   {skill.evidence.map((evidence, index) => <blockquote key={index}>{evidence.quote}</blockquote>)}
  </div>],
 })));
}

function declaredSkills(declarations: Declarations | null): Skill[] {
 return declarations?.declarations.map(declaration => ({
  canonicalId:declaration.canonical_skill_id,key: `declaration:${declaration.id}`, name: declaration.name,
  label: 'Added by you', step: 0, established: false, sources: [],
  details: [<div className="skill-row-source" key={`declaration:${declaration.id}`}><p>{declaration.description}</p></div>],
 })) ?? [];
}

/** The same skill from several sources is one row: strongest level, every source's evidence. */
function merged(skills: Skill[]) {
 const byName = new Map<string, Skill>();
 for (const skill of skills) {
  const key = skill.canonicalId || skill.name.trim().toLowerCase(), existing = byName.get(key);
  if (!existing) { byName.set(key, {...skill, sources: [...new Set(skill.sources)]}); continue; }
  const stronger = skill.established && (!existing.established || skill.step > existing.step);
  byName.set(key, {...existing, note: existing.note ?? skill.note, added: existing.added || skill.added, ...(stronger ? {ownLevel: skill.ownLevel ?? existing.ownLevel, label: skill.label, step: skill.step, established: true} : {}),
   sources: [...new Set([...existing.sources, ...skill.sources])], details: [...existing.details, ...skill.details]});
 }
 return [...byName.values()];
}

export const profileSkillList = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 merged([...cvSkills(cv), ...profileSkills(profile), ...declaredSkills(declarations)]);

export type Relevance='high'|'medium'|'low'|'none';
export type Status={relevance:Relevance|null;state:'score'|'not_needed'|'not_recorded'|'unknown'|'not_compared';score?:number;need?:number|null;explanation?:string|null};
/** The comparison's per-skill judgement, matched by registry identity or, failing that, by name. */
export function evaluatedSkill(skill:Pick<Skill,'canonicalId'|'name'>,comparison?:Assessment|null):EvaluatedSkill|undefined{
 const skills=comparison?.skill_profile?.skills??[],name=skill.name.trim().toLowerCase();
 return skills.find(item=>skill.canonicalId&&item.canonical_skill_id===skill.canonicalId)??skills.find(item=>item.name.trim().toLowerCase()===name);
}
/** Exactly one competence state per skill, read from the saved goal comparison. Nothing is scored here. */
export function skillStatus(skill:Skill,comparison?:Assessment|null):Status{
 if(!comparison)return {relevance:null,state:'not_compared'};
 // Prefer the comparison's own judgement of this skill; older results fall back to requirement outcomes.
 const judged=evaluatedSkill(skill,comparison);
 if(judged){
  if(judged.competence_score!=null)return {relevance:judged.relevance,state:'score',score:judged.competence_score,need:judged.required_score,explanation:judged.explanation};
  return {relevance:judged.relevance,state:judged.relevance==='none'?'not_needed':'unknown',explanation:judged.explanation};
 }
 const related=comparison.job_skill_gaps.filter(outcome=>skill.canonicalId&&outcome.canonical_skill_id===skill.canonicalId || outcome.components.some(component=>component.evidence_refs.some(ref=>comparison.evidence?.[ref]?.name?.trim().toLowerCase()===skill.name.trim().toLowerCase())));
 if(!related.length)return {relevance:'none',state:'not_needed'};
 const order:Relevance[]=['high','medium','low','none'];
 const relevance=related.map(outcome=>outcome.relevance).filter((value):value is Relevance=>!!value).sort((a,b)=>order.indexOf(a)-order.indexOf(b))[0]??null;
 const scored=related.find(outcome=>outcome.competence_score!=null);
 if(scored)return {relevance,state:'score',score:scored.competence_score!,need:scored.required_score,explanation:scored.score_explanation};
 return {relevance,state:related.some(outcome=>outcome.score_status==='insufficient_evidence')?'unknown':'not_recorded'};
}
/** Each source carries its own map; together they cover every skill shown. */
export const profileSkillGroups = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 ({...declarations?.skill_groups, ...profile?.skill_groups, ...cv?.skill_groups});

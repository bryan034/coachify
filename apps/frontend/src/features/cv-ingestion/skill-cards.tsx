"use client";
import type { Assessment, EvaluatedSkill } from '@/features/roadmap/types';
import {useState,type ReactNode} from 'react';
import {groupSkills} from '@/lib/skill-groups';
import {categoryAnchor} from '@/components/ui/skill-category-nav';
import type {CvDetail, Declarations, SkillEstimate, SkillsProfile} from './types';

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

type Skill = {canonicalId?:string|null; note?:string; added?:boolean; key: string; name: string; label: string; step: number; established: boolean; sources: string[]; details: ReactNode[]};

function cvSkills(cv: CvDetail | null): Skill[] {
 if (!cv) return [];
 const review = cv.review_summary;
 return cv.skills.map(skill => {
  const titled = skill.sources?.map(source => ({source, item: cv.items.find(item => item.id === source.item_id)})) ?? [];
  const level = strongestLevel(cv.skill_estimates, skill.name);
  return {
   canonicalId:skill.canonical_skill_id,key: `cv:${skill.skill_id}`, name: skill.name,
   note: review?.skill_notes[skill.skill_id], added: review?.added_skill_ids.includes(skill.skill_id),
   label: level?.label ?? skill.proficiency ?? 'Level not established', step: level?.step ?? 0, established: Boolean(level ?? skill.proficiency),
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
  byName.set(key, {...existing, note: existing.note ?? skill.note, added: existing.added || skill.added, ...(stronger ? {label: skill.label, step: skill.step, established: true} : {}),
   sources: [...new Set([...existing.sources, ...skill.sources])], details: [...existing.details, ...skill.details]});
 }
 return [...byName.values()];
}

export const profileSkillList = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 merged([...cvSkills(cv), ...profileSkills(profile), ...declaredSkills(declarations)]);

type Relevance='high'|'medium'|'low'|'none';
type Status={relevance:Relevance|null;state:'score'|'not_needed'|'not_recorded'|'unknown'|'not_compared';score?:number;need?:number|null;explanation?:string|null};
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
const stateText={not_needed:'Not needed for your current goal.',not_recorded:'Competence not recorded yet.',unknown:'Level unknown from your CV review.',not_compared:'Evaluate your skills with your Career Goal to see how this skill counts for it.'};
const relevanceLabels:Record<Relevance,string>={high:'High relevance',medium:'Medium relevance',low:'Low relevance',none:'Not needed'};

function SkillPanel({skill,status,close}:{skill:Skill;status:Status;close:()=>void}){
 return <aside className="card skill-panel" aria-labelledby="skill-panel-title">
  <div className="skill-panel-head"><h2 id="skill-panel-title">{skill.name}</h2><button type="button" className="btn ghost sm" aria-label="Close skill panel" onClick={close}>✕</button></div>
  <p className="briefing-detail-label">Used in</p>
  {skill.sources.length?<ul className="skill-panel-used">{skill.sources.map(source=><li key={source}>{source}</li>)}</ul>:<p className="small">Added through your Skills Profile.</p>}
  {(skill.note||skill.added)&&<div className="skill-panel-note"><p className="briefing-detail-label">From your review</p><p>{skill.note??'Added in review from your answers.'}</p></div>}
  <div className="skill-panel-state">
   {status.state==='score'?<><div className="skill-panel-score"><p className="briefing-detail-label">Competence for your goal</p><p><strong>{status.score}</strong><span> / 10</span></p></div>
    <div className="competence-bar" role="img" aria-label={`${status.score} out of 10 for your goal${status.need!=null?`, goal needs about ${status.need}`:''}`}><span className={`competence-fill ${status.need!=null&&status.score!>=status.need?'score-met':'score-short'}`} style={{width:`${status.score!*10}%`}}/>{status.need!=null&&<span className="competence-target" style={{left:`calc(${status.need*10}% - 1px)`}}/>}</div>
    {status.need!=null&&<p className="small">Goal needs about {status.need} / 10</p>}</>
   :<p>{stateText[status.state]}</p>}
   {status.explanation&&<p className="small skill-panel-why">{status.explanation}</p>}
  </div>
 </aside>;
}

/** One combined panel: a row per category (and sub-category), skills as chips coloured by goal relevance. */
export function SkillProfile({skills, categories: named, comparison, subcategories: namedSub={}}: {subcategories?:Record<string,string>;skills: Skill[]; comparison?: Assessment | null; categories: Record<string, string>}) {
 const [picked,setPicked]=useState<string|null>(null),[sort,setSort]=useState<'category'|'relevance'>('category');
 // A saved comparison's per-skill judgement decides category and sub-category; otherwise the backend's name map does.
 const judged=skills.map(skill=>[skill.name,evaluatedSkill(skill,comparison)] as const).filter((entry):entry is readonly [string,EvaluatedSkill]=>!!entry[1]);
 const categories={...named,...Object.fromEntries(judged.map(([name,item])=>[name,item.category]))};
 const subcategories:Record<string,string>={...namedSub,...Object.fromEntries(judged.map(([name,item])=>[name,item.subcategory??'']))};
 const groups = groupSkills(byStrength(skills), skill => skill.name, categories);
 const status=new Map(skills.map(skill=>[skill.key,skillStatus(skill,comparison)]));
 const chip=(skill:Skill)=>{const value=status.get(skill.key)!;return <li key={skill.key}><button type="button" className={`skill-chip relevance-${value.relevance??'unknown'}`} aria-pressed={picked===skill.key} onClick={()=>setPicked(picked===skill.key?null:skill.key)}>{skill.name}{value.relevance&&<span className="cv-visually-hidden">, {relevanceLabels[value.relevance]}</span>}</button></li>;};
 const rows=sort==='category'
  ? groups.flatMap(group=>[...new Set(group.items.map(skill=>subcategories[skill.name]||''))].map((sub,index)=>({key:`${group.name}:${sub}`,title:index===0?group.name:'',sub,items:group.items.filter(skill=>(subcategories[skill.name]||'')===sub)})))
  : (['high','medium','low','none'] as Relevance[]).map(level=>({key:level,title:relevanceLabels[level],sub:level==='high'?'Core to your goal':level==='medium'?'Helpful for your goal':level==='low'?'Nice to have':'Not used by your goal',items:skills.filter(skill=>status.get(skill.key)!.relevance===level)})).filter(row=>row.items.length);
 const selected=skills.find(skill=>skill.key===picked);
 return <>
  <div className={`skills-board${selected?' has-panel':''}`}>
   <section className="card skills-unified-panel" aria-labelledby="skills-panel-title">
    <div className="skills-panel-head"><h2 id="skills-panel-title">{sort==='category'?'Skills by category':'Skills by relevance to your goal'}</h2>
     {comparison&&<div className="skills-sort" role="group" aria-label="Sort skills by"><span>Sort by</span>{(['category','relevance'] as const).map(value=><button key={value} type="button" aria-pressed={sort===value} onClick={()=>setSort(value)}>{value==='category'?'Category':'Relevance to goal'}</button>)}</div>}
    </div>
    {comparison&&<ul className="skills-relevance-legend" aria-label="Relevance to your goal"><li>Relevance to your goal:</li>{(['high','medium','low','none'] as Relevance[]).map(level=><li key={level}><i className={`relevance-${level}`} aria-hidden="true"/>{level==='none'?'Not needed':level[0].toUpperCase()+level.slice(1)}</li>)}</ul>}
    {rows.map(row=><section key={row.key} className="skills-category-row" aria-label={[row.title,row.sub].filter(Boolean).join(' · ')||undefined} id={row.title&&sort==='category'?categoryAnchor('have',row.title):undefined}>
     <div className="skills-category-name">{row.title&&<h3>{row.title}</h3>}{row.sub&&<p className="small">{row.sub}</p>}</div>
     <ul className="skill-chips">{row.items.map(chip)}</ul>
    </section>)}
   </section>
   {selected&&<SkillPanel skill={selected} status={status.get(selected.key)!} close={()=>setPicked(null)}/>}
  </div>
 </>;
}

/** Within a card the strongest evidence comes first. */
const byStrength = (skills: Skill[]) => [...skills].sort((a, b) => b.step - a.step || Number(b.established) - Number(a.established) || a.name.localeCompare(b.name));

/** Each source carries its own map; together they cover every skill shown. */
export const profileSkillGroups = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 ({...declarations?.skill_groups, ...profile?.skill_groups, ...cv?.skill_groups});

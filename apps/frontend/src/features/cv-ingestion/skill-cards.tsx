"use client";
import type { Assessment, EvaluatedSkill } from '@/features/roadmap/types';
import {useEffect,useState,type ReactNode} from 'react';
import {rateSkill,ratingKey,skillRatings,type SkillRatings} from '@/lib/api/assessment';
import {announceInputsChanged} from '@/features/assessment/comparison';
import {groupSkills} from '@/lib/skill-groups';
import {categoryAnchor} from '@/components/ui/skill-category-nav';
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

type Skill = {ownLevel?:SkillLevelInfo|null;canonicalId?:string|null; note?:string; added?:boolean; key: string; name: string; label: string; step: number; established: boolean; sources: string[]; details: ReactNode[]};

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
const stateText={not_needed:'Not needed for your current goal.',not_recorded:'elo could not evaluate your proficiency in this skill yet.',unknown:'elo could not evaluate your proficiency in this skill from your CV and review.',not_compared:'Evaluate your skills with your Career Goal to see how this skill counts for it.'};

/** Outline bands for a skill's level: 8.5 and above, 6 and above, below 6, and uncertain (no level). */
export type Band='strong'|'developing'|'early'|'uncertain';
export const band=(score?:number|null):Band=>score==null?'uncertain':score>=8.5?'strong':score>=6?'developing':'early';
const bandLabels:Record<Band,string>={strong:'8.5–10',developing:'6–8.4',early:'Below 6',uncertain:'Uncertain'};
/** The level a chip is outlined by: elo's score, else the person's own rating, else none. */
const shownLevel=(skill:Skill,status:Status,self?:number)=>skill.ownLevel ? skill.ownLevel.level : (status.state==='score'?status.score:self);
const relevanceLabels:Record<Relevance,string>={high:'High relevance',medium:'Medium relevance',low:'Low relevance',none:'Not needed'};

function SelfRating({skill,self,save}:{skill:Skill;self?:number;save?:(score:number|null)=>Promise<void>}){
 const [editing,setEditing]=useState(false),[value,setValue]=useState(self??5),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{setEditing(false);setError('');setValue(self??5);},[skill.key,self]);
 if(!save)return null;
 const submit=async(score:number|null)=>{setBusy(true);setError('');try{await save(score);setEditing(false);}catch{setError('Your rating could not be saved. Try again.');}finally{setBusy(false);}};
 return <div className="skill-self-rating">
  {self!=null&&!editing&&<div className="skill-panel-score"><p className="briefing-detail-label">Your rating</p><p><strong>{self}</strong><span> / 10</span></p></div>}
  {self!=null&&!editing&&<p className="small">You set this level yourself. It is not checked against your evidence.</p>}
  {editing?<form className="skill-self-rating-form" onSubmit={event=>{event.preventDefault();void submit(value);}}>
    <label htmlFor="skill-self-score">Your level for {skill.name}: <strong>{value} / 10</strong></label>
    <input id="skill-self-score" type="range" min={1} max={10} step={1} value={value} onChange={event=>setValue(Number(event.target.value))}/>
    <div className="skill-self-rating-scale small" aria-hidden="true"><span>1 · Just starting</span><span>5 · Independent</span><span>10 · Expert</span></div>
    <div className="row"><button type="submit" className="btn pri sm" disabled={busy}>{busy?'Saving…':'Save my rating'}</button><button type="button" className="btn ghost sm" disabled={busy} onClick={()=>setEditing(false)}>Cancel</button></div>
   </form>
   :<div className="row"><button type="button" className="btn sm" onClick={()=>setEditing(true)}>{self!=null?'Change my rating':'Rate my skill level'}</button>{self!=null&&<button type="button" className="btn ghost sm" disabled={busy} onClick={()=>void submit(null)}>Remove</button>}</div>}
  {error&&<p role="alert" className="small">{error}</p>}
 </div>;
}

function SkillPanel({skill,status,close,self,save}:{skill:Skill;status:Status;close:()=>void;self?:number;save?:(score:number|null)=>Promise<void>}){
 return <aside className="card skill-panel" aria-labelledby="skill-panel-title">
  <div className="skill-panel-head"><h2 id="skill-panel-title">{skill.name}</h2><button type="button" className="btn ghost sm" aria-label="Close skill panel" onClick={close}>✕</button></div>
  <p className="briefing-detail-label">Used in</p>
  {skill.sources.length?<ul className="skill-panel-used">{skill.sources.map(source=><li key={source}>{source}</li>)}</ul>:<p className="small">Added through your Skills Profile.</p>}
  {(skill.note||skill.added)&&<div className="skill-panel-note"><p className="briefing-detail-label">From your review</p><p>{skill.note??'Added in review from your answers.'}</p></div>}
  {skill.ownLevel&&<div className="skill-panel-state">
   <div className="skill-panel-score"><p className="briefing-detail-label">Skill level from your CV and review</p><p>{skill.ownLevel.level!=null?<><strong>{skill.ownLevel.level}</strong><span> / 10</span></>:<span>Uncertain</span>}</p></div>
   <p className="small">{skill.ownLevel.rationale}</p>
  </div>}
  <div className="skill-panel-state">
   {status.state==='score'?<><div className="skill-panel-score"><p className="briefing-detail-label">Competence for your goal</p><p><strong>{status.score}</strong><span> / 10</span></p></div>
    <div className="competence-bar" role="img" aria-label={`${status.score} out of 10 for your goal${status.need!=null?`, goal needs about ${status.need}`:''}`}><span className={`competence-fill ${status.need!=null&&status.score!>=status.need?'score-met':'score-short'}`} style={{width:`${status.score!*10}%`}}/>{status.need!=null&&<span className="competence-target" style={{left:`calc(${status.need*10}% - 1px)`}}/>}</div>
    {status.need!=null&&<p className="small">Goal needs about {status.need} / 10</p>}</>
   :<><p className="skill-panel-uncertain">{skill.ownLevel?.level==null&&<span className="skill-level-tag level-uncertain">Uncertain</span>}{stateText[status.state]}</p><SelfRating skill={skill} self={self} save={save}/></>}
   {status.explanation&&<p className="small skill-panel-why">{status.explanation}</p>}
  </div>
 </aside>;
}

/** One combined panel: a row per category (and sub-category), skills as chips coloured by goal relevance. */
export function SkillProfile({skills, categories: named, comparison, subcategories: namedSub={}, token}: {subcategories?:Record<string,string>;skills: Skill[]; comparison?: Assessment | null; categories: Record<string, string>; token?: string}) {
 const [picked,setPicked]=useState<string|null>(null),[sort,setSort]=useState<'category'|'relevance'>('category');
 const [ratings,setRatings]=useState<SkillRatings|null>(null);
 useEffect(()=>{
  if(!token)return;
  const abort=new AbortController();
  skillRatings(token,abort.signal).then(value=>{if(!abort.signal.aborted)setRatings(value);}).catch(()=>{if(!abort.signal.aborted)setRatings(null);});
  return ()=>abort.abort();
 },[token]);
 const own=new Map((ratings?.ratings??[]).map(rating=>[rating.key,rating.score]));
 const save=token&&ratings?async(skill:Skill,score:number|null)=>{
  const value=await rateSkill(token,{expected_version:ratings.version,name:skill.name,canonical_skill_id:skill.canonicalId??null,score});
  setRatings(value);
  // The workspace version moved: let the evaluation views re-read it before their next command.
  announceInputsChanged();
 }:undefined;
 // A saved comparison's per-skill judgement decides category and sub-category; otherwise the backend's name map does.
 const judged=skills.map(skill=>[skill.name,evaluatedSkill(skill,comparison)] as const).filter((entry):entry is readonly [string,EvaluatedSkill]=>!!entry[1]);
 const categories={...named,...Object.fromEntries(judged.map(([name,item])=>[name,item.category]))};
 const subcategories:Record<string,string>={...namedSub,...Object.fromEntries(judged.map(([name,item])=>[name,item.subcategory??'']))};
 const groups = groupSkills(byStrength(skills), skill => skill.name, categories);
 const status=new Map(skills.map(skill=>[skill.key,skillStatus(skill,comparison)]));
 const chip=(skill:Skill)=>{const value=status.get(skill.key)!,self=own.get(ratingKey(skill)),level=shownLevel(skill,value,self),tier=band(level);return <li key={skill.key}><button type="button" className={`skill-chip relevance-${value.relevance??'unknown'} level-${tier}`} aria-pressed={picked===skill.key} aria-describedby={`level-${skill.key}`} onClick={()=>setPicked(picked===skill.key?null:skill.key)}>{skill.name}{value.relevance&&<span className="cv-visually-hidden">, {relevanceLabels[value.relevance]}</span>}</button><span id={`level-${skill.key}`} className="cv-visually-hidden">{level!=null?`Level ${level} out of 10${skill.ownLevel?.level!=null?', CV and review':value.state!=='score'?', your rating':''}`:'Level uncertain'}</span></li>;};
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
    <ul className="skills-level-legend" aria-label="Skill level outline"><li>Skill level (outline):</li>{(['strong','developing','early','uncertain'] as Band[]).map(tier=><li key={tier}><i className={`level-${tier}`} aria-hidden="true"/>{bandLabels[tier]}</li>)}</ul>
    {rows.map(row=><section key={row.key} className="skills-category-row" aria-label={[row.title,row.sub].filter(Boolean).join(' · ')||undefined} id={row.title&&sort==='category'?categoryAnchor('have',row.title):undefined}>
     <div className="skills-category-name">{row.title&&<h3>{row.title}</h3>}{row.sub&&<p className="small">{row.sub}</p>}</div>
     <ul className="skill-chips">{row.items.map(chip)}</ul>
    </section>)}
   </section>
   {selected&&<SkillPanel skill={selected} status={status.get(selected.key)!} close={()=>setPicked(null)} self={own.get(ratingKey(selected))} save={save&&(score=>save(selected,score))}/>}
  </div>
 </>;
}

/** Within a card the strongest evidence comes first. */
const byStrength = (skills: Skill[]) => [...skills].sort((a, b) => b.step - a.step || Number(b.established) - Number(a.established) || a.name.localeCompare(b.name));

/** Each source carries its own map; together they cover every skill shown. */
export const profileSkillGroups = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 ({...declarations?.skill_groups, ...profile?.skill_groups, ...cv?.skill_groups});

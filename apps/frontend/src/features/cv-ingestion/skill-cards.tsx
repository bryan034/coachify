"use client";
import {useState, type ReactNode} from 'react';
import {groupSkills} from '@/lib/skill-groups';
import {SkillCategoryNav, categoryAnchor} from '@/components/ui/skill-category-nav';
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

type Skill = {key: string; name: string; label: string; step: number; established: boolean; sources: string[]; details: ReactNode[]};

function cvSkills(cv: CvDetail | null): Skill[] {
 if (!cv) return [];
 return cv.skills.map(skill => {
  const titled = skill.sources?.map(source => ({source, item: cv.items.find(item => item.id === source.item_id)})) ?? [];
  const level = strongestLevel(cv.skill_estimates, skill.name);
  return {
   key: `cv:${skill.skill_id}`, name: skill.name,
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
  key: `profile:${entry.id}:${skill.name}`, name: skill.name,
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
  key: `declaration:${declaration.id}`, name: declaration.name,
  label: 'Added by you', step: 0, established: false, sources: [],
  details: [<div className="skill-row-source" key={`declaration:${declaration.id}`}><p>{declaration.description}</p></div>],
 })) ?? [];
}

/** The same skill from several sources is one row: strongest level, every source's evidence. */
function merged(skills: Skill[]) {
 const byName = new Map<string, Skill>();
 for (const skill of skills) {
  const key = skill.name.trim().toLowerCase(), existing = byName.get(key);
  if (!existing) { byName.set(key, {...skill, sources: [...new Set(skill.sources)]}); continue; }
  const stronger = skill.established && (!existing.established || skill.step > existing.step);
  byName.set(key, {...existing, ...(stronger ? {label: skill.label, step: skill.step, established: true} : {}),
   sources: [...new Set([...existing.sources, ...skill.sources])], details: [...existing.details, ...skill.details]});
 }
 return [...byName.values()];
}

export const profileSkillList = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 merged([...cvSkills(cv), ...profileSkills(profile), ...declaredSkills(declarations)]);

function LevelMeter({skill}: {skill: Skill}) {
 return <span className={`skill-level${skill.established ? ' established' : ''}`}>
  {skill.step > 0 && <span className="skill-level-meter" aria-hidden="true">{Array.from({length: MAX_STEP}, (_, index) => <span key={index} className={index < skill.step ? 'on' : ''}/>)}</span>}
  <span className="skill-level-label">{skill.label}</span>
 </span>;
}

function SkillRow({skill, collapsed = false}: {skill: Skill; collapsed?: boolean}) {
 return <li className={`skill-row${skill.established ? ' is-levelled' : ''}${skill.sources.length ? ' has-source' : ''}`} hidden={collapsed}><details>
  <summary>{skill.name}<LevelMeter skill={skill}/>{skill.sources.length > 0 && <span className="skill-row-from">{skill.sources.join(' · ')}</span>}</summary>
  <div className="skill-row-details">{skill.details}</div>
 </details></li>;
}

const COLLAPSED = 8;
/** Long categories start short. Every skill stays in the page so its evidence stays findable. */
function SkillGroupCard({name, items}: {name: string; items: Skill[]}) {
 const [expanded, setExpanded] = useState(false);
 const hidden = items.length - COLLAPSED;
 return <section className="skill-group" id={categoryAnchor('have', name)} aria-label={name}>
  <header><h3>{name}</h3><span>{items.length}</span></header>
  <ul>{items.map((skill, index) => <SkillRow key={skill.key} skill={skill} collapsed={!expanded && index >= COLLAPSED}/>)}</ul>
  {hidden > 0 && <button type="button" className="skill-group-more" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? 'Show fewer' : `+${hidden} more`}</button>}
 </section>;
}

/** Within a card the strongest evidence comes first. */
const byStrength = (skills: Skill[]) => [...skills].sort((a, b) => b.step - a.step || Number(b.established) - Number(a.established) || a.name.localeCompare(b.name));

/** Each source carries its own map; together they cover every skill shown. */
export const profileSkillGroups = (cv: CvDetail | null, profile: SkillsProfile | null, declarations: Declarations | null) =>
 ({...declarations?.skill_groups, ...profile?.skill_groups, ...cv?.skill_groups});

export function SkillProfile({skills, categories}: {skills: Skill[]; categories: Record<string, string>}) {
 const groups = groupSkills(byStrength(skills), skill => skill.name, categories);
 return <>
  <div className="skill-profile-overview">
   <p className="cv-visually-hidden"><strong>{skills.length} {skills.length === 1 ? 'skill' : 'skills'}</strong> in {groups.length} {groups.length === 1 ? 'category' : 'categories'}, <strong>{skills.filter(skill => skill.established).length}</strong> with an established level</p>
   <dl className="skill-level-legend" aria-label="What the levels mean">
    {Object.values(levels).map(level => <div key={level!.label}><dt>{level!.label}</dt><dd>{level!.step === 1 ? 'You applied it with support' : level!.step === 2 ? 'You applied it on your own' : 'Independent, on complex problems'}</dd></div>)}
   </dl>
  </div>
  <div className="skill-share" aria-hidden="true">{groups.map(group => <i key={group.name} style={{flexGrow: group.items.length}} title={`${group.name}: ${group.items.length}`}/>)}</div>
  <SkillCategoryNav groups={groups} prefix="have" label="Categories of your skills"/>
  <p className="skill-key"><span className="skill-key-source">From your experience</span><span className="skill-key-level">Level set</span></p>
  <div className="skill-group-grid">{groups.map(group => <SkillGroupCard key={group.name} name={group.name} items={group.items}/>)}</div>
 </>;
}

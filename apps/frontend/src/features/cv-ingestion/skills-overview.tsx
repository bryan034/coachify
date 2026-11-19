"use client";
import { useEffect, useMemo, useState } from 'react';
import { namesSkill } from '@/features/assessment/levels';
import { TalkItThrough, type TalkSkill } from '@/features/assessment/talk-it-through';
import type { Comparison } from '@/features/assessment/comparison';
import type { Assessment } from '@/features/roadmap/types';
import { linkedProfileSkills, skillParts } from '@/features/assessment/goal-breakdown';
import { skillOutcomes, skillRatings, ratingKey, type SkillRatings } from '@/lib/api/assessment';
import type { CurrentGoal, ReviewSkill } from '@/lib/api/career';
import type { Section } from '@/lib/api/workspace-summary';
import { groupSkills } from '@/lib/skill-groups';
import { evaluatedSkill, skillStatus, type Relevance, type Skill, type Status } from './skill-cards';

/** `missing`: a skill the Career Goal expects that none of the person's evidence shows yet. `parent`: the goal skill this one counts towards. */
type Entry = { skill: Skill; status: Status; level: number | null; target: number | null; own: boolean; missing?: boolean; parent?: ReviewSkill };
/** How a rated level sits against the role's target: met it, 2 or fewer short, or further away. No target, no colour. */
export const targetGap = (level: number, target: number | null) => target == null ? null : level >= target ? 'met' : target - level <= 2 ? 'near' : 'far';
const goalRelevant = (relevance: Relevance | null) => relevance === 'high' || relevance === 'medium';

/**
 * The person's skills as chips. Skills that count towards the career goal come first with their level against the role's target;
 * the rest sit behind "Show all skills" at the top. A skill counts when it is a goal skill, one of the smaller skills a goal skill
 * breaks down into, or linked to one by the saved evaluation: the same rule the Career Goal's breakdown uses.
 * Goal skills and smaller skills the person doesn't have yet show with a dotted outline.
 */
export function SkillsOverview({ token, skills, categories, assessment, comparison, goal, goalRole, onChanged }: {
 token?: string; skills: Skill[]; categories: Record<string, string>; assessment?: Assessment | null; comparison: Comparison;
 goal: Section<CurrentGoal>; goalRole?: string; onChanged?: () => void;
}) {
 const [ratings, setRatings] = useState<SkillRatings | null>(null), [showAll, setShowAll] = useState(false), [talking, setTalking] = useState<string | null>(null);
 const [ratingVersion, setRatingVersion] = useState(0);
 useEffect(() => {
  if (!token) return;
  const abort = new AbortController();
  skillRatings(token, abort.signal).then(value => { if (!abort.signal.aborted) setRatings(value); }).catch(() => { if (!abort.signal.aborted) setRatings(null); });
  return () => abort.abort();
 }, [token, ratingVersion, comparison.current?.version]);
 const own = useMemo(() => new Map((ratings?.ratings ?? []).map(rating => [rating.key, rating.score])), [ratings]);
 const compared = !!assessment;
 const goalSkills = useMemo(() => goal.status === 'ready' ? goal.data.goal?.skills ?? [] : [], [goal]);
 const goalGroups = goal.status === 'ready' ? goal.data.skill_groups ?? {} : {};
 const outcomes = useMemo(() => assessment ? skillOutcomes(assessment) : {}, [assessment]);
 const outcomeOf = (item: ReviewSkill) => item.item_id ? outcomes[item.item_id] : undefined;
 // The goal skill a skill counts towards: the same skill first, else the first goal skill it is part of or linked to.
 const parentOf = (skill: Pick<Skill, 'name' | 'canonicalId'>) => goalSkills.find(item => namesSkill([item], skill))
  ?? goalSkills.find(item => item.priority !== 'conflicting' && linkedProfileSkills(item, outcomeOf(item), [skill]).length > 0);
 const entries = skills.map((skill): Entry => {
  const status = skillStatus(skill, assessment), self = own.get(ratingKey(skill));
  const level = skill.ownLevel?.level ?? (status.state === 'score' ? status.score ?? null : self ?? null);
  return { skill, status, level, target: goalRelevant(status.relevance) ? status.need ?? null : null, own: skill.ownLevel?.level == null && status.state !== 'score' && self != null, parent: parentOf(skill) };
 });
 const placeholder = (key: string, name: string, label: string, canonicalId: string | null = null): Skill => ({ key, name, canonicalId, label, step: -1, established: false, sources: [], details: [] });
 const active = goalSkills.filter(item => item.priority !== 'conflicting');
 // Goal skills none of the person's skills count towards yet. They can't be rated, only built.
 const missing = active.filter(item => !linkedProfileSkills(item, outcomeOf(item), skills).length)
  .filter((item, index, list) => list.findIndex(other => namesSkill([other], { name: item.name, canonicalId: item.canonical_skill_id })) === index)
  .map((item): Entry => ({ skill: placeholder(`goal:${item.canonical_skill_id ?? item.name}`, item.name, 'Expected by your goal', item.canonical_skill_id ?? null),
   status: { relevance: null, state: 'not_recorded' }, level: null, target: item.competence_target?.level ?? null, own: false, missing: true, parent: item }));
 // The smaller skills goal skills break down into that the person doesn't have yet.
 const parts = active.flatMap(item => skillParts(item, goalSkills).map(part => ({ part, item })))
  .filter(({ part }, index, list) => !skills.some(skill => namesSkill([part], { name: skill.name })) && list.findIndex(other => namesSkill([other.part], { name: part.name })) === index)
  .map(({ part, item }): Entry => ({ skill: { ...placeholder(`part:${item.name}:${part.name}`, part.name, `Part of ${item.name}`), note: `Part of ${item.name}. ${part.reason}` },
   status: { relevance: null, state: 'not_recorded' }, level: null, target: null, own: false, missing: true, parent: item }));
 const all = [...entries, ...missing, ...parts];
 /* How much the Career Goal needs a skill: the stated priority of the goal skill it counts towards. Works before any evaluation. */
 const importance = (entry: Entry): 'important' | 'nice' | null => {
  if (!entry.parent || entry.parent.priority === 'conflicting') return null;
  return entry.parent.priority === 'required' || entry.parent.priority === 'preferred' ? 'important' : 'nice';
 };
 // Essential first, then important, then nice to have, then everything else.
 const rank = (entry: Entry) => {
  if (!entry.parent || entry.parent.priority === 'conflicting') return 4;
  return entry.parent.priority === 'required' ? 0 : entry.parent.priority === 'preferred' ? 1 : 2;
 };
 // The strongest evidence comes first within each category.
 const strongest = (a: Entry, b: Entry) => b.skill.step - a.skill.step || Number(b.skill.established) - Number(a.skill.established) || a.skill.name.localeCompare(b.skill.name);
 // "Show fewer" keeps only the skills the goal needs; "Show all skills" adds the rest. Goal skills come first, most important first, then by strength.
 const hidden = entries.filter(entry => !importance(entry)).length, hasRelevant = hidden < entries.length || missing.length + parts.length > 0;
 const filtering = hasRelevant && !showAll;
 const listed = all.filter(entry => !filtering || importance(entry)).sort((a, b) => rank(a) - rank(b) || strongest(a, b));
 // A smaller skill sits in the same category as the goal skill it belongs to.
 const partGroups = Object.fromEntries(parts.flatMap(entry => { const group = entry.parent && goalGroups[entry.parent.name]; return group ? [[entry.skill.name, group]] : []; }));
 const groups = groupSkills(listed, entry => entry.skill.name, { ...partGroups, ...goalGroups, ...categories, ...Object.fromEntries(skills.flatMap(skill => { const judged = evaluatedSkill(skill, assessment); return judged ? [[skill.name, judged.category]] : []; })) });
 const picked = all.find(entry => entry.skill.key === talking);
 const talkSkill = useMemo((): TalkSkill | null => {
  if (!picked) return null;
  // A smaller skill has no target of its own; its note says which goal skill it belongs to.
  const match = picked.parent && namesSkill([picked.parent], picked.skill) ? picked.parent : goalSkills.find(item => namesSkill([item], { name: picked.skill.name, canonicalId: picked.skill.canonicalId }));
  return { key: picked.skill.key, name: picked.skill.name, canonicalId: picked.skill.canonicalId, level: picked.level, target: picked.target ?? match?.competence_target?.level ?? null,
   meaning: match?.competence_target?.explanation, sources: picked.skill.sources, note: picked.skill.note ?? (picked.skill.added ? 'Added in review from your answers.' : null), tasks: (match?.learning_items ?? []).map(item => ({ name: item.name, reason: item.reason })) };
 }, [picked, goalSkills]);

 const chip = (entry: Entry, minor: boolean) => {
  const label = entry.missing ? `${entry.skill.label}, not in your skills yet${entry.target != null ? `, target ${entry.target}` : ''}` : entry.level == null ? (entry.target != null ? `Not rated, target ${entry.target}` : 'Not rated') : entry.target != null ? `Level ${entry.level} out of 10, target ${entry.target}` : `Level ${entry.level} out of 10${entry.own ? ', your rating' : ''}`;
  return <li key={entry.skill.key}><button type="button" className={`ws-sc${entry.missing ? ' missing' : ''}${minor ? ' minor' : ''}${importance(entry) ? ` ${importance(entry)}` : ''}`} aria-label={`${entry.skill.name}, ${label}. Talk it through`} onClick={() => setTalking(entry.skill.key)}>
   {entry.skill.name}
   <span className={`lv ${entry.level == null ? 'unrated' : targetGap(entry.level, entry.target) ?? ''}`.trimEnd()}>{entry.missing ? '–' : entry.level ?? '?'}{entry.target != null && <small>/{entry.target}</small>}</span>
  </button></li>;
 };
 return <section className="ws-panel" id="your-skills" aria-labelledby="skills-title">
  <h2 id="skills-title">Your skills</h2>
  <p className="ws-lead">The first number is your level out of 10; the number after the slash is the target your goal sets.{compared ? '' : ' Evaluate your skills with your Career Goal to see your levels against its targets.'} Tap a skill to talk it through.</p>
  {hasRelevant && hidden > 0 && <div className="ws-filter"><button type="button" className="ws-showall" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>{showAll ? 'Show fewer' : `Show all skills (${hidden} more)`}</button></div>}
  {hasRelevant && <div className="ws-key" aria-hidden="true" style={{ marginTop: 0 }}>
   <span><i className="ws-key-pill important"/>Important skill</span>
   <span><i className="ws-key-pill nice"/>Nice to have</span>
   {missing.length + parts.length > 0 && <span><i className="ws-key-pill missing"/>Expected by your goal, not in your skills yet</span>}
   <span><b className="ws-key-lv">2<small>/8</small></b>Your level / the role&apos;s target:</span>
   <span><b className="ws-key-lv met">8<small>/8</small></b>at or above</span>
   <span><b className="ws-key-lv near">6<small>/8</small></b>within 2</span>
   <span><b className="ws-key-lv far">3<small>/8</small></b>further away</span>
  </div>}
  {groups.map(group => <section key={group.name} aria-label={group.name}>
   <h3 className="ws-group-t">{group.name}</h3>
   <ul className="ws-sc-list">{group.items.map(entry => chip(entry, compared && !importance(entry)))}</ul>
  </section>)}
  <TalkItThrough skill={talkSkill} onClose={() => setTalking(null)} token={token} goalLabel={goalRole} comparison={comparison} onRoadmapChanged={onChanged}/>
 </section>;
}

"use client";
import { useEffect, useMemo, useState } from 'react';
import { levelStatus, namesSkill } from '@/features/assessment/levels';
import { TalkItThrough, type TalkSkill } from '@/features/assessment/talk-it-through';
import type { Comparison } from '@/features/assessment/comparison';
import type { Assessment } from '@/features/roadmap/types';
import { skillRatings, ratingKey, type SkillRatings } from '@/lib/api/assessment';
import type { CurrentGoal } from '@/lib/api/career';
import type { Section } from '@/lib/api/workspace-summary';
import { groupSkills } from '@/lib/skill-groups';
import { evaluatedSkill, skillStatus, type Relevance, type Skill, type Status } from './skill-cards';

type Entry = { skill: Skill; status: Status; level: number | null; target: number | null; own: boolean };
const goalRelevant = (relevance: Relevance | null) => relevance === 'high' || relevance === 'medium';

/**
 * The person's skills as chips. Skills the career goal needs come first with their level against the role's target;
 * the rest sit behind "Show all skills". Levels are read from the saved evaluation and the person's own ratings.
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
 const entries = useMemo(() => skills.map((skill): Entry => {
  const status = skillStatus(skill, assessment), self = own.get(ratingKey(skill));
  const level = skill.ownLevel?.level ?? (status.state === 'score' ? status.score ?? null : self ?? null);
  return { skill, status, level, target: goalRelevant(status.relevance) ? status.need ?? null : null, own: skill.ownLevel?.level == null && status.state !== 'score' && self != null };
 }), [skills, assessment, own]);
 const compared = !!assessment;
 const goalSkills = goal.status === 'ready' ? goal.data.goal?.skills ?? [] : [];
 /* How much the Career Goal needs a skill: its stated priority, or the evaluation's relevance when the goal doesn't list it. Works before any evaluation. */
 const importance = (entry: Entry): 'important' | 'nice' | null => {
  const match = goalSkills.find(item => namesSkill([item], { name: entry.skill.name, canonicalId: entry.skill.canonicalId }));
  if (match) return match.priority === 'required' || match.priority === 'preferred' ? 'important' : match.priority === 'conflicting' ? null : 'nice';
  return entry.status.relevance === 'high' ? 'important' : entry.status.relevance === 'medium' ? 'nice' : null;
 };
 // Essential first, then important, then nice to have, then everything else.
 const rank = (entry: Entry) => {
  const match = goalSkills.find(item => namesSkill([item], { name: entry.skill.name, canonicalId: entry.skill.canonicalId }));
  if (match) return match.priority === 'required' ? 0 : match.priority === 'preferred' ? 1 : match.priority === 'conflicting' ? 4 : 2;
  return entry.status.relevance === 'high' ? 0 : entry.status.relevance === 'medium' ? 2 : 4;
 };
 const relevant = compared ? entries.filter(entry => goalRelevant(entry.status.relevance)).sort((a, b) => rank(a) - rank(b) || Number(b.status.relevance === 'high') - Number(a.status.relevance === 'high') || a.skill.name.localeCompare(b.skill.name)) : [];
 // The strongest evidence comes first within each category.
 const strongest = (a: Entry, b: Entry) => b.skill.step - a.skill.step || Number(b.skill.established) - Number(a.skill.established) || a.skill.name.localeCompare(b.skill.name);
 const rest = (compared ? entries.filter(entry => !goalRelevant(entry.status.relevance)) : entries).sort(strongest);
 // The category view: skills the goal needs first, most important first, then the rest by strength. The filter keeps only the relevant ones.
 const [onlyRelevant, setOnlyRelevant] = useState(false);
 const hasRelevant = entries.some(entry => importance(entry));
 const filtering = onlyRelevant && hasRelevant, expanded = filtering || showAll || !compared;
 const listed = (filtering || showAll ? entries : rest).filter(entry => !filtering || importance(entry)).sort((a, b) => rank(a) - rank(b) || strongest(a, b));
 const groups = groupSkills(listed, entry => entry.skill.name, { ...categories, ...Object.fromEntries(skills.flatMap(skill => { const judged = evaluatedSkill(skill, assessment); return judged ? [[skill.name, judged.category]] : []; })) });
 const picked = entries.find(entry => entry.skill.key === talking);
 const talkSkill = useMemo((): TalkSkill | null => {
  if (!picked) return null;
  const match = goalSkills.find(item => namesSkill([item], { name: picked.skill.name, canonicalId: picked.skill.canonicalId }));
  return { key: picked.skill.key, name: picked.skill.name, canonicalId: picked.skill.canonicalId, level: picked.level, target: picked.target ?? match?.competence_target?.level ?? null,
   meaning: match?.competence_target?.explanation, sources: picked.skill.sources, note: picked.skill.note ?? (picked.skill.added ? 'Added in review from your answers.' : null), tasks: (match?.learning_items ?? []).map(item => ({ name: item.name, reason: item.reason })) };
 }, [picked, goalSkills]);

 const chip = (entry: Entry, minor: boolean) => {
  const status = levelStatus(entry.level, entry.target);
  const label = entry.level == null ? 'Not rated' : entry.target != null ? `Level ${entry.level} out of 10, target ${entry.target}` : `Level ${entry.level} out of 10${entry.own ? ', your rating' : ''}`;
  return <li key={entry.skill.key}><button type="button" className={`ws-sc${minor ? ' minor' : ''}${importance(entry) ? ` ${importance(entry)}` : ''}`} aria-label={`${entry.skill.name}, ${label}. Talk it through`} onClick={() => setTalking(entry.skill.key)}>
   {entry.skill.name}
   <span className={`lv ${entry.level == null ? 'unrated' : minor || entry.target == null ? 'neutral' : status}`}>{entry.level ?? '?'}{entry.target != null && <small>/{entry.target}</small>}</span>
  </button></li>;
 };
 return <section className="ws-panel" id="your-skills" aria-labelledby="skills-title">
  <h2 id="skills-title">Your skills</h2>
  <p className="ws-lead">The number is your level out of 10.{compared ? ' For skills your goal needs, the colour shows how close you are to its target.' : ' Evaluate your skills with your Career Goal to see how close you are to its targets.'} Tap a skill to talk it through.</p>
  {hasRelevant && <div className="ws-filter" role="group" aria-label="Filter skills"><button type="button" className={`ws-showall${onlyRelevant ? ' on' : ''}`} aria-pressed={onlyRelevant} onClick={() => setOnlyRelevant(value => !value)}>{onlyRelevant ? 'Showing only skills relevant to your goal' : 'Show only skills relevant to your goal'}</button></div>}
  {hasRelevant && <div className="ws-key" aria-hidden="true" style={{ marginTop: 0 }}>
   {compared && relevant.length > 0 && <>
    <span><i style={{ width: 18, height: 10, borderRadius: 5, background: 'var(--mint)' }}/>Ready</span>
    <span><i style={{ width: 18, height: 10, borderRadius: 5, background: 'var(--ws-amber-bg)', outline: '1px solid var(--ws-amber)' }}/>Getting there</span>
    <span><i style={{ width: 18, height: 10, borderRadius: 5, background: 'var(--ws-soft)', outline: '1px solid var(--ws-line)' }}/>To build</span>
   </>}
   <span><i style={{ width: 18, height: 10, borderRadius: 5, background: 'var(--skill-important)' }}/>Important skill</span>
   <span><i style={{ width: 18, height: 10, borderRadius: 5, background: 'var(--skill-nice)' }}/>Nice to have</span>
   {compared && relevant.length > 0 && <span>“/8” is the target for this role</span>}
  </div>}
  {compared && !expanded && <>
   <h3 className="ws-group-t">{goalRole ? `Relevant to ${goalRole}` : 'Relevant to your goal'}</h3>
   {relevant.length ? <ul className="ws-sc-list">{relevant.map(entry => chip(entry, false))}</ul> : <p className="ws-sub">None of your skills match what this goal needs yet.</p>}
  </>}
  {expanded && groups.map(group => <section key={group.name} aria-label={group.name}>
   <h3 className={`ws-group-t${compared ? ' sub' : ''}`}>{group.name}</h3>
   <ul className="ws-sc-list">{group.items.map(entry => chip(entry, compared && !importance(entry)))}</ul>
  </section>)}
  {compared && !filtering && rest.length > 0 && <button type="button" className="ws-showall" aria-expanded={showAll} onClick={() => setShowAll(value => !value)}>{showAll ? 'Show fewer' : `Show all skills (${rest.length} more)`}</button>}
  <TalkItThrough skill={talkSkill} onClose={() => setTalking(null)} token={token} goalLabel={goalRole} comparison={comparison} onRoadmapChanged={onChanged}/>
 </section>;
}

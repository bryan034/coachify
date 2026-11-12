"use client";
import { useMemo, useState } from 'react';
import { Icon } from '@/components/ui/icon';
import { InfoTip } from '@/components/ui/workspace-ui';
import type { CvDetail, CvItem } from './types';
import '@/styles/skills.css';

type Origin = 'cv' | 'add' | 'rem' | 'skip';
type ResultSkill = { id: string; name: string; origin: Origin; itemIds: string[]; category: string; subgroup: string; note?: string };
type Sort = 'category' | 'origin';

const ORIGIN: Record<Origin, { label: string; fallback: string }> = {
 cv: { label: 'In your CV', fallback: 'Confirmed in your review.' },
 add: { label: 'Added in review', fallback: 'Added from your answers.' },
 rem: { label: 'Removed in review', fallback: 'Removed after your answers.' },
 skip: { label: 'From a skipped topic', fallback: 'Not reviewed. You skipped this topic, so elo uses your CV as written.' },
};
const ORIGIN_ORDER: Origin[] = ['cv', 'add', 'rem', 'skip'];
const ORIGIN_HINT: Record<Origin, string> = {
 cv: 'Confirmed in your review', add: 'Not in your CV, from your answers', rem: 'Taken out after your answers', skip: 'Your CV as written',
};
const KIND_ORDER: CvItem['kind'][] = ['experience', 'project', 'education'];
const KIND_LABEL: Record<string, string> = { experience: 'Work and experience', project: 'Projects', education: 'Education' };

function shortDate(value?: string | null) {
 if (!value) return '';
 const [year, month] = value.split('-');
 const name = month ? ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(month) - 1] : '';
 return name ? `${name} ${year}` : year;
}
function when(item: CvItem) {
 const start = shortDate(item.start_date), end = item.ongoing ? 'now' : shortDate(item.end_date);
 if (start && end) return `${start} to ${end}`;
 return start || end || 'Dates not stated';
}
const longDate = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });

function useResults(cv: CvDetail) {
 return useMemo(() => {
  const skipped = new Set<string>(), answered = new Set<string>();
  cv.clarifications.forEach(c => (c.status === 'skipped' ? skipped : c.status === 'answered' ? answered : new Set<string>()).add(c.item_id));
  const topicSkipped = (itemId: string) => skipped.has(itemId) && !answered.has(itemId);
  const review = cv.review_summary;
  const groups = cv.skill_groups ?? {}, subgroups = cv.skill_subgroups ?? {};
  const seen = new Set<string>();
  const skills: ResultSkill[] = cv.skills.map(skill => {
   seen.add(skill.name.toLowerCase());
   const added = review?.added_skill_ids.includes(skill.skill_id);
   const sourceItems = [...new Set([...skill.item_ids, ...cv.items.filter(item => item.skill_ids.includes(skill.skill_id)).map(item => item.id)])]
    .filter(id => cv.items.some(item => item.id === id && item.kind !== 'skill'));
   const everySourceSkipped = sourceItems.length > 0 && sourceItems.every(topicSkipped);
   return {
    id: skill.skill_id, name: skill.name, itemIds: sourceItems, note: review?.skill_notes[skill.skill_id],
    origin: added ? 'add' : everySourceSkipped ? 'skip' : 'cv',
    category: groups[skill.skill_id] ?? skill.category ?? 'Other', subgroup: subgroups[skill.skill_id] ?? '',
   };
  });
  // Skills you removed in review are no longer extracted, so they come back from the item list.
  cv.items.filter(item => item.kind === 'skill' && item.removed && !seen.has(item.title.toLowerCase())).forEach(item => skills.push({
   id: item.id, name: item.title, itemIds: [item.id], origin: 'rem', category: 'Removed', subgroup: '', note: review?.skill_notes[item.id],
  }));
  const experiences = cv.items.filter(item => item.kind !== 'skill');
  return { skills, experiences, topicSkipped, answered: review?.answered_questions ?? answered.size, skippedCount: skipped.size };
 }, [cv]);
}

export function ExtractedResults({ cv, onBack, children }: { cv: CvDetail; onBack: () => void; children?: React.ReactNode }) {
 const { skills, experiences, topicSkipped, answered, skippedCount } = useResults(cv);
 const [sort, setSort] = useState<Sort>('category');
 const [pickedId, setPickedId] = useState<string>(skills[0]?.id ?? '');
 const picked = skills.find(skill => skill.id === pickedId) ?? skills[0];
 const added = skills.filter(skill => skill.origin === 'add').length, removed = skills.filter(skill => skill.origin === 'rem').length;
 const fromCv = skills.length - added - removed;
 const items = new Map(cv.items.map(item => [item.id, item]));
 const rows = sort === 'category' ? categoryRows(skills) : ORIGIN_ORDER.map(origin => ({ key: origin, title: ORIGIN[origin].label, sub: ORIGIN_HINT[origin], skills: skills.filter(skill => skill.origin === origin) }));
 const title = cv.display_name ?? cv.file_name;
 return <div className="results">
  <header className="results-head">
   <button type="button" className="results-back" onClick={onBack}><Icon name="chevronLeft"/>Skills Profile</button>
   <div className="ptitle-heading"><h1 tabIndex={-1}>Extracted results</h1><InfoTip label="About Extracted results">What elo read from your CV, shown next to what changed in your review. Read only.</InfoTip></div>
   <p className="results-lead"><strong>{title}</strong>, uploaded {longDate(cv.created_at)}. elo read <strong>{fromCv} skills</strong> from <strong>{experiences.length} experiences</strong>.{(added || removed) ? <> Your review added {added} and removed {removed}.</> : null}</p>
  </header>
  {children}
  <section className="card results-strip" aria-label="Review status">
   <Icon name="doc"/><h2>What elo read from your CV</h2><span className="results-readonly">Read only</span>
   <span className="results-strip-meta">{answered} {answered === 1 ? 'question' : 'questions'} answered, {skippedCount} skipped</span>
  </section>
  <div className="results-body">
   <section className="card results-skills" aria-labelledby="results-skills-h">
    <div className="results-skills-head">
     <h2 id="results-skills-h">{sort === 'category' ? 'Skills by category' : 'Skills by where they came from'}</h2>
     <div role="group" aria-label="Sort skills by" className="results-sort"><span>Sort by</span>
      <div>{(['category', 'origin'] as Sort[]).map(option => <button key={option} type="button" aria-pressed={sort === option} onClick={() => setSort(option)}>{option === 'category' ? 'Category' : 'Where it came from'}</button>)}</div>
     </div>
    </div>
    <p className="results-legend"><span>Where it came from:</span>{ORIGIN_ORDER.map(origin => <span key={origin}><i className={`results-key is-${origin}`}/>{origin === 'skip' ? 'Skipped topic, CV as written' : ORIGIN[origin].label}</span>)}</p>
    {skills.length ? rows.filter(row => row.skills.length).map(row => <div className="results-row" key={row.key}>
     <div><p>{row.title}</p>{row.sub && <p>{row.sub}</p>}</div>
     <div className="results-chips">{row.skills.map(skill => <button key={skill.id} type="button" className={`results-skill is-${skill.origin}`} aria-pressed={picked?.id === skill.id} onClick={() => setPickedId(skill.id)}>{skill.origin === 'add' ? '+ ' : ''}{skill.name}</button>)}</div>
    </div>) : <p className="results-empty">No skills were found in this CV.</p>}
   </section>
   {picked && <aside className="card results-detail" aria-labelledby="results-detail-h">
    <h2 id="results-detail-h">{picked.name}</h2>
    <span className={`results-skill is-${picked.origin} is-label`}>{ORIGIN[picked.origin].label}</span>
    <div>
     <p className="results-label">{picked.origin === 'add' ? 'From your answers about' : 'Where it appears in your CV'}</p>
     <ul>{picked.itemIds.map(id => items.get(id)).filter((item): item is CvItem => Boolean(item) && item!.kind !== 'skill').map(item => <li key={item.id}><strong>{item.title}</strong><span>{picked.origin === 'add' ? 'You described this in your review answers.' : item.description}</span></li>)}</ul>
    </div>
    <div className="results-note"><p className="results-label">In your review</p><p>{picked.note ?? ORIGIN[picked.origin].fallback}</p></div>
   </aside>}
  </div>
  <section className="card results-experiences" aria-labelledby="results-exp-h">
   <h2 id="results-exp-h">Experiences found in your CV</h2>
   {experiences.length ? <div className="results-cols">{KIND_ORDER.map(kind => {
    const list = experiences.filter(item => item.kind === kind);
    return list.length ? <section key={kind}><header><h3>{KIND_LABEL[kind]}</h3><span>{list.length}</span></header>
     {list.map(item => {
      const found = skills.filter(skill => skill.itemIds.includes(item.id) && skill.origin !== 'rem');
      const state = item.removed ? 'Removed' : topicSkipped(item.id) ? 'Skipped' : 'Reviewed';
      return <details key={item.id}><summary>{item.title}<span className={`results-tag is-${state.toLowerCase()}`}>{state}</span></summary>
       <dl><dt>When</dt><dd>{when(item)}</dd><dt>What your CV says</dt><dd>{item.description}</dd><dt>Skills found</dt><dd>{found.length ? found.map(skill => skill.name + (skill.origin === 'add' ? ' (added in review)' : '')).join(', ') : 'None found'}</dd></dl>
      </details>;
     })}
    </section> : null;
   })}</div> : <p className="results-empty">No experiences were found in this CV.</p>}
  </section>
 </div>;
}

function categoryRows(skills: ResultSkill[]) {
 const order: string[] = [];
 skills.forEach(skill => { if (!order.includes(skill.category)) order.push(skill.category); });
 return order.flatMap(category => {
  const inCategory = skills.filter(skill => skill.category === category);
  const subs = [...new Set(inCategory.map(skill => skill.subgroup))];
  return subs.map((sub, index) => ({ key: `${category}:${sub}`, title: index === 0 ? category : '', sub, skills: inCategory.filter(skill => skill.subgroup === sub) }));
 });
}

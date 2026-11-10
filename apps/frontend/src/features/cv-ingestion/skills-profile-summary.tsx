"use client";
import { useComparison, ComparisonPanel } from '@/features/assessment/comparison';
import {SkillBaseline} from './skill-baseline';
import {ReviewEvidence} from './review-evidence';
import {SkillProfile, profileSkillGroups, profileSkillList} from './skill-cards';
import {groupSkills} from '@/lib/skill-groups';
import '@/styles/skills.css';
import type { CvDetail, CvSummary, Declarations, SkillsProfile } from './types';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icon } from '@/components/ui/icon';
import { CardSkeleton } from '@/components/ui/workspace-ui';
import { formatDate } from '@/lib/format';

const labels: Record<string, string> = {education:'Education',work:'Work and internships',project:'Projects',interest:'Interests'};
const cvKind = (kind: string) => kind === 'work' ? 'experience' : kind;
const readable = (value: string) => value.replaceAll('_', ' ');

export function SkillsProfileSummary({token, title, profile, cv, recentReview, declarations, error, upload, build, review, retry, save, saving, saveCv, savingCv, pending, chat, chatOpen=false, cvs=[], activeCvId=null, viewCv, makeActive, removeCv, busy=false}: {
 chat?:()=>void; chatOpen?: boolean; cvs?: CvSummary[]; activeCvId?: string|null; viewCv?: (id: string) => void; makeActive?: (id: string) => void; removeCv?: (cv: CvSummary) => void; busy?: boolean; token?: string; title?: ReactNode; profile: SkillsProfile | null; cv: CvDetail | null; declarations: Declarations | null; error: string;
 recentReview?: CvSummary;
 upload: () => void; build: () => void; review: (id: string) => void; retry: () => void;
 save: () => void; saving: boolean;
 saveCv: () => void; savingCv: boolean;
 pending: boolean;
}) {
 const comparison = useComparison(token, `${cv?.id}:${cv?.effective_version}:${profile?.version}:${declarations?.version}`);
 const skills = profileSkillList(cv, profile, declarations);
 const areas = profile ? Object.entries(labels).filter(([kind]) => !profile.entries.some(entry => entry.kind === kind)) : [];
 const unexplored = areas.filter(([kind]) => !profile?.areas[kind as keyof typeof profile.areas] && !cv?.items.some(item => !item.removed && item.kind === (kind === 'work' ? 'experience' : kind))).map(([, label]) => label);
 const answered = areas.flatMap(([kind, label]) => { const status = profile?.areas[kind as keyof typeof profile.areas]; return status ? [`${label}: ${readable(status)}`] : []; });
 const experience = cv ? cv.items.filter(item => !item.removed && item.kind !== 'skill') : [];
 const hasExperience = experience.length > 0 || Boolean(profile?.entries.length) || answered.length > 0;
 const experiences = experience.length + (profile?.entries.length ?? 0);
 const goalRole = comparison.context?.goal?.role;
 // Same file name = versions of one CV, newest first.
 const families = [...cvs.reduce((map, item) => map.set(item.file_name, [...(map.get(item.file_name) ?? []), item]), new Map<string, CvSummary[]>()).entries()]
  .map(([name, items]) => [name, [...items].sort((x, y) => y.created_at.localeCompare(x.created_at))] as const);
 const versionLabel = (item: CvSummary, items: readonly CvSummary[]) => `${item.display_name ?? item.file_name}${items.length > 1 ? ` · version ${items.length - items.indexOf(item)}` : ''} · ${formatDate(item.created_at)}${item.id === activeCvId ? ' (active)' : ''}`;
 const reviewed = cv ? cv.profile_reviewed_effective_version === cv.effective_version : false;
 const topCategories = groupSkills(skills, skill => skill.name, profileSkillGroups(cv, profile, declarations)).slice(0, 2).map(group => group.name.toLowerCase());
 const understood = cv && cv.status === 'ready' ? [
  experience.length ? `${experience.length} ${experience.length === 1 ? 'experience' : 'experiences'}: ${experience.slice(0, 3).map(item => item.title).join('; ')}${experience.length > 3 ? '; and more' : ''}.` : 'No experiences were found in this CV.',
  cv.skills.length ? `${cv.skills.length} skills${topCategories.length ? `, mostly ${topCategories.join(' and ')}` : ''}.` : '',
 ].filter(Boolean).join(' ') : null;
 return <div className="skills-home">
  <header className="skills-hero skills-hero-compact"><div className="skills-hero-copy">{title}
   {skills.length > 0 && <p className="skills-hero-line"><strong>{skills.length} {skills.length === 1 ? 'skill' : 'skills'}</strong> from <strong>{experiences} {experiences === 1 ? 'experience' : 'experiences'}</strong>{goalRole ? <> · compared with <Link href="/career-goal">{goalRole}</Link></> : null}</p>}
  </div>
  <div className="skills-hero-actions"><button type="button" className="btn ghost" onClick={upload}><Icon name="up"/>Upload new CV</button><button type="button" className="btn pri" aria-expanded={chatOpen} onClick={chat ?? build}>{chatOpen ? 'Close chat' : 'Chat to edit'}</button></div></header>
  {cv && <section className="card skills-cv-card" aria-label="Your CV">
   <div className="skills-cv-switch">
    {cvs.length > 0 ? <label><span>Choose a CV</span><select value={cv.id} disabled={busy} onChange={event => viewCv?.(event.target.value)}>{families.map(([name, items]) => <optgroup key={name} label={name}>{items.map(item => <option key={item.id} value={item.id}>{versionLabel(item, items)}</option>)}</optgroup>)}</select></label> : <strong>{cv.display_name ?? cv.file_name}</strong>}
    {cv.id === activeCvId && <span className="skills-active-chip">Active</span>}
    <span className="skills-cv-actions">
     {makeActive && cv.id !== activeCvId && <button type="button" className="btn ghost sm" disabled={busy || cv.status !== 'ready'} onClick={() => makeActive(cv.id)}>Make active</button>}
     <button type="button" className={`btn sm ${reviewed ? 'ghost' : 'pri'}`} disabled={cv.status === 'failed'} onClick={() => review(cv.id)}>{reviewed ? 'Refine' : cv.status === 'ready' ? 'Continue review' : 'Open review'}</button>
     {cv.status === 'ready' && !reviewed && <button className="btn ghost sm" type="button" disabled={savingCv || pending} onClick={saveCv}>{savingCv ? 'Saving…' : 'Save to Skills Profile'}</button>}
     {removeCv && <button type="button" className="btn ghost sm" disabled={busy} onClick={() => removeCv(cv)}>Delete</button>}
    </span>
   </div>
   {cv.status !== 'ready' ? <p className="small">{cv.status === 'failed' ? 'Processing failed. Manage saved CVs to retry.' : 'Your CV is still processing. Open its review to see progress.'}</p> : understood && <div className="skills-understood"><p className="briefing-detail-label">What elo understood from your CV</p><p>{understood}</p></div>}
  </section>}
  {<div className="skills-entry-actions">{recentReview && recentReview.id !== cv?.id && <button type="button" className="btn ghost sm" onClick={() => review(recentReview.id)}>Review {recentReview.display_name ?? recentReview.file_name}</button>}<button type="button" className="btn ghost sm" onClick={build}>{profile?.status === 'draft' ? 'Continue building your profile through chat' : profile?.entries.length ? 'Update through chat' : 'Build through chat, no CV needed'}</button></div>}
  <ComparisonPanel comparison={comparison}/>
  <section className="skills-summary" id="your-skills" aria-label="Skills profile summary">
   {profile && profile.status !== 'empty' && <p className="small skills-saved-state">{profile.status === 'saved' ? 'Saved profile' : 'Draft saved'}</p>}
   {error && <div role="alert" className="cv-error"><p>{error}</p><button type="button" className="btn ghost sm" onClick={retry}>Retry skills profile</button></div>}
   {pending&&<p role="status" className="cv-warning">Finish or cancel the pending conversation updates before saving your profile. You can review your current saved draft below.</p>}
   {!profile && !error && <CardSkeleton label="Loading your skills profile…"/>}
   {profile && !profile.entries.length && !cv && !declarations?.declarations.length && <p className="skills-empty">Start with your CV or a conversation. Your experience and skills will appear here as you build your profile.</p>}
   {profile?.status === 'draft'&&<div className="skills-profile-save"><p className="small">Review the details below. You can save a partial profile; unknown details stay uncertain.</p><button className="btn pri" type="button" disabled={saving||pending} onClick={save}>{saving?'Saving profile…':'Save profile'}</button></div>}
   {skills.length>0&&<SkillProfile skills={skills} categories={profileSkillGroups(cv, profile, declarations)} subcategories={{...declarations?.skill_subgroups,...profile?.skill_subgroups,...cv?.skill_subgroups}} comparison={comparison.result?.inputs?.cv_id && comparison.result.inputs.cv_id !== cv?.id ? null : comparison.result}/>}
   {skills.length===0&&cv&&<p className="skills-empty">No skills have been saved from this CV yet. They will appear here once they are available.</p>}
   {hasExperience&&<section className="skills-experience" id="your-experience" aria-labelledby="your-experience-title">
    <h2 id="your-experience-title">Experience behind your skills</h2>
    <div className="skills-experience-columns">{Object.entries(labels).map(([kind,label])=>{
     const items=cv?experience.filter(item=>item.kind===cvKind(kind)):[];
     const entries=profile?.entries.filter(entry=>entry.kind===kind)??[];
     if(!items.length&&!entries.length)return null;
     return <section className="skills-experience-column" key={kind}><header><h3>{label}</h3><span>{items.length+entries.length}</span></header>
      {items.map(item=><details className="skills-background" key={item.id}><summary>{item.title}</summary><dl className="skills-facts"><div><dt>Role or project</dt><dd><strong>{item.title}</strong></dd></div><div><dt>What you did</dt><dd>{item.description}</dd></div><div><dt>Skills used</dt><dd>{cv!.skills.filter(skill=>skill.item_ids.includes(item.id)).map(skill=>skill.name).join(', ')||'Not recorded'}</dd></div></dl>{cv!.clarifications.filter(q=>q.item_id===item.id&&q.status!=='unanswered'&&!q.reconciliation_required).map(q=><div key={q.id}><p className="small">{q.question}</p><blockquote>{q.answer??'Skipped. This detail remains unknown.'}</blockquote>{q.interpretation_status==='failed'&&<p className="small">Interpretation needs attention before saving this review.</p>}</div>)}</details>)}
      {entries.map(entry=><article className="skills-background" key={entry.id}><h4>{entry.title}</h4><dl className="skills-facts">{Object.entries(entry.fields).map(([field,value])=><div key={field}><dt>{readable(field)}</dt><dd>{value.value ?? readable(value.status)}</dd></div>)}</dl></article>)}
     </section>;
    })}</div>
    {(unexplored.length>0||answered.length>0)&&<p className="small skills-areas-note">{[unexplored.length?`Not yet explored: ${unexplored.join(', ')}.`:'',answered.length?`${answered.join('; ')}.`:''].filter(Boolean).join(' ')} You can add more through chat.</p>}
   </section>}
  </section>
 </div>;
}

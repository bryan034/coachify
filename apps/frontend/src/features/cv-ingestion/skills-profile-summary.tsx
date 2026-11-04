"use client";
import {SkillBaseline} from './skill-baseline';
import {ReviewEvidence} from './review-evidence';
import {SkillProfile, profileSkillGroups, profileSkillList} from './skill-cards';
import type { CvDetail, Declarations, SkillsProfile } from './types';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icon } from '@/components/ui/icon';

const labels: Record<string, string> = {work:'Work and internships',project:'Projects',education:'Education',interest:'Interests'};
const readable = (value: string) => value.replaceAll('_', ' ');

export function SkillsProfileSummary({title, profile, cv, declarations, error, upload, build, review, retry, save, saving, saveCv, savingCv, pending}: {
 title?: ReactNode; profile: SkillsProfile | null; cv: CvDetail | null; declarations: Declarations | null; error: string;
 upload: () => void; build: () => void; review: (id: string) => void; retry: () => void;
 save: () => void; saving: boolean;
 saveCv: () => void; savingCv: boolean;
 pending: boolean;
}) {
 const skills = profileSkillList(cv, profile, declarations);
 const areas = profile ? Object.entries(labels).filter(([kind]) => !profile.entries.some(entry => entry.kind === kind)) : [];
 const unexplored = areas.filter(([kind]) => !profile?.areas[kind as keyof typeof profile.areas] && !cv?.items.some(item => !item.removed && item.kind === (kind === 'work' ? 'experience' : kind))).map(([, label]) => label);
 const answered = areas.flatMap(([kind, label]) => { const status = profile?.areas[kind as keyof typeof profile.areas]; return status ? [`${label}: ${readable(status)}`] : []; });
 const experience = cv ? cv.items.filter(item => !item.removed && item.kind !== 'skill') : [];
 const hasExperience = experience.length > 0 || Boolean(profile?.entries.length) || answered.length > 0;
 return <div className="skills-home">
  <header className="skills-hero"><div className="skills-hero-copy">{title}
  <p className="skills-home-intro">What you can do and the experience behind it. elo uses this evidence to assess how your skills match job applications. Unknown details can stay unknown.</p>
  <div className={`skills-entry-actions${skills.length ? ' compact' : ''}`}>
   <button type="button" className="skills-entry-action" onClick={upload}><Icon name="up"/><span><strong>Upload your CV</strong><span>Drop a PDF or DOCX to start reviewing your experience and contributions.</span></span></button>
   <button type="button" className="skills-entry-action" onClick={build}><Icon name="chat"/><span><strong>{profile?.status === 'draft' ? 'Continue building your profile' : profile?.entries.length ? 'Update through chat' : 'Build through chat'}</strong><span>No CV needed. Explore your work, projects, education and interests with guided questions.</span></span></button>
  </div>
  </div></header>
  <nav className="skills-jump-links" aria-label="Skills Profile sections"><a href="#your-skills">Skills you have</a>{hasExperience&&<a href="#your-experience">Experience</a>}<a href="#your-cvs">Your CVs</a></nav>
  <section className="skills-summary" id="your-skills" aria-label="Skills profile summary">
   <div className="skills-summary-heading"><h2>Skills you have</h2><Link className="small text-link" href="/career-goal">Skills your goal needs</Link><span className="pill n">{profile?.status === 'saved' ? 'Saved profile' : profile?.status === 'draft' ? 'Draft saved' : cv?.profile_reviewed_effective_version === cv?.effective_version && cv ? 'Saved CV profile' : cv ? 'CV available' : 'Not started'}</span></div>
   {error && <div role="alert" className="cv-error"><p>{error}</p><button type="button" className="btn ghost sm" onClick={retry}>Retry skills profile</button></div>}
   {pending&&<p role="status" className="cv-warning">Finish or cancel the pending conversation updates before saving. You can review your current saved draft below.</p>}
   {!profile && !error && <p role="status">Loading your skills profile…</p>}
   {profile && !profile.entries.length && !cv && !declarations?.declarations.length && <p className="skills-empty">Start with your CV or a conversation. Your experience and skills will appear here as you build your profile.</p>}
   {profile?.status === 'draft'&&<div className="skills-profile-save"><p className="small">Review the details below. You can save a partial profile; unknown details stay uncertain.</p><button className="btn pri" type="button" disabled={saving||pending} onClick={save}>{saving?'Saving profile…':'Save profile'}</button></div>}
   {skills.length>0&&<SkillProfile skills={skills} categories={profileSkillGroups(cv, profile, declarations)}/>}
   {skills.length===0&&cv&&<p className="skills-empty">No skills have been saved from this CV yet. They will appear here once they are available.</p>}
   {skills.length>0&&<p className="small skills-summary-note">Levels come from your CV and review answers; practical competence has not been tested. A missing detail is uncertain; it does not mean a skill is absent. Job-specific evaluation happens against your chosen role.</p>}
   {cv && <article className="skills-cv-summary"><div><h3>{(cv.display_name??cv.file_name)}</h3><p className="small">{cv.status !== 'ready' ? 'Processing must finish before review.' : cv.profile_reviewed_effective_version === cv.effective_version ? 'Reviewed CV profile' : 'Ready for guided review. Unanswered details remain uncertain when you save.'}</p></div><div className="skills-cv-actions"><button type="button" className={`btn sm ${cv.status==='ready'&&cv.profile_reviewed_effective_version!==cv.effective_version?'ghost':'pri'}`} disabled={cv.status !== 'ready'} onClick={()=>review(cv.id)}>Review CV</button>{cv.status==='ready'&&cv.profile_reviewed_effective_version!==cv.effective_version&&<button className="btn pri sm" type="button" disabled={savingCv||pending} onClick={saveCv}>{savingCv?'Saving CV profile…':'Save CV profile'}</button>}</div></article>}
   {hasExperience&&<section className="skills-experience" id="your-experience" aria-labelledby="your-experience-title">
    <h2 id="your-experience-title">Experience behind your skills</h2>
    {cv&&experience.map(item=><details className="skills-background" key={item.id}><summary>{item.title}<span className="small"> {item.kind}</span></summary><p className="cv-copy">{item.description}</p><ReviewEvidence facts={item.review_evidence}/><SkillBaseline estimates={cv.skill_estimates?.filter(estimate=>estimate.item_id===item.id)}/>{cv.clarifications.filter(q=>q.item_id===item.id&&q.status!=='unanswered'&&!q.reconciliation_required).map(q=><div key={q.id}><p className="small">{q.question}</p><blockquote>{q.answer??'Skipped. This detail remains unknown.'}</blockquote>{q.interpretation_status==='failed'&&<p className="small">Interpretation needs attention before saving this review.</p>}</div>)}</details>)}
    {profile&&Object.entries(labels).map(([kind,label])=>{const entries=profile.entries.filter(entry=>entry.kind===kind);return entries.length?<section className="skills-background" key={kind}><h3>{label}</h3>{entries.map(entry=><article key={entry.id}><h4>{entry.title}</h4><dl className="skills-facts">{Object.entries(entry.fields).map(([field,value])=><div key={field}><dt>{readable(field)}</dt><dd>{value.value ?? readable(value.status)}</dd></div>)}</dl></article>)}</section>:null;})}
    {(unexplored.length>0||answered.length>0)&&<p className="small skills-areas-note">{[unexplored.length?`Not yet explored: ${unexplored.join(', ')}.`:'',answered.length?`${answered.join('; ')}.`:''].filter(Boolean).join(' ')} You can add more through chat.</p>}
   </section>}
  </section>
 </div>;
}

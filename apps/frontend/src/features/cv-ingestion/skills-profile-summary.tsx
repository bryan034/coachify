"use client";
import { announceInputsChanged, useComparison } from '@/features/assessment/comparison';
import { EvaluateBanner } from '@/features/assessment/evaluate-banner';
import {profileSkillGroups, profileSkillList} from './skill-cards';
import {SkillsOverview} from './skills-overview';
import {loadGoal, useSection} from '@/lib/api/workspace-summary';
import {PageFlow} from '@/components/ui/page-flow';
import {groupSkills} from '@/lib/skill-groups';
import '@/styles/skills.css';
import '@/styles/workspace-pages.css';
import type { CvDetail, CvSummary, Declarations, SkillsProfile } from './types';
import Link from 'next/link';
import { useEffect, useRef, type ReactNode } from 'react';
import { Icon } from '@/components/ui/icon';
import { CardSkeleton } from '@/components/ui/workspace-ui';
import { dateSpan } from './dates';
import { ReviewComplete, ReviewNotFinished, useReviewTopics } from './skills-states';

const labels: Record<string, string> = {education:'Education',work:'Work and internships',project:'Projects',interest:'Interests'};
const cvKind = (kind: string) => kind === 'work' ? 'experience' : kind;
const readable = (value: string) => value.replaceAll('_', ' ');

export function SkillsProfileSummary({token, title, profile, cv, recentReview, declarations, error, upload, build, review, retry, save, saving, saveCv, savingCv, pending, chat, chatOpen=false, firstUpload=false, cvs=[], activeCvId=null, viewCv, makeActive, removeCv, busy=false, uploadPanel, onSkillsChanged}: {
 uploadPanel?: ReactNode; onSkillsChanged?: () => void;
 chat?:()=>void; chatOpen?: boolean; firstUpload?: boolean; cvs?: CvSummary[]; activeCvId?: string|null; viewCv?: (id: string) => void; makeActive?: (id: string) => void; removeCv?: (cv: CvSummary) => void; busy?: boolean; token?: string; title?: ReactNode; profile: SkillsProfile | null; cv: CvDetail | null; declarations: Declarations | null; error: string;
 recentReview?: CvSummary;
 upload: () => void; build: () => void; review: (id: string) => void; retry: () => void;
 save: () => void; saving: boolean;
 saveCv: () => void; savingCv: boolean;
 pending: boolean;
}) {
 const comparison = useComparison(token, `${cv?.id}:${cv?.effective_version}:${profile?.version}:${declarations?.version}`);
 const goalSection = useSection(loadGoal, token);
 const skills = profileSkillList(cv, profile, declarations);
 const areas = profile ? Object.entries(labels).filter(([kind]) => !profile.entries.some(entry => entry.kind === kind)) : [];
 const unexplored = areas.filter(([kind]) => !profile?.areas[kind as keyof typeof profile.areas] && !cv?.items.some(item => !item.removed && item.kind === (kind === 'work' ? 'experience' : kind))).map(([, label]) => label);
 const answered = areas.flatMap(([kind, label]) => { const status = profile?.areas[kind as keyof typeof profile.areas]; return status ? [`${label}: ${readable(status)}`] : []; });
 const experience = cv ? cv.items.filter(item => !item.removed && item.kind !== 'skill') : [];
 const hasExperience = experience.length > 0 || Boolean(profile?.entries.length) || answered.length > 0;
 const experiences = experience.length + (profile?.entries.length ?? 0);
 const goalRole = comparison.context?.goal?.role;
 const reviewed = cv ? cv.profile_reviewed_effective_version === cv.effective_version : false;
 const topCategories = groupSkills(skills, skill => skill.name, profileSkillGroups(cv, profile, declarations)).slice(0, 2).map(group => group.name.toLowerCase());
 const understood = cv && cv.status === 'ready' ? [
  experience.length ? `${experience.length} ${experience.length === 1 ? 'experience' : 'experiences'}: ${experience.slice(0, 3).map(item => item.title).join('; ')}${experience.length > 3 ? '; and more' : ''}.` : 'No experiences were found in this CV.',
  cv.skills.length ? `${cv.skills.length} skills${topCategories.length ? `, mostly ${topCategories.join(' and ')}` : ''}.` : '',
 ].filter(Boolean).join(' ') : null;
 const notFinished = Boolean(cv && cv.status === 'ready' && !reviewed && !firstUpload);
 const reviewTopics = useReviewTopics(token, notFinished ? cv!.id : null, `${cv?.effective_version}:${cv?.updated_at}:${pending}`);
 // Every topic is covered but the CV was never marked reviewed (e.g. finished before this was automatic): mark it once.
 const topicList = reviewTopics?.topics ?? [];
 const allCovered = topicList.length > 0 && topicList.every(topic => ['reviewed', 'reviewed_with_gaps', 'deferred'].includes(topic.status));
 // A finished review rates the new skills: let the automatic skill-gap update see it.
 const reviewedKey = reviewed ? `${cv?.id}:${cv?.effective_version}` : '';
 useEffect(() => { if (reviewedKey) announceInputsChanged(); }, [reviewedKey]);
 const autoSaved = useRef('');
 useEffect(() => {
  if (!notFinished || !cv || !allCovered || pending || savingCv || busy || autoSaved.current === `${cv.id}:${cv.effective_version}`) return;
  autoSaved.current = `${cv.id}:${cv.effective_version}`;
  saveCv();
 }, [notFinished, cv, allCovered, pending, savingCv, busy, saveCv]);
 if (notFinished && cv) return <div className="skills-home skills-unfinished-page"><header className="skills-hero skills-hero-compact"><div className="skills-hero-copy is-stacked">{title}<p className="skills-hero-line">Your skills appear here once your CV review is finished.</p></div></header>
  {error && <div role="alert" className="cv-error"><p>{error}</p><button type="button" className="btn ghost sm" onClick={retry}>Retry skills profile</button></div>}
  <ReviewNotFinished cv={cv} topics={reviewTopics?.topics ?? null} goalRole={goalRole} review={() => review(cv.id)} saveCv={saveCv} savingCv={savingCv} pending={pending} upload={upload} chat={build}/></div>;
 if (firstUpload) return <div className="skills-home"><header className="skills-hero skills-hero-compact"><div className="skills-hero-copy is-stacked">{title}
  <p className="skills-hero-line">Upload your CV and elo lists your skills and the experience behind each one, then compares them with {goalRole ? <Link href="/career-goal">{goalRole}</Link> : 'your Career Goal'}.</p>
 </div></header></div>;
 const saveDraft = profile?.status === 'draft';
 const columns = Object.entries(labels).map(([kind, label]) => ({ kind, label, items: cv ? experience.filter(item => item.kind === cvKind(kind)) : [], entries: profile?.entries.filter(entry => entry.kind === kind) ?? [] })).filter(column => column.items.length || column.entries.length);
 return <div className="ws-page">
  <ReviewComplete cv={cv && reviewed && cv.status === 'ready' ? cv : null}/>
  <EvaluateBanner comparison={comparison} here="/cv"/>
  <div className="ws-head">
   <div>
    {title}
    {skills.length > 0 && <p className="ws-sum"><b>{skills.length} {skills.length === 1 ? 'skill' : 'skills'}</b> from <b>{experiences} {experiences === 1 ? 'experience' : 'experiences'}</b>{goalRole ? <>, compared with <Link href="/career-goal">{goalRole}</Link></> : null}</p>}
    {profile && profile.status !== 'empty' && <p className="ws-sub">{profile.status === 'saved' ? 'Saved profile' : 'Draft saved'}</p>}
   </div>
   <button type="button" className="ws-btn dark" aria-expanded={chatOpen} onClick={chat ?? build}><Icon name="chat"/>{chatOpen ? 'Close chat' : 'Chat to edit'}</button>
  </div>
  <PageFlow current="/cv">Your skills are measured against your Career Goal. Anything below its target becomes a task in your Roadmap, and finishing tasks raises your levels here.</PageFlow>
  {error && <div role="alert" className="ws-error"><p>{error}</p><button type="button" className="ws-mini" onClick={retry}>Retry skills profile</button></div>}
  {pending && <p role="status" className="ws-sub">Finish or cancel the pending conversation updates before saving your profile. You can review your current saved draft below.</p>}
  {!profile && !error && <CardSkeleton label="Loading your skills profile…"/>}
  {profile && !skills.length && !cv && <p className="ws-empty">Start with your CV or a conversation. Your experience and skills will appear here as you build your profile.</p>}
  {saveDraft && <div className="ws-status"><p><b>Draft saved.</b> Review the details below. You can save a partial profile; unknown details stay uncertain.</p><button className="go" type="button" disabled={saving || pending} onClick={save}>{saving ? 'Saving profile…' : 'Save profile'}</button></div>}
  {skills.length > 0 && <SkillsOverview token={token} skills={skills} categories={profileSkillGroups(cv, profile, declarations)} assessment={comparison.result?.inputs?.cv_id && comparison.result.inputs.cv_id !== cv?.id ? null : comparison.result} comparison={comparison} goal={goalSection.state} goalRole={goalRole} onChanged={onSkillsChanged}/>}
  {skills.length === 0 && cv && <p className="ws-empty">No skills have been saved from this CV yet. They will appear here once they are available.</p>}
  <div className="ws-cv">
   {cv ? <section className="ws-cvcard" aria-label="Your CV">
    <div className="ws-cvtop"><Icon name="doc"/><b>{cv.display_name ?? cv.file_name}</b>{cv.id === activeCvId && <span className="ws-tag">Active</span>}{reviewed && cv.status === 'ready' && <span className="ws-tag grey">Reviewed</span>}</div>
    {cv.status !== 'ready' ? <p className="ws-sub">{cv.status === 'failed' ? 'Processing failed. Manage saved CVs to retry.' : 'Your CV is still processing. Open its review to see progress.'}</p> : understood && <><h3>What elo understood from your CV</h3><p>{understood}</p></>}
    <div className="ws-cvacts">
     {cv.status === 'ready' && <button type="button" className="ws-mini solid" onClick={() => review(cv.id)}>Refine CV</button>}
     {cv.status === 'ready' && viewCv && <button type="button" className="ws-mini" onClick={() => viewCv(cv.id)}>View extracted results</button>}
    </div>
   </section> : <section className="ws-cvcard" aria-label="Your CV"><h3>No CV yet</h3><p>Upload a CV and elo lists your skills and the experience behind each one. Or tell elo about your skills through Chat to edit.</p></section>}
   {uploadPanel}
  </div>
  {(hasExperience || columns.length > 0) && <section className="ws-panel" id="your-experience" aria-labelledby="your-experience-title">
   <h2 id="your-experience-title" style={{ marginBottom: 16 }}>Experience behind your skills</h2>
   <div className="ws-exp">{columns.map(column => <section className="ws-expcol" key={column.kind}>
    <h3>{column.label} <span>{column.items.length + column.entries.length}</span></h3>
    <ul>
     {column.items.map(item => <li key={item.id}><details><summary>{item.title}</summary><dl>{dateSpan(item.start_date, item.end_date, item.ongoing) && <div><dt>Dates</dt><dd>{dateSpan(item.start_date, item.end_date, item.ongoing)}</dd></div>}<div><dt>What you did</dt><dd>{item.description}</dd></div><div><dt>Skills used</dt><dd>{cv!.skills.filter(skill => skill.item_ids.includes(item.id)).map(skill => skill.name).join(', ') || 'Not recorded'}</dd></div>{cv!.clarifications.filter(q => q.item_id === item.id && q.status !== 'unanswered' && !q.reconciliation_required).map(q => <div key={q.id}><dt>{q.question}</dt><dd>{q.answer ?? 'Skipped. This detail remains unknown.'}{q.interpretation_status === 'failed' ? ' Interpretation needs attention before saving this review.' : ''}</dd></div>)}</dl></details></li>)}
     {column.entries.map(entry => <li key={entry.id}><details><summary>{entry.title}</summary><dl>{Object.entries(entry.fields).map(([field, value]) => <div key={field}><dt>{readable(field)}</dt><dd>{value.value ?? readable(value.status)}</dd></div>)}</dl></details></li>)}
    </ul>
   </section>)}</div>
   {(unexplored.length > 0 || answered.length > 0) && <p className="ws-sub" style={{ marginTop: 14 }}>{[unexplored.length ? `Not yet explored: ${unexplored.join(', ')}.` : '', answered.length ? `${answered.join('; ')}.` : ''].filter(Boolean).join(' ')} You can add more through chat.</p>}
  </section>}
  <div className="ws-actions" hidden={!(recentReview && recentReview.id !== cv?.id) && !saveDraft && !profile?.entries.length}>{recentReview && recentReview.id !== cv?.id && <button type="button" className="ws-mini" onClick={() => review(recentReview.id)}>Review {recentReview.display_name ?? recentReview.file_name}</button>}{(saveDraft || !!profile?.entries.length) && <button type="button" className="ws-mini" onClick={build}>{saveDraft ? 'Continue building your profile through chat' : 'Update through chat'}</button>}</div>
 </div>;
}

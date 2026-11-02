"use client";
import type { CvDetail, Declarations, SkillsProfile } from './types';
import { Icon } from '@/components/ui/icon';

const labels: Record<string, string> = {work:'Work and internships',project:'Projects',education:'Education',interest:'Interests'};
const readable = (value: string) => value.replaceAll('_', ' ');

export function SkillsProfileSummary({profile, cv, declarations, error, upload, build, review, retry, save, saving, saveCv, savingCv, pending}: {
 profile: SkillsProfile | null; cv: CvDetail | null; declarations: Declarations | null; error: string;
 upload: () => void; build: () => void; review: (id: string) => void; retry: () => void;
 save: () => void; saving: boolean;
 saveCv: () => void; savingCv: boolean;
 pending: boolean;
}) {
 return <div className="skills-home">
  <div className="skills-home-intro"><h2>Your experience, in focus.</h2><p>Your Skills Profile captures what you can do and the experience behind it. elo uses this evidence to assess how your skills match job applications. Unknown details can stay unknown.</p></div>
  <div className="skills-entry-actions">
   <button type="button" className="skills-entry-action" onClick={upload}><Icon name="up"/><span><strong>Upload your CV</strong><span>Drop a PDF or DOCX, then choose Review CV to work through the details.</span></span></button>
   <button type="button" className="skills-entry-action" onClick={build}><Icon name="chat"/><span><strong>{profile?.status === 'draft' ? 'Continue building your profile' : profile?.entries.length ? 'Update through chat' : 'Build through chat'}</strong><span>No CV needed. Explore your work, projects, education and interests with guided questions.</span></span></button>
  </div>
  <section className="skills-summary" aria-label="Skills profile summary">
   <div className="row between"><h2>Your skills profile</h2><span className="pill n">{profile?.status === 'saved' ? 'Saved profile' : profile?.status === 'draft' ? 'Draft saved' : cv?.profile_reviewed_effective_version === cv?.effective_version && cv ? 'Saved CV profile' : cv ? 'CV available' : 'Not started'}</span></div>
   {error && <div role="alert" className="cv-error"><p>{error}</p><button type="button" className="btn ghost sm" onClick={retry}>Retry skills profile</button></div>}
   {pending&&<p role="status" className="cv-warning">Finish or cancel the pending conversation updates before saving. You can review your current saved draft below.</p>}
   {!profile && !error && <p role="status">Loading your skills profile…</p>}
   {profile && !profile.entries.length && !cv && !declarations?.declarations.length && <p className="skills-empty">Start with your CV or a conversation. Your experience and skills will appear here as you build your profile.</p>}
   {cv && <article className="skills-cv-summary"><div className="row between"><div><h3>{cv.file_name}</h3><p className="small">{cv.status !== 'ready' ? 'Processing must finish before review.' : cv.profile_reviewed_effective_version === cv.effective_version ? 'Reviewed CV profile' : 'Ready for guided review'}</p></div><button type="button" className="btn pri sm" disabled={cv.status !== 'ready'} onClick={()=>review(cv.id)}>Review CV</button></div>
    {cv.skills.length > 0 && <ul className="skills-source-list">{cv.skills.map(skill=><li key={skill.skill_id}><strong>{skill.name}</strong><span>{skill.proficiency ?? 'Level not established'}</span>{skill.sources?.map(source=><details key={source.item_id}><summary>{cv.items.find(i=>i.id===source.item_id)?.title ?? 'Source experience'}</summary><p>{source.attribution === 'unknown' ? 'Personal contribution needs clarification.' : `Contribution: ${source.attribution}. Support: ${source.assistance}.`}</p>{source.evidence.map((e,index)=><blockquote key={`${e.id}:${index}`}>{e.excerpt}</blockquote>)}</details>)}</li>)}</ul>}
    {cv.items.filter(item=>!item.removed&&item.kind!=='skill').map(item=><details className="skills-background" key={item.id}><summary>{item.title}<span className="small"> · {item.kind}</span></summary><p className="cv-copy">{item.description}</p>{cv.clarifications.filter(q=>q.item_id===item.id&&q.status!=='unanswered'&&!q.reconciliation_required).map(q=><div key={q.id}><p className="small">{q.question}</p><blockquote>{q.answer??'Skipped. This detail remains unknown.'}</blockquote>{q.interpretation_status==='failed'&&<p className="small">Interpretation needs attention before saving this review.</p>}</div>)}</details>)}
    {cv.status==='ready'&&cv.profile_reviewed_effective_version!==cv.effective_version&&<div className="skills-profile-save"><p className="small">Review the extracted details and your clarifications. Unanswered details remain uncertain when you save.</p><button className="btn pri" type="button" disabled={savingCv||pending} onClick={saveCv}>{savingCv?'Saving CV profile…':'Save CV profile'}</button></div>}
   </article>}
   {profile && Object.entries(labels).map(([kind,label])=>{
    const entries=profile.entries.filter(entry=>entry.kind===kind),status=profile.areas[kind as keyof typeof profile.areas];
    const inCv=cv?.items.some(item=>!item.removed&&item.kind===(kind==='work'?'experience':kind));
    return <section className="skills-background" key={kind}><h3>{label}</h3>{!entries.length && <p className="small">{status ? `${readable(status)} — no additional experience recorded here.` : inCv ? 'Included in your CV above. You can add more through chat.' : 'Not yet explored.'}</p>}{entries.map(entry=><article key={entry.id}><h4>{entry.title}</h4><dl className="skills-facts">{Object.entries(entry.fields).map(([field,value])=><div key={field}><dt>{readable(field)}</dt><dd>{value.value ?? readable(value.status)}</dd></div>)}</dl>{entry.skills.map(skill=><details className="skills-manual-skill" key={skill.name}><summary>{skill.name}<span className="small">{profile.status==='draft'?'Proposed skill — review before saving':'User-described experience'}</span></summary><p>{skill.description}</p><dl className="skills-facts">{Object.entries(skill.dimensions).map(([field,value])=><div key={field}><dt>{readable(field)}</dt><dd>{value.value ?? readable(value.status)}</dd></div>)}</dl><p className="small">Other dimensions remain unknown until discussed.</p>{skill.evidence.map((e,index)=><blockquote key={index}>{e.quote}</blockquote>)}</details>)}</article>)}</section>;
   })}
   {declarations && declarations.declarations.length > 0 && <details className="skills-background"><summary>Saved manual capabilities ({declarations.declarations.length})</summary>{declarations.declarations.map(d=><article key={d.id}><h4>{d.name}</h4><p>{d.description}</p></article>)}</details>}
   {profile?.status === 'draft'&&<div className="skills-profile-save"><p className="small">Review the details above. You can save a partial profile; unknown details stay uncertain.</p><button className="btn pri" type="button" disabled={saving||pending} onClick={save}>{saving?'Saving profile…':'Save profile'}</button></div>}
   <p className="small skills-summary-note">Evidence is specific to each experience. A missing detail is uncertain; it does not mean a skill is absent. Job-specific evaluation happens against your chosen role.</p>
  </section>
 </div>;
}

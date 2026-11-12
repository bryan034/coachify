"use client";
import Link from 'next/link';
import {useEffect, useState, type ReactNode} from 'react';
import {cvApi} from '@/lib/api/cv';
import type {InterviewTopic} from './types';
import { Icon } from '@/components/ui/icon';
import { formatDate } from '@/lib/format';
import { useComparison } from '@/features/assessment/comparison';
import { dateSpan } from './dates';
import { useProcessingPercent } from './cv-processing-progress';
import type { CvDetail, CvItem, CvSummary } from './types';

const stageRank: Record<string, number> = {queued: 0, source_read: 0, document_parse: 0, model_request: 1, extraction_validation: 2, model_repair: 2, publication: 2, ready: 3};
const Tick = ({size = 11, color = 'currentColor'}: {size?: number; color?: string}) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>;

/** What the page promises before any CV exists: three plain steps and the cost of skipping. */
export function FirstUploadNextSteps() {
 const steps: [string, string][] = [
  ['elo reads your CV', 'Usually takes a minute or two. You can leave this page while it works.'],
  ['You see what it found', 'Your experiences and skills are listed in one place.'],
  ['You answer a few questions', 'Short questions about what you did yourself, so your skills are accurate.'],
 ];
 return <aside className="skills-first-side">
  <section className="card" aria-labelledby="skills-next-title">
   <h2 id="skills-next-title">What happens next</h2>
   <ol className="skills-next-steps">{steps.map(([title, text], index) => <li key={title}><span className="skills-next-num" aria-hidden="true">{index + 1}</span><span><strong>{title}</strong><span>{text}</span></span></li>)}</ol>
  </section>
  <p className="skills-first-note"><Icon name="warn"/><span>Until you add a CV, elo can’t generate a roadmap, and job matches won’t show which skills you already have.</span></p>
 </aside>;
}

/** Page-level view while the only CV is still being read. */
export function SkillsProcessing({token, title, cv, items, busy, cancel, review, later}: {token?: string; title: ReactNode; cv: CvSummary; items: CvItem[]; busy: boolean; cancel: () => void; review?: () => void; later?: () => void}) {
 const comparison = useComparison(token, `processing:${cv.id}`);
 const goalRole = comparison.context?.goal?.role;
 const {progress, percent, active} = useProcessingPercent(cv);
 const stage = progress?.stage ?? 'queued';
 const current = Math.min(stageRank[stage] ?? 0, 2);
 const found = items.filter(item => !item.removed && item.kind !== 'skill');
 const steps = [
  {name: 'Uploaded', detail: 'Done', state: 'done'},
  {name: 'Read your CV', detail: current > 0 ? 'Done' : cv.status === 'queued' ? 'Waiting to start' : 'In progress', state: current > 0 ? 'done' : 'now'},
  {name: 'Finding your experiences', detail: current > 1 ? 'Done' : current === 1 ? (found.length ? `${found.length} found so far` : 'In progress') : 'Up next', state: current > 1 ? 'done' : current === 1 ? 'now' : 'todo'},
  {name: 'Listing your skills', detail: current === 2 ? 'In progress' : 'Up next', state: current === 2 ? 'now' : 'todo'},
 ];
 const name = cv.display_name ?? cv.file_name;
 return <div className="skills-home skills-run">
  <header className="skills-hero skills-hero-compact"><div className="skills-hero-copy is-stacked">{title}
   <p className="skills-hero-line">elo is reading your CV. Your skills will be compared with {goalRole ? <Link href="/career-goal">{goalRole}</Link> : 'your Career Goal'} once it’s done.</p>
  </div></header>
  <section className="card skills-run-card" aria-labelledby="skills-read-title" aria-busy={active}>
   <div className="skills-run-file">
    <Icon name="doc"/>
    <div><h2 id="skills-read-title">{name}</h2><p>Uploaded {formatDate(cv.created_at)}</p></div>
    <span className="skills-run-actions">{review && <button type="button" className="btn sm" disabled={busy} onClick={review}>Open review</button>}{later && <button type="button" className="btn sm" disabled={busy} onClick={later}>Save and review later</button>}<button type="button" className="btn sm" disabled={busy} onClick={cancel}>Cancel upload</button></span>
   </div>
   <div className="skills-run-body">
    <div className="skills-run-meter">
     <div><p id="skills-read-label">Reading your CV</p><p className="skills-run-percent">{progress ? <>{percent}%<span> complete</span></> : <span>In progress</span>}</p></div>
     <div className={`skills-run-track${progress ? '' : ' is-indeterminate'}`} role="progressbar" aria-labelledby="skills-read-label" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ? percent : undefined} aria-valuetext={progress ? `${percent}% complete` : 'In progress'}><span style={{width: progress ? `${percent}%` : '35%'}}/></div>
    </div>
    <ol className="skills-run-steps">{steps.map(step => <li key={step.name} aria-current={step.state === 'now' ? 'step' : undefined}>
     <span className={`skills-run-mark is-${step.state}`} aria-hidden="true">{step.state === 'done' && <Tick/>}</span>
     <span><strong>{step.name}</strong><span>{step.detail}</span></span>
    </li>)}</ol>
    <p role="status" className="skills-run-note">You can leave this page. elo keeps reading, and your profile will be here when it’s done.</p>
   </div>
  </section>
  <div className="skills-run-grid">
   <section className="card skills-run-found" aria-labelledby="skills-found-title">
    <div><h2 id="skills-found-title">Experiences found so far</h2><span>{found.length}</span></div>
    <p>You’ll check these in the next step.</p>
    <ul>{found.map(item => <li key={item.id}><Tick size={18} color="var(--ready-ink, #116149)"/><span><strong>{item.title}</strong>{dateSpan(item.start_date, item.end_date, item.ongoing) && <span>{dateSpan(item.start_date, item.end_date, item.ongoing)}</span>}</span></li>)}
     <li aria-hidden="true" className="is-pending"><span className="skills-run-dash"/><span><i className="skills-sk" style={{width: '55%'}}/><i className="skills-sk" style={{width: '35%', height: 10}}/></span></li></ul>
   </section>
   <section className="card skills-run-skills" aria-label="Skills, loading">
    <div><h2>Skills by category</h2><p>Skills appear here once your experiences are read.</p></div>
    <div aria-hidden="true">{[[120, [78, 64, 92, 70]], [96, [88, 60, 100]], [130, [72, 96, 66, 84, 58]], [104, [90, 68]]].map(([label, chips]) => <div key={label as number} className="skills-run-row"><i className="skills-sk" style={{width: label as number, height: 12}}/><span>{(chips as number[]).map(width => <i key={width} className="skills-sk is-chip" style={{width}}/>)}</span></div>)}</div>
   </section>
  </div>
 </div>;
}

/** Shown once the guided review is finished; points at what the profile unlocks. */
export function ReviewComplete({cv}: {cv: CvDetail}) {
 const summary = cv.review_summary;
 const answered = summary?.answered_questions ?? 0, experiences = summary?.experiences ?? 0;
 const changes = summary ? [[summary.skills_added, 'added'], [summary.skills_corrected, 'corrected'], [summary.skills_removed, 'removed']]
  .filter(([count]) => Number(count) > 0).map(([count, verb]) => verb === 'added' ? `added ${count} ${count === 1 ? 'skill' : 'skills'}` : `${verb} ${count}`) : [];
 const joined = changes.length > 1 ? `${changes.slice(0, -1).join(', ')} and ${changes[changes.length - 1]}` : changes[0];
 return <section className="skills-complete" aria-labelledby="skills-complete-title">
  <span className="skills-complete-mark" aria-hidden="true"><Tick size={18} color="#fff"/></span>
  <div>
   <h2 id="skills-complete-title">Your CV review is complete</h2>
   <p>{answered ? `You answered ${answered} ${answered === 1 ? 'question' : 'questions'} across ${experiences} ${experiences === 1 ? 'experience' : 'experiences'}.${joined ? ` From your answers, elo ${joined}.` : ' Your skills reflect your answers.'}` : 'Your skills reflect the review you completed with elo.'}</p>
  </div>
  <div className="skills-complete-actions"><Link className="btn pri" href="/roadmap">Generate roadmap</Link><Link className="btn" href="/jobs">Search jobs</Link></div>
 </section>;
}

/** Saved review topics for one CV, read from its current saved conversation. Never starts a conversation. */
export function useReviewTopics(token: string | undefined, cvId: string | null, version: string) {
 const [state, setState] = useState<{key: string; topics: InterviewTopic[] | null; failed: boolean} | null>(null);
 const key = `${cvId}:${version}`;
 useEffect(() => {
  if (!token || !cvId) return;
  const controller = new AbortController();
  (async () => {
   try {
    const {conversations} = await cvApi.conversations(cvId, token, controller.signal);
    const current = [...conversations].sort((a, b) => Number(a.read_only) - Number(b.read_only) || b.updated_at.localeCompare(a.updated_at))[0];
    const topics = current ? (await cvApi.conversation(current.id, token, controller.signal)).interview?.topics ?? null : null;
    if (!controller.signal.aborted) setState({key, topics, failed: false});
   } catch { if (!controller.signal.aborted) setState({key, topics: null, failed: true}); }
  })();
  return () => controller.abort();
 }, [token, cvId, key]);
 return state?.key === key ? state : null;
}

const lockIcon = <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 11h12v9H6zM9 11V8a3 3 0 0 1 6 0v3"/></svg>;

/** A CV has been read but its review is unfinished: show where the review stands, and what it unlocks. */
export function ReviewNotFinished({cv, topics, goalRole, review, saveCv, savingCv, pending, upload, chat}: {cv: CvDetail; topics: InterviewTopic[] | null; goalRole?: string; review: () => void; saveCv: () => void; savingCv: boolean; pending: boolean; upload: () => void; chat: () => void}) {
 const covered = (status: string) => ['reviewed', 'reviewed_with_gaps', 'deferred'].includes(status);
 const list = topics ?? [];
 const done = list.filter(topic => covered(topic.status)).length;
 const skipped = list.filter(topic => topic.status === 'deferred').length;
 const next = list.find(topic => topic.status === 'current') ?? list.find(topic => !covered(topic.status));
 const left = list.length - done;
 const started = done > 0 || list.some(topic => topic.status === 'current');
 return <div className="skills-home skills-unfinished">
  <section className="card skills-unfinished-hero" aria-labelledby="skills-unfinished-title">
   <div className="skills-unfinished-top">
    <p><span className="skills-unfinished-badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 8v5M12 16.5v.01M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18"/></svg>Review not finished</span></p>
    <h2 id="skills-unfinished-title">Finish your CV review to build your profile</h2>
    <p className="skills-unfinished-copy">elo has read your CV, but your skills aren’t added until you’ve reviewed each topic, or skipped the ones you want to accept as written. Roadmap and Search Jobs unlock when you’re done.</p>
    <div className="skills-unfinished-actions">
     <button type="button" className="skills-unfinished-cta" onClick={review}>{started ? 'Continue review' : 'Start review'}</button>
     {list.length > 0 && <span><strong>{left} {left === 1 ? 'topic' : 'topics'} left.</strong>{next ? ` Next up: ${next.title}` : ''}</span>}
    </div>
   </div>
   {list.length > 0 && <div className="skills-unfinished-progress">
    <div className="skills-unfinished-count"><p>{done} of {list.length} topics covered</p><p>{done - skipped} reviewed, {skipped} skipped</p></div>
    <div className="skills-unfinished-segs" role="progressbar" aria-label="CV review progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(100 * done / list.length)} aria-valuetext={`${done} of ${list.length} topics covered`} style={{gridTemplateColumns: `repeat(${list.length},minmax(0,1fr))`}}>
     {list.map(topic => <span key={topic.id} className={topic.status === 'deferred' ? 'is-skipped' : covered(topic.status) ? 'is-done' : topic === next ? 'is-next' : ''}/>)}
    </div>
    <ol className="skills-unfinished-topics" aria-label="Review topics">{list.map(topic => {
     const skippedTopic = topic.status === 'deferred', doneTopic = covered(topic.status) && !skippedTopic, now = topic === next;
     return <li key={topic.id} className={now ? 'is-next' : undefined} aria-current={now ? 'step' : undefined}>
      <span className={`skills-unfinished-mark${skippedTopic ? ' is-skipped' : doneTopic ? ' is-done' : now ? ' is-next' : ''}`} aria-hidden="true">{doneTopic && <Tick/>}{skippedTopic && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" aria-hidden="true"><path d="M6 12h12"/></svg>}</span>
      <span><strong className={doneTopic || skippedTopic ? 'is-quiet' : undefined}>{topic.title}</strong><small>{skippedTopic ? 'Skipped, CV used as written' : doneTopic ? 'Reviewed' : now ? 'Next up' : 'Not started'}</small></span>
     </li>;
    })}</ol>
   </div>}
   <div className="skills-unfinished-foot">
    <button type="button" className="btn ghost sm" onClick={upload}>Upload new CV</button>
    <button type="button" className="btn ghost sm" onClick={chat}>Add skills by chat</button>
    <button type="button" className="btn ghost sm" disabled={savingCv || pending} onClick={saveCv}>{savingCv ? 'Saving…' : 'Use my CV as written'}</button>
   </div>
  </section>
  <section className="card skills-locked" aria-labelledby="skills-locked-title">
   <h2 id="skills-locked-title">Waiting for your review</h2>
   <p>These unlock when your CV review is finished.</p>
   <ul>{[['Goal match', `See how your skills compare with ${goalRole ?? 'your Career Goal'}.`], ['Roadmap', 'Plan what to learn first, around your week.'], ['Search Jobs', 'See which roles match the skills you already have.']].map(([name, text]) => <li key={name}><span aria-hidden="true">{lockIcon}</span><span><strong>{name}</strong><span>{text}</span></span></li>)}</ul>
  </section>
 </div>;
}

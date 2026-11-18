"use client";
import Link from 'next/link';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { FreeTimes, Workspace } from '@/features/roadmap/types';
import { reevaluateSkill } from '@/lib/api/assessment';
import { cvApi } from '@/lib/api/cv';
import { roadmapApi } from '@/lib/api/roadmap';
import { loadRoadmap } from '@/lib/api/workspace-summary';
import { errorText } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import { HelperComposer, HelperHeader, HelperOpening, HelperStatus } from '@/components/ui/helper-chat';
import { announceInputsChanged, type Comparison } from './comparison';
import { levelText } from './levels';

/** One skill as the drawer talks about it. Level and target come from the saved evaluation. */
export type TalkSkill = {
 key: string; name: string; canonicalId?: string | null;
 level: number | null; target: number | null;
 /** What reaching the target means for this role, when the goal says. */
 meaning?: string | null;
 /** Where the current level comes from. */
 sources?: string[];
 /** What the CV review noted about this skill. */
 note?: string | null;
 /** Saved things to learn for this skill; the drawer offers them one at a time. */
 tasks: { name: string; reason: string }[];
};
type Props = {
 skill: TalkSkill | null; onClose: () => void; token?: string; goalLabel?: string; comparison: Comparison;

 /** 'build' opens straight at the task that builds the skill. */
 mode?: 'talk' | 'build'; onRoadmapChanged?: () => void;
};
type Message = { id: number; kind: 'elo' | 'me' | 'task' | 'alert' | 'result' | 'wait'; body: ReactNode };
type Reply = { label: string; solid?: boolean; href?: string; run?: () => void };

const words = (value: string) => value.trim().split(/\s+/).filter(Boolean);
/** One line, under 20 words, on why the skill has its level. */
export function ratingReason(skill: Pick<TalkSkill, 'name' | 'level' | 'sources' | 'note'>) {
 if (skill.note && words(skill.note).length < 20) return skill.note;
 if (skill.level == null) return 'I couldn’t find enough in your CV to rate this.';
 const base = `Rated ${skill.level} out of 10 based on`, sources = (skill.sources ?? []).filter(Boolean);
 if (!sources.length) return `${base} your CV and review answers.`;
 const room = 19 - words(base).length;
 const both = sources.length > 1 ? `${sources[0]} and ${sources[1]}` : '';
 const named = both && words(both).length <= room ? both : words(sources[0]).slice(0, room).join(' ');
 return `${base} ${named}.`;
}
/** Roadmap task names hold at most 19 words and 160 characters. */
const taskTitle = (value: string) => value.trim().split(/\s+/).slice(0, 19).join(' ').slice(0, 160);

/**
 * Skills Helper: tell elo about experience that isn't on the CV. The answer is saved to the Skills Profile and
 * only this skill is judged again. Opened from "build", it offers one task that builds the skill instead.
 */
export function TalkItThrough(props: Props) {
 const { skill, onClose } = props;
 const close = useRef<HTMLButtonElement>(null), opener = useRef<Element | null>(null);
 const open = !!skill;
 useEffect(() => {
  if (!open) return;
  opener.current = document.activeElement;
  const timer = setTimeout(() => close.current?.focus(), 60);
  const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
  document.addEventListener('keydown', key);
  return () => { clearTimeout(timer); document.removeEventListener('keydown', key); (opener.current as HTMLElement | null)?.focus?.(); };
 }, [open, onClose]);
 return <>
  <div className={`ws-scrim${open ? ' on' : ''}`} onClick={onClose}/>
  <aside className={`ws-drawer${open ? ' on' : ''}`} role="dialog" aria-modal="true" aria-label={skill?.name ?? 'Skill helper'} aria-hidden={!open}>
   <HelperHeader title="Skills Helper" onClose={onClose} closeRef={close}/>
   {skill && <HelperStatus><strong>{skill.name}</strong> · {levelText(skill.level, skill.target)}</HelperStatus>}
   {skill && <Conversation key={skill.key} {...props} skill={skill}/>}
  </aside>
 </>;
}

function Conversation({ skill, onClose, token, goalLabel, mode, onRoadmapChanged }: Props & { skill: TalkSkill }) {
 const [messages, setMessages] = useState<Message[]>([]);
 const [replies, setReplies] = useState<Reply[]>([]);
 const [draft, setDraft] = useState(''), [busy, setBusy] = useState(false);
 const next = useRef(0);
 const lifetime = useRef(new AbortController()), list = useRef<HTMLDivElement>(null), input = useRef<HTMLTextAreaElement>(null);
 useEffect(() => { if (lifetime.current.signal.aborted) lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
 const push = (kind: Message['kind'], body: ReactNode) => setMessages(all => [...all.filter(item => item.kind !== 'wait'), { id: next.current++, kind, body }]);
 useEffect(() => { const node = list.current; if (node) node.scrollTop = node.scrollHeight; }, [messages, replies]);
 useEffect(() => { if (mode !== 'build') input.current?.focus(); }, [mode]);
 useEffect(() => { if (mode === 'build') build('Help me build it'); /* the opening, once */ }, []); // eslint-disable-line react-hooks/exhaustive-deps
 const done = (): Reply[] => [{ label: 'Close', solid: true, run: onClose }];

 /* ---- What the person tells elo: saved as evidence, then only this skill is judged again ---- */
 async function share(what: string) {
  if (!token || busy) return;
  push('me', what); setDraft(''); setBusy(true); push('wait', 'Saving your answer…');
  const signal = lifetime.current.signal;
  const before = skill.level;
  try {
   const current = await cvApi.declarations(token, signal);
   const match = current.declarations.find(item => item.name.trim().toLowerCase() === skill.name.trim().toLowerCase());
   await cvApi.addDeclaration({ expected_version: current.version, mutation_id: crypto.randomUUID(), name: match?.name ?? skill.name, description: what.slice(0, 2000), mode: match ? 'attach' : 'new', ...(match ? { attach_to_id: match.id } : {}) }, token, signal);
   if (signal.aborted) return;
  } catch (cause) {
   if (!signal.aborted) { push('alert', errorText(cause, 'Your answer could not be saved. Try again.')); setDraft(what); setBusy(false); }
   return;
  }
  push('wait', `Checking ${skill.name} again…`);
  try {
   const result = await reevaluateSkill(token, { name: skill.name, canonical_skill_id: skill.canonicalId ?? null }, signal);
   if (signal.aborted) return;
   const after = result.skill.competence_score;
   push('result', before === after ? `${skill.name}: stays at ${after ?? 'Not rated'}` : `${skill.name}: ${before ?? 'Not rated'} → ${after ?? 'Not rated'}`);
  } catch (cause) {
   if (!signal.aborted) push('alert', cause && typeof cause === 'object' && 'status' in cause && cause.status === 409
    ? 'Your answer is saved. Your level updates the next time your skills are evaluated.'
    : errorText(cause, 'Your answer is saved, but your level couldn’t be checked just now. It updates the next time your skills are evaluated.'));
  } finally { if (!signal.aborted) { setBusy(false); announceInputsChanged(); } }
 }

 /* ---- Opened from "Build this skill": one task that builds the skill ---- */
 function build(label: string) {
  push('me', label); setReplies([]);
  if (!skill.tasks.length) {
   push('elo', 'I don’t have a specific task saved for this skill yet. Your roadmap plans practice for every skill below its target.');
   setReplies([{ label: 'Open roadmap', solid: true, href: '/roadmap' }, { label: 'Close', run: onClose }]);
   return;
  }
  offer(0);
 }
 function offer(index: number) {
  const task = skill.tasks[index % skill.tasks.length];
  push('elo', index === 0 ? 'Here’s one task that would show it:' : 'Here’s another one:');
  push('task', <><b>{task.name}</b>{task.reason}<br/><span className="plus">Builds {skill.name}</span></>);
  setReplies([
   { label: 'Add to my roadmap', solid: true, run: () => { push('me', 'Add to my roadmap'); void add(index); } },
   ...(skill.tasks.length > 1 ? [{ label: 'Suggest something else', run: () => { push('me', 'Suggest something else'); offer(index + 1); } }] : []),
  ]);
 }
 async function add(index: number) {
  if (!token) return;
  const task = skill.tasks[index % skill.tasks.length], signal = lifetime.current.signal;
  setReplies([]); setBusy(true);
  try {
   const workspace = await loadRoadmap(token, signal);
   if (!workspace.planner.active) {
    push('elo', 'You don’t have a roadmap yet. Generate one and elo plans this skill into it.');
    setReplies([{ label: 'Generate roadmap', solid: true, href: '/roadmap' }, { label: 'Close', run: onClose }]);
    return;
   }
   const minutes = workspace.planner.config.preferred_session_minutes || 60;
   const free = await roadmapApi<FreeTimes>('/planner/sessions/free-times', token, { duration_minutes: minutes }, signal);
   const day = free.days.find(item => item.starts.length > 0);
   const date = day?.date ?? free.today, time = day?.starts[0] ?? null;
   await roadmapApi<Workspace>('/planner/sessions/add', token, { expected_version: free.version, mutation_id: crypto.randomUUID(), allow_overlap: false,
    session: { title: taskTitle(task.name), completion_criterion: task.reason.slice(0, 4000), skills: [skill.name.slice(0, 160)], date, start_time: time, duration_minutes: minutes } }, signal);
   if (signal.aborted) return;
   push('elo', `Added to your roadmap for ${formatDate(date)}${time ? `, ${time}` : ''}. You can move it there.`);
   setReplies([{ label: 'Close', solid: true, run: onClose }, { label: 'Open roadmap', href: '/roadmap' }]);
   onRoadmapChanged?.();
  } catch (cause) {
   if (!signal.aborted) { push('alert', errorText(cause, 'The task could not be added to your roadmap. Try again.')); setReplies([{ label: 'Try again', solid: true, run: () => void add(index) }, { label: 'Close', run: onClose }]); }
  } finally { if (!signal.aborted) setBusy(false); }
 }

 function submit(event: FormEvent) {
  event.preventDefault();
  const value = draft.trim();
  if (value && !busy) void share(value);
 }
 return <>
  <div className="ws-msgs" ref={list} aria-live="polite">
   <HelperOpening title={skill.level == null ? `Why isn’t ${skill.name} rated?` : `Why is ${skill.name} rated ${skill.level} out of 10?`}>
    <p>{ratingReason(skill)}{skill.target != null ? ` The target for ${goalLabel ?? 'your goal'} is ${skill.target}.` : ''}</p>
    <p>If your CV review doesn’t show solid evidence, elo assumes you used complete guidance, so it doesn’t assume you understand this topic.</p>
    <p><b>Want elo to take another look?</b> Tell me about this skill, in your own words:</p>
    <ul>
     <li>Projects outside your CV where you’ve used it</li>
     <li>How confident you feel with it</li>
     <li>What you built or solved on your own, without step-by-step guidance</li>
    </ul>
    <p>elo will add it to your Skills Profile and re-evaluate your level.</p>
   </HelperOpening>
   {messages.map(message => message.kind === 'result'
    ? <div key={message.id} className="ws-m result">{message.body}</div>
    : message.kind === 'wait' ? <div key={message.id} className="ws-m result" role="status"><span className="ws-spin" aria-hidden="true"/>{message.body}</div>
    : <div key={message.id} className={`ws-m ${message.kind}`} role={message.kind === 'alert' ? 'alert' : undefined}>{message.body}</div>)}
  </div>
  {!!replies.length && <div className="ws-replies">{replies.map(reply => reply.href
   ? <Link key={reply.label} className={`ws-reply${reply.solid ? ' solid' : ''}`} href={reply.href}>{reply.label}</Link>
   : <button key={reply.label} type="button" className={`ws-reply${reply.solid ? ' solid' : ''}`} disabled={busy} onClick={reply.run}>{reply.label}</button>)}</div>}
  <form className="ws-composer" onSubmit={submit}>
   <HelperComposer hint="Everything you add stays yours to change." canSend={!!draft.trim() && !busy}>
    <textarea ref={input} rows={3} maxLength={1800} value={draft} disabled={busy} aria-label="Your answer" placeholder="Tell me about your experience with this skill…" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}/>
   </HelperComposer>
  </form>
 </>;
}

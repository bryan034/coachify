"use client";
import Link from 'next/link';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { FreeTimes, Workspace } from '@/features/roadmap/types';
import { reevaluateSkill, skillChat, skillChatHistory, type SkillChatEntry, type SkillChatReply } from '@/lib/api/assessment';
import { cvApi } from '@/lib/api/cv';
import { roadmapApi } from '@/lib/api/roadmap';
import { loadRoadmap } from '@/lib/api/workspace-summary';
import { errorText } from '@/lib/errors';
import { formatDate } from '@/lib/format';
import { HelperComposer, HelperHeader, HelperOpening, HelperStatus } from '@/components/ui/helper-chat';
import { announceInputsChanged, type Comparison } from './comparison';
import { levelText } from './levels';

export type TalkSkill = {
 key: string; name: string; canonicalId?: string | null;
 level: number | null; target: number | null; estimated?: boolean;
 meaning?: string | null;
 sources?: string[];
 note?: string | null;
 tasks: { name: string; reason: string }[];
};
type Props = {
 skill: TalkSkill | null; onClose: () => void; token?: string; goalLabel?: string; comparison: Comparison;

 mode?: 'talk' | 'build'; onRoadmapChanged?: () => void;
};
type Message = { id: number; kind: 'elo' | 'me' | 'task' | 'alert' | 'result' | 'wait'; body: ReactNode };
type Reply = { label: string; solid?: boolean; href?: string; run?: () => void; retry?: boolean };

const words = (value: string) => value.trim().split(/\s+/).filter(Boolean);
export function ratingReason(skill: Pick<TalkSkill, 'name' | 'level' | 'sources' | 'note' | 'estimated'>) {
 if (skill.note && words(skill.note).length < 20) return skill.note;
 if (skill.level == null) return 'I couldn’t find enough in your CV to rate this.';
 const base = `${skill.estimated ? 'Estimated at' : 'Rated'} ${skill.level} out of 10 based on`, sources = (skill.sources ?? []).filter(Boolean);
 if (!sources.length) return `${base} your CV and review answers.`;
 const room = 19 - words(base).length;
 const both = sources.length > 1 ? `${sources[0]} and ${sources[1]}` : '';
 const named = both && words(both).length <= room ? both : words(sources[0]).slice(0, room).join(' ');
 return `${base} ${named}.`;
}
const taskTitle = (value: string) => value.trim().split(/\s+/).slice(0, 19).join(' ').slice(0, 160);
const levelChange = (name: string, before: number | null, after: number | null) =>
 before === after ? `${name}: stays at ${after ?? 'Not rated'}` : `${name}: ${before ?? 'Not rated'} → ${after ?? 'Not rated'}`;
function savedMessages(name: string, turns: SkillChatEntry[]): Message[] {
 return turns.flatMap((turn, index): Message[] => {
  const id = -(turns.length - index) * 3;
  if (turn.role === 'person') return [{ id, kind: 'me', body: turn.text }];
  if (turn.level) return [{ id, kind: 'result', body: levelChange(name, turn.level.before, turn.level.after) }, { id: id + 1, kind: 'elo', body: turn.text }];
  return [{ id, kind: 'elo', body: turn.text }, ...(turn.evidence ? [{ id: id + 1, kind: 'result' as const, body: `Your experience: “${turn.evidence}”` }] : [])];
 });
}

export function TalkItThrough(props: Props) {
 const { skill, onClose } = props;
 const close = useRef<HTMLButtonElement>(null), drawer = useRef<HTMLElement>(null), opener = useRef<Element | null>(null);
 const closing = useRef(onClose);
 closing.current = onClose;
 const open = !!skill;
 useEffect(() => {
  if (!open) return;
  opener.current = document.activeElement;
  const timer = setTimeout(() => { if (!drawer.current?.contains(document.activeElement)) close.current?.focus(); }, 60);
  const key = (event: KeyboardEvent) => { if (event.key === 'Escape') closing.current(); };
  document.addEventListener('keydown', key);
  return () => { clearTimeout(timer); document.removeEventListener('keydown', key); (opener.current as HTMLElement | null)?.focus?.(); };
 }, [open]);
 return <>
  <div className={`ws-scrim${open ? ' on' : ''}`} onClick={onClose}/>
  <aside ref={drawer} className={`ws-drawer${open ? ' on' : ''}`} role="dialog" aria-modal="true" aria-label={skill?.name ?? 'Skill helper'} aria-hidden={!open}>
   <HelperHeader title="Skills Helper" onClose={onClose} closeRef={close}/>
   {skill && <HelperStatus><strong>{skill.name}</strong> · {levelText(skill.level, skill.target)}</HelperStatus>}
   {skill && <Conversation key={skill.key} {...props} skill={skill}/>}
  </aside>
 </>;
}

function Conversation({ skill, onClose, token, goalLabel, mode, onRoadmapChanged }: Props & { skill: TalkSkill }) {
 const [messages, setMessages] = useState<Message[]>([]), [past, setPast] = useState<Message[] | null>(token ? null : []);
 const [replies, setReplies] = useState<Reply[]>([]);
 const [draft, setDraft] = useState(''), [busy, setBusy] = useState(false);
 const next = useRef(0);
 const lifetime = useRef(new AbortController()), list = useRef<HTMLDivElement>(null), input = useRef<HTMLTextAreaElement>(null);
 useEffect(() => { if (lifetime.current.signal.aborted) lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
 useEffect(() => {
  if (!token) return;
  const signal = lifetime.current.signal;
  skillChatHistory(token, { name: skill.name, canonical_skill_id: skill.canonicalId ?? null }, signal)
   .then(saved => { if (!signal.aborted) setPast(savedMessages(skill.name, saved.turns)); })
   .catch(() => { if (!signal.aborted) setPast([{ id: -1, kind: 'alert', body: 'Your earlier messages couldn’t be loaded. You can keep talking.' }]); });
 }, []);
 const push = (kind: Message['kind'], body: ReactNode) => setMessages(all => [...all.filter(item => item.kind !== 'wait'), { id: next.current++, kind, body }]);
 useEffect(() => { const node = list.current; if (node) node.scrollTop = node.scrollHeight; }, [past, messages, replies]);
 useEffect(() => { if (mode !== 'build') input.current?.focus(); }, [mode]);
 useEffect(() => { if (mode === 'build') build('Help me build it');  }, []);
 const done = (): Reply[] => [{ label: 'Close', solid: true, run: onClose }];

 async function share(what: string, again = false) {
  if (!token || busy) return;
  if (!again) push('me', what);
  setDraft(''); setReplies(all => all.filter(reply => !reply.retry)); setBusy(true); push('wait', 'Thinking…');
  const signal = lifetime.current.signal;
  let answer: SkillChatReply;
  try {
   answer = await skillChat(token, { name: skill.name, canonical_skill_id: skill.canonicalId ?? null, message: what }, signal);
   if (signal.aborted) return;
  } catch (cause) {
   if (!signal.aborted) {
    push('alert', errorText(cause, 'elo couldn’t reply just now. Try again.'));
    setReplies(all => [...all, { label: 'Try again', solid: true, retry: true, run: () => void share(what, true) }]); setBusy(false);
   }
   return;
  }
  push('elo', answer.reply);
  if (answer.evidence) await saveEvidence(answer.evidence);
  else setBusy(false);
 }

 async function saveEvidence(evidence: string) {
  if (!token) return;
  const signal = lifetime.current.signal, before = skill.level;
  setReplies(all => all.filter(reply => !reply.retry)); setBusy(true);
  push('result', `Saving to your Skills Profile: “${evidence}”`); push('wait', 'Saving your answer…');
  try {
   const current = await cvApi.declarations(token, signal);
   const match = current.declarations.find(item => item.name.trim().toLowerCase() === skill.name.trim().toLowerCase());
   await cvApi.addDeclaration({ expected_version: current.version, mutation_id: crypto.randomUUID(), name: match?.name ?? skill.name, description: evidence.slice(0, 2000), mode: match ? 'attach' : 'new', ...(match ? { attach_to_id: match.id } : {}) }, token, signal);
   if (signal.aborted) return;
  } catch (cause) {
   if (!signal.aborted) {
    push('alert', errorText(cause, 'Your answer could not be saved. Try again.'));
    setReplies(all => [...all, { label: 'Try saving again', solid: true, retry: true, run: () => void saveEvidence(evidence) }]); setBusy(false);
   }
   return;
  }
  push('wait', `Checking ${skill.name} again…`);
  try {
   const result = await reevaluateSkill(token, { name: skill.name, canonical_skill_id: skill.canonicalId ?? null }, signal);
   if (signal.aborted) return;
   push('result', levelChange(skill.name, before, result.skill.competence_score)); push('elo', result.skill.explanation);
  } catch (cause) {
   if (!signal.aborted) push('alert', cause && typeof cause === 'object' && 'status' in cause && cause.status === 409
    ? 'Your answer is saved. Your level updates the next time your skills are evaluated.'
    : errorText(cause, 'Your answer is saved, but your level couldn’t be checked just now. It updates the next time your skills are evaluated.'));
  } finally { if (!signal.aborted) { setBusy(false); announceInputsChanged(); } }
 }

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
   <HelperOpening title={skill.level == null ? `Why isn’t ${skill.name} rated?` : `Why is ${skill.name} ${skill.estimated ? 'estimated at' : 'rated'} ${skill.level} out of 10?`}>
    <p>{ratingReason(skill)}{skill.target != null ? ` Target: ${skill.target}.` : ''}</p>
    <p>Without clear evidence, elo assumes you had guidance.</p>
    <p><b>Ask me why</b>, or tell me about:</p>
    <ul>
     <li>Projects not on your CV</li>
     <li>What you did unguided</li>
     <li>How confident you feel</li>
    </ul>
   </HelperOpening>
   {past === null && <div className="ws-m result" role="status"><span className="ws-spin" aria-hidden="true"/>Loading your conversation…</div>}
   {[...(past ?? []), ...messages].map(message => message.kind === 'result'
    ? <div key={message.id} className="ws-m result">{message.body}</div>
    : message.kind === 'wait' ? <div key={message.id} className="ws-m result" role="status"><span className="ws-spin" aria-hidden="true"/>{message.body}</div>
    : <div key={message.id} className={`ws-m ${message.kind}`} role={message.kind === 'alert' ? 'alert' : undefined}>{message.body}</div>)}
  </div>
  {!!replies.length && <div className="ws-replies">{replies.map(reply => reply.href
   ? <Link key={reply.label} className={`ws-reply${reply.solid ? ' solid' : ''}`} href={reply.href}>{reply.label}</Link>
   : <button key={reply.label} type="button" className={`ws-reply${reply.solid ? ' solid' : ''}`} disabled={busy} onClick={reply.run}>{reply.label}</button>)}</div>}
  <form className="ws-composer" onSubmit={submit}>
   <HelperComposer hint="Everything you add stays yours to change." canSend={!!draft.trim() && !busy}>
    <textarea ref={input} rows={3} maxLength={1800} value={draft} disabled={busy} aria-label="Your message" placeholder="Ask why, or tell me about your experience…" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}/>
   </HelperComposer>
  </form>
 </>;
}

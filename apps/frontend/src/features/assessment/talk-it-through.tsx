"use client";
import Link from 'next/link';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { FreeTimes, Workspace } from '@/features/roadmap/types';
import { rateSkill, skillRatings } from '@/lib/api/assessment';
import { cvApi } from '@/lib/api/cv';
import { roadmapApi } from '@/lib/api/roadmap';
import { loadRoadmap } from '@/lib/api/workspace-summary';
import { errorText } from '@/lib/errors';
import { formatDate } from '@/lib/format';
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
 /** The person's own skills, offered as "tools used". */
 tools?: string[]; allowSelfRating?: boolean;
 /** 'build' opens straight at the task that builds the skill. */
 mode?: 'talk' | 'build'; onRoadmapChanged?: () => void; onRated?: () => void;
};
type Message = { id: number; kind: 'elo' | 'me' | 'task' | 'alert' | 'result' | 'wait'; body: ReactNode; undo?: boolean };
type Reply = { label: string; solid?: boolean; href?: string; run?: () => void };
type Saved = { declaration_id: string; contribution_id: string };

const running = (c: Comparison) => !!c.current?.operation && ['pending', 'running'].includes(c.current.operation.status);
/** Roadmap task names hold at most 19 words and 160 characters. */
const taskTitle = (value: string) => value.trim().split(/\s+/).slice(0, 19).join(' ').slice(0, 160);

/**
 * "Talk it through": tell elo about experience that isn't on the CV, or get one task that builds the skill.
 * Evidence is saved to the Skills Profile and the level changes only when the evaluation is run again.
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
  <aside className={`ws-drawer${open ? ' on' : ''}`} role="dialog" aria-modal="true" aria-labelledby="talk-title" aria-hidden={!open}>
   <div className="ws-dr-head">
    <div className="t"><span>Talk it through</span><b id="talk-title">{skill?.name}</b></div>
    {skill && <span className="ws-dr-score">{levelText(skill.level, skill.target)}</span>}
    <button ref={close} className="ws-x" type="button" aria-label="Close chat" onClick={onClose}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
   </div>
   {skill && <Conversation key={skill.key} {...props} skill={skill}/>}
  </aside>
 </>;
}

function Conversation({ skill, onClose, token, goalLabel, comparison, tools = [], allowSelfRating, mode, onRoadmapChanged, onRated }: Props & { skill: TalkSkill }) {
 const intro = (): Message[] => [
  { id: 0, kind: 'elo', body: skill.target != null
   ? <>For {goalLabel ?? 'your goal'}, the target for <b>{skill.name}</b> is {skill.target} out of 10.{skill.meaning ? ` ${skill.meaning}` : ''}</>
   : <><b>{skill.name}</b> is rated out of 10 from your CV and review answers.</> },
  { id: 1, kind: 'elo', body: <>{skill.level == null ? 'I couldn’t find enough in your CV to rate this.' : `You’re at ${skill.level} now${skill.sources?.length ? `, based on ${skill.sources.slice(0, 2).join(' and ')}` : ''}.`}{skill.note ? ` From your CV review: ${skill.note}` : ''} {skill.level == null ? 'Have you used it anywhere, like a project, internship or club?' : 'Have you used this somewhere that isn’t on your CV yet?'}</> },
 ];
 const [messages, setMessages] = useState<Message[]>(intro);
 const [replies, setReplies] = useState<Reply[]>([]);
 const [asking, setAsking] = useState<null | ((text: string) => void)>(null), [draft, setDraft] = useState('');
 const [picking, setPicking] = useState<null | { what: string }>(null), [picked, setPicked] = useState<string[]>([]);
 const [rating, setRating] = useState<number | null>(null);
 const [busy, setBusy] = useState(false);
 /** Set while a saved change waits for the next evaluation. */
 const [watch, setWatch] = useState<{ before: number | null; resultId: string | null; saved: Saved | null; started: boolean } | null>(null);
 const next = useRef(2), saved = useRef<Saved | null>(null);
 const lifetime = useRef(new AbortController()), list = useRef<HTMLDivElement>(null), input = useRef<HTMLTextAreaElement>(null);
 useEffect(() => { if (lifetime.current.signal.aborted) lifetime.current = new AbortController(); return () => lifetime.current.abort(); }, []);
 const push = (kind: Message['kind'], body: ReactNode, undo = false) => setMessages(all => [...all.filter(item => item.kind !== 'wait'), { id: next.current++, kind, body, undo }]);
 useEffect(() => { const node = list.current; if (node) node.scrollTop = node.scrollHeight; }, [messages, replies, asking, picking, rating]);
 useEffect(() => { if (asking) input.current?.focus(); }, [asking]);
 const done = (): Reply[] => [{ label: 'Close', solid: true, run: onClose }];
 const fail = (cause: unknown, fallback: string, retry: Reply[]) => { push('alert', errorText(cause, fallback)); setReplies(retry); };

 const start = (): Reply[] => [
  { label: 'Yes, let me tell you', solid: true, run: () => prove('Yes, let me tell you') },
  { label: 'Not yet, help me build it', run: () => build('Not yet, help me build it') },
  ...(allowSelfRating && skill.level == null ? [{ label: 'Set my own level', run: () => { setReplies([]); setRating(5); } }] : []),
 ];
 useEffect(() => { if (mode === 'build') build('Help me build it'); else setReplies(start()); /* the opening, once */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

 /* ---- Path A: experience that isn't on the CV ---- */
 function prove(label: string) {
  push('me', label); setReplies([]);
  push('elo', 'Great. What did you do, and what came out of it?');
  setAsking(() => (what: string) => {
   push('me', what); setAsking(null);
   const options = tools.filter(name => name.trim().toLowerCase() !== skill.name.trim().toLowerCase()).slice(0, 6);
   if (!options.length) { void saveEvidence(what, []); return; }
   push('elo', 'Which of your skills or tools did you use? Pick any.');
   setPicked([]); setPicking({ what });
  });
 }
 async function saveEvidence(what: string, used: string[]) {
  if (!token) return;
  setPicking(null); setReplies([]); setBusy(true);
  const description = `${what}${used.length ? `\nTools used: ${used.join(', ')}` : ''}`.slice(0, 2000);
  const signal = lifetime.current.signal;
  try {
   const current = await cvApi.declarations(token, signal);
   const match = current.declarations.find(item => item.name.trim().toLowerCase() === skill.name.trim().toLowerCase());
   const result = await cvApi.addDeclaration({ expected_version: current.version, mutation_id: crypto.randomUUID(), name: match?.name ?? skill.name, description, mode: match ? 'attach' : 'new', ...(match ? { attach_to_id: match.id } : {}) }, token, signal);
   if (signal.aborted) return;
   const declaration = result.declarations.find(item => match ? item.id === match.id : !current.declarations.some(old => old.id === item.id));
   const contribution = declaration?.contributions?.find(item => item.description === description && !match?.contributions?.some(old => old.id === item.id));
   saved.current = declaration && contribution ? { declaration_id: declaration.id, contribution_id: contribution.id } : null;
   const evaluated = !!comparison.current?.result;
   push('elo', evaluated ? 'Thanks. I’ve added it to your Skills Profile and I’m checking your level again. This takes a minute or two.' : 'Thanks. I’ve added it to your Skills Profile. Your level shows once your skills are evaluated against your goal.');
   if (evaluated) { push('wait', 'Checking your level…'); setWatch({ before: skill.level, resultId: comparison.current!.result!.id, saved: saved.current, started: false }); }
   else setReplies(done());
   announceInputsChanged();
  } catch (cause) {
   if (!signal.aborted) fail(cause, 'Your answer could not be saved. Try again.', [{ label: 'Try again', solid: true, run: () => void saveEvidence(what, used) }, { label: 'Close', run: onClose }]);
  } finally { if (!signal.aborted) setBusy(false); }
 }
 async function undo(change: Saved, messageId: number) {
  if (!token || busy) return;
  setBusy(true);
  const signal = lifetime.current.signal;
  try {
   const current = await cvApi.declarations(token, signal);
   await cvApi.withdrawDeclaration({ expected_version: current.version, mutation_id: crypto.randomUUID(), ...change }, token, signal);
   if (signal.aborted) return;
   setMessages(all => all.map(item => item.id === messageId ? { ...item, body: 'Change undone', undo: false } : item));
   push('wait', 'Checking your level…');
   setWatch({ before: skill.level, resultId: comparison.current?.result?.id ?? null, saved: null, started: false });
   announceInputsChanged();
  } catch (cause) { if (!signal.aborted) push('alert', errorText(cause, 'The change could not be undone. Try again.')); }
  finally { if (!signal.aborted) setBusy(false); }
 }
 // The level only moves when the evaluation finishes; report it then.
 const resultId = comparison.result?.id ?? null, failed = comparison.current?.operation?.status === 'failed', active = running(comparison);
 useEffect(() => {
  if (!watch) return;
  if (active && !watch.started) { setWatch({ ...watch, started: true }); return; }
  if (resultId && resultId !== watch.resultId) {
   const text = watch.before === skill.level ? `${skill.name}: stays at ${levelText(skill.level, skill.target)}` : `${skill.name}: ${watch.before ?? 'Not rated'} → ${skill.level ?? 'Not rated'}`;
   push('result', text, !!watch.saved);
   setWatch(null); setReplies(done());
  } else if ((watch.started && !active && (failed || comparison.error)) || (!active && comparison.current?.stale && comparison.context && (!comparison.context.model_available || comparison.context.cv_reviewed === false))) {
   push('alert', 'Your answer is saved, but your level couldn’t be checked just now. It updates the next time your skills are evaluated.');
   setWatch(null); setReplies(done());
  }
 }, [watch, resultId, failed, active, comparison.error, comparison.current, comparison.context, skill.level, skill.target, skill.name]); // eslint-disable-line react-hooks/exhaustive-deps

 /* ---- Path B: one task that builds the skill ---- */
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
   if (!signal.aborted) fail(cause, 'The task could not be added to your roadmap. Try again.', [{ label: 'Try again', solid: true, run: () => void add(index) }, { label: 'Close', run: onClose }]);
  } finally { if (!signal.aborted) setBusy(false); }
 }

 /* ---- A level the person sets for a skill elo could not rate ---- */
 async function rate(score: number) {
  if (!token) return;
  const signal = lifetime.current.signal;
  setBusy(true);
  try {
   const current = await skillRatings(token, signal);
   await rateSkill(token, { expected_version: current.version, name: skill.name, canonical_skill_id: skill.canonicalId ?? null, score });
   if (signal.aborted) return;
   setRating(null);
   push('result', `You set ${skill.name} to ${score} / 10. It’s shown as your own rating.`);
   setReplies(done());
   announceInputsChanged(); onRated?.();
  } catch { if (!signal.aborted) push('alert', 'Your rating could not be saved. Try again.'); }
  finally { if (!signal.aborted) setBusy(false); }
 }

 function submit(event: FormEvent) {
  event.preventDefault();
  const value = draft.trim();
  if (!value || !asking) return;
  setDraft(''); asking(value);
 }
 return <>
  <div className="ws-msgs" ref={list} aria-live="polite">
   {messages.map(message => message.kind === 'result'
    ? <div key={message.id} className="ws-m result">{message.body}{message.undo && saved.current && <button className="u" type="button" disabled={busy} onClick={() => void undo(saved.current!, message.id)}>Undo</button>}</div>
    : message.kind === 'wait' ? <div key={message.id} className="ws-m result" role="status"><span className="ws-spin" aria-hidden="true"/>{message.body}</div>
    : <div key={message.id} className={`ws-m ${message.kind}`} role={message.kind === 'alert' ? 'alert' : undefined}>{message.body}</div>)}
  </div>
  {picking && <div className="ws-replies" role="group" aria-label="Skills or tools you used">
   {tools.filter(name => name.trim().toLowerCase() !== skill.name.trim().toLowerCase()).slice(0, 6).map(name => <button key={name} type="button" className="ws-reply" aria-pressed={picked.includes(name)} onClick={() => setPicked(all => all.includes(name) ? all.filter(item => item !== name) : [...all, name])}>{name}</button>)}
   <button type="button" className="ws-reply solid" disabled={busy} onClick={() => { push('me', picked.length ? picked.join(', ') : 'None of these'); void saveEvidence(picking.what, picked); }}>Done</button>
  </div>}
  {rating != null && <form className="ws-rate" onSubmit={event => { event.preventDefault(); void rate(rating); }}>
   <label htmlFor="talk-rating">Your level for {skill.name}: <b>{rating} / 10</b></label>
   <input id="talk-rating" type="range" min={1} max={10} step={1} value={rating} onChange={event => setRating(Number(event.target.value))}/>
   <span className="ws-sub">1 is just starting, 5 is working independently, 10 is expert. This is your own rating; it isn’t checked against evidence.</span>
   <div className="ws-replies" style={{ padding: 0 }}><button type="submit" className="ws-reply solid" disabled={busy}>{busy ? 'Saving…' : 'Save my rating'}</button><button type="button" className="ws-reply" disabled={busy} onClick={() => { setRating(null); setReplies(start()); }}>Cancel</button></div>
  </form>}
  {!picking && rating == null && <div className="ws-replies">{replies.map(reply => reply.href
   ? <Link key={reply.label} className={`ws-reply${reply.solid ? ' solid' : ''}`} href={reply.href}>{reply.label}</Link>
   : <button key={reply.label} type="button" className={`ws-reply${reply.solid ? ' solid' : ''}`} disabled={busy} onClick={reply.run}>{reply.label}</button>)}</div>}
  {asking && <form className="ws-composer" onSubmit={submit}>
   <textarea ref={input} rows={2} maxLength={1800} value={draft} aria-label="Your answer" placeholder="What did you do, and what was the result?" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}/>
   <button type="submit" disabled={!draft.trim()}>Send</button>
  </form>}
 </>;
}

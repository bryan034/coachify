"use client";
import ReactMarkdown from 'react-markdown';
import { useEffect, useRef, type FormEvent } from 'react';
import { BrandLogo } from '@/components/ui/brand-logo';
import { useChatScroll, ChatScrollControl } from '@/features/career/use-chat-scroll';
import type { Runway, Workspace } from './types';
import { friendlyOperationError } from '@/lib/errors';
import { humaniseText } from '@/lib/format';

/** The required planner details, in the order the helper asks for them. Issue codes come from the backend's runway. */
const required: { code: string; label: string; question: string; hint: string; starters: string[] }[] = [
 { code: 'missing_target', label: 'target date or duration', question: 'When would you like to be ready?', hint: 'Give me a date or a length of time, and I’ll fill in your timeline.', starters: ['I want to be ready in 8 weeks.', 'Help me choose a realistic target date.'] },
 { code: 'no_budget', label: 'weekly study budget', question: 'How many hours can you study each week?', hint: 'A rough number is fine. You can change it in the planner at any time.', starters: ['About five hours a week.', 'Help me find a realistic weekly pace.'] },
 { code: 'no_blocks', label: 'recurring study blocks', question: 'Which days and times do you usually study?', hint: 'I’ll turn your answer into recurring study blocks.', starters: ['I can study on weekday evenings and Saturday mornings.'] },
];

export function AdviserChat({ workspace, runway, text, setText, partial, setPartial, showPartial, busy, running, frozen, editing, takeFocus, send, retry, close }: {
 workspace: Workspace; runway: Runway | null; text: string; setText: (value: string) => void; partial: boolean; setPartial: (value: boolean) => void; showPartial: boolean;
 busy: boolean; running: boolean; frozen: boolean; editing: boolean; takeFocus: boolean; send: () => void; retry: () => void; close: () => void;
}) {
 const { transcript, showJump, jumpToLatest, scrollProps } = useChatScroll();
 const input = useRef<HTMLTextAreaElement>(null);
 useEffect(() => { if (takeFocus) input.current?.focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
 const { context } = workspace;
 const validResearch = ['available', 'no_findings'].includes(context.research_coverage || '');
 const failed = workspace.operation?.status === 'failed';
 const missing = required.filter(item => runway?.issues.some(issue => issue.code === item.code));
 const next = missing[0];
 return <section className="adviser-conversation" aria-label="Chat helper" onKeyDown={event => { if (event.key === 'Escape') close(); }}>
  <div className="adviser-intro"><div className="adviser-avatar" aria-hidden="true"><BrandLogo compact decorative /></div><div><h2>{editing ? 'Roadmap planner' : 'Plan helper'}</h2><p>{editing ? 'Add or change tasks. You review every change first.' : 'I’ll guide you through the planner and fill it in as we talk.'}</p></div><button type="button" className="btn ghost adviser-close" aria-label="Close chat helper" onClick={close}>Close</button></div>
  {!editing && <p className="helper-needed" role="status">{missing.length ? <>Still needed: <strong>{missing.map(item => item.label).join(', ')}</strong></> : 'All required details are filled in. Review the planner, then generate your roadmap.'}</p>}
  <div ref={transcript} {...scrollProps} className="adviser-messages" role="log" aria-label="Saved planning messages" aria-live="polite">
   {!workspace.messages.length && <div className="adviser-opening"><h3>{editing ? 'What would you like to change?' : next?.question || 'Anything else to add?'}</h3><p>{editing ? 'Tell me what isn’t working and I’ll prepare a preview for you to review.' : next?.hint || 'I can add blackout days and times, your preferred session length or what you’d like to focus on.'}</p>{!editing && next?.code === 'no_budget' && context.planning_defaults.weekly_hours != null && <p>You previously saved {context.planning_defaults.weekly_hours} hours a week. We can use that as a starting point or choose a different pace.</p>}{!editing && next?.code === 'missing_target' && context.goal?.job_dates?.map((date, i) => <p key={i}>{date.kind.replaceAll('_', ' ')}: <strong>{date.text}</strong>. We can discuss a target date around this.</p>)}{!editing && !!next && <div className="adviser-starters">{next.starters.map(prompt => <button key={prompt} disabled={!context.ready || busy} onClick={() => setText(prompt)}>{prompt}</button>)}</div>}</div>}
   {workspace.messages.map(message => <article key={message.id} className={`adviser-message ${message.role}`}><span>{message.role === 'assistant' ? 'elo' : 'You'}</span><ReactMarkdown components={{ img: () => null, a: ({ children }) => <span>{children}</span> }}>{humaniseText(message.content)}</ReactMarkdown></article>)}
   {running && <p role="status" className="adviser-working">Working on your request… You can keep drafting your next message.</p>}
   {failed && workspace.retry_request && <div className="roadmap-notice"><p>{friendlyOperationError(workspace.operation?.error, 'This response could not finish. Your message is saved.')}</p>{!!workspace.operation?.retry_after && <p role="status">Provider capacity: retry in {workspace.operation.retry_after} seconds.</p>}<button className="btn" disabled={busy || !context.ready || !context.model_available || !!workspace.operation?.retry_after} onClick={retry}>{workspace.operation?.error?.code === 'inputs_changed' ? 'Retry with current inputs' : 'Retry saved message'}</button></div>}
  </div>
  <ChatScrollControl visible={showJump} onClick={jumpToLatest} />
  <form className="adviser-composer" onSubmit={(event: FormEvent) => { event.preventDefault(); send(); }}>
   {!validResearch && context.ready && <p className="small">Using available evidence. Interview research is {context.research_coverage || 'unavailable'}; the comparison will be labelled partial.</p>}
   {!context.model_available && <p className="small">Your helper is unavailable. Your saved plan remains available, and you can still fill in the planner yourself.</p>}
   <label htmlFor="adviser-message">{editing ? 'Ask for a change' : 'Answer here'}</label><textarea ref={input} id="adviser-message" rows={2} maxLength={4000} value={text} disabled={!context.ready} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (text.trim() && context.ready && context.model_available && !frozen) send(); } }} placeholder={editing ? 'Move Thursday’s session to Saturday morning…' : 'I can do six hours a week, mostly on Saturdays…'} />
   <div><span className="small">{editing ? 'Changes appear as a preview first.' : 'Everything I fill in stays yours to change.'}</span> <span className="cv-visually-hidden">Enter to send · Shift+Enter for a new line</span><button className="btn primary" disabled={!text.trim() || !context.ready || !context.model_available || frozen}>Send message</button></div>
  </form>
 </section>;
}

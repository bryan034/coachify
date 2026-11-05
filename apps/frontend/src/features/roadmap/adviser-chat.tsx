"use client";
import ReactMarkdown from 'react-markdown';
import { useEffect, useRef, type FormEvent } from 'react';
import { BrandLogo } from '@/components/ui/brand-logo';
import { useChatScroll, ChatScrollControl } from '@/features/career/use-chat-scroll';
import { chatEnterKey, chatKeyHint } from '@/lib/chat-keyboard';
import { nextGuideStep, requiredDetails } from './planner-guide';
import type { PlannerConfig, Runway, Workspace } from './types';

export function AdviserChat({ workspace, runway, config, text, setText, partial, setPartial, showPartial, busy, running, frozen, editing, send, retry, close }: {
 workspace: Workspace; runway: Runway | null; config: PlannerConfig | null; text: string; setText: (value: string) => void; partial: boolean; setPartial: (value: boolean) => void; showPartial: boolean;
 busy: boolean; running: boolean; frozen: boolean; editing: boolean; send: () => void; retry: () => void; close: () => void;
}) {
 const { transcript, showJump, jumpToLatest, scrollProps } = useChatScroll();
 const input = useRef<HTMLTextAreaElement>(null);
 useEffect(() => { input.current?.focus(); }, []);
 const { context } = workspace;
 const validResearch = ['available', 'no_findings'].includes(context.research_coverage || '');
 const failed = workspace.operation?.status === 'failed';
 const missing = requiredDetails.filter(item => runway?.issues.some(issue => issue.code === item.code));
 const next = editing ? null : nextGuideStep(runway, config);
 const needsChoice = editing && !validResearch && !partial;
 const canSend = !!text.trim() && context.ready && context.model_available && !frozen && !needsChoice;
 return <section className="adviser-conversation" aria-label="Chat helper" onKeyDown={event => { if (event.key === 'Escape') close(); }}>
  <div className="adviser-intro"><div className="adviser-avatar" aria-hidden="true"><BrandLogo compact decorative /></div><div><h2>Your chat helper</h2><p>{editing ? 'Ask for a change and review it before it applies.' : 'I’ll guide you through the planner and fill it in as we talk.'}</p></div><button type="button" className="btn ghost adviser-close" onClick={close}>Close chat helper</button></div>
  {!editing && <p className="helper-needed" role="status">{missing.length ? <>Still needed: <strong>{missing.map(item => item.label).join(', ')}</strong></> : 'All required details are filled in. Review the planner, then generate your roadmap.'}</p>}
  <div ref={transcript} {...scrollProps} className="adviser-messages" role="log" aria-label="Saved planning messages" aria-live="polite">
   {editing && !workspace.messages.length && <div className="adviser-opening"><h3>What would you like to change?</h3><p>Tell me what isn’t working and I’ll prepare a preview for you to review.</p></div>}
   {workspace.messages.map(message => <article key={message.id} className={`adviser-message ${message.role}`}><span>{message.role === 'assistant' ? 'elo' : 'You'}</span><ReactMarkdown components={{ img: () => null, a: ({ children }) => <span>{children}</span> }}>{message.content}</ReactMarkdown></article>)}
   {!editing && !running && <div className="helper-next">
    {next ? <>
     <p className="helper-next-field">{next.optional ? 'Optional next' : 'Next'}: <strong>{next.section} › {next.field}</strong></p>
     <h3>{next.question}</h3>
     <p>{next.hint}</p>
     {next.field === 'Weekly budget in hours' && context.planning_defaults.weekly_hours != null && <p>You previously saved {context.planning_defaults.weekly_hours} hours a week. We can use that as a starting point or choose a different pace.</p>}
     {next.field === 'Target date or Duration' && context.goal?.job_dates?.map((date, i) => <p key={i}>{date.kind.replaceAll('_', ' ')}: <strong>{date.text}</strong>. We can discuss a target date around this.</p>)}
     {!!next.starters.length && <div className="adviser-starters">{next.starters.map(prompt => <button key={prompt} type="button" disabled={!context.ready || busy} onClick={() => setText(prompt)}>{prompt}</button>)}</div>}
    </> : <><h3>Anything else to add?</h3><p>Review the planner, then press Generate roadmap. I can still change anything you’ve filled in.</p></>}
   </div>}
   {running && <p role="status" className="adviser-working">Working on your request… You can keep drafting your next message.</p>}
   {failed && workspace.retry_request && <div className="roadmap-notice"><p>{workspace.operation?.error?.detail || 'This response could not finish. Your message is saved.'}</p>{!!workspace.operation?.retry_after && <p role="status">Provider capacity: retry in {workspace.operation.retry_after} seconds.</p>}<button className="btn" disabled={busy || !context.ready || !context.model_available || !!workspace.operation?.retry_after} onClick={retry}>{workspace.operation?.error?.code === 'inputs_changed' ? 'Retry with current inputs' : 'Retry saved message'}</button></div>}
  </div>
  <ChatScrollControl visible={showJump} onClick={jumpToLatest} />
  <form className="adviser-composer" onSubmit={(event: FormEvent) => { event.preventDefault(); send(); }}>
   {showPartial && !validResearch && context.ready && <label className="roadmap-partial"><input type="checkbox" checked={partial} onChange={event => setPartial(event.target.checked)} />Continue with available evidence. Interview research is {context.research_coverage || 'unavailable'}; the comparison will be labelled partial.</label>}
   {!showPartial && needsChoice && context.ready && <p className="small">Tick “Continue with available evidence” in the planner before asking for plan changes.</p>}
   {!context.model_available && <p className="small">Your helper is unavailable. Your saved plan remains available, and you can still fill in the planner yourself.</p>}
   <label htmlFor="adviser-message">{editing ? 'Ask for a change' : 'Answer here'}</label><textarea ref={input} id="adviser-message" rows={3} maxLength={4000} value={text} disabled={!context.ready} onChange={event => setText(event.target.value)} onKeyDown={event => chatEnterKey(event, () => { if (canSend) send(); }, setText)} placeholder={editing ? 'Move Thursday’s session to Saturday morning…' : 'I can do six hours a week, mostly on Saturdays…'} />
   <div><span className="small adviser-composer-notes"><span>{editing ? 'Changes appear as a preview first.' : 'Everything I fill in stays yours to change.'}</span><span>{chatKeyHint}</span></span><button className="btn primary" disabled={!canSend}>Send message</button></div>
  </form>
 </section>;
}

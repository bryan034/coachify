"use client";

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { cvApi, CvApiError } from '@/lib/api/cv';
import type { ConversationAction, ConversationDecision, ConversationInput, ConversationMessage, CvConversation, CvDetail } from './types';

const statusLabel: Record<ConversationAction['status'], string> = {
 awaiting_confirmation: 'Review before saving', needs_source: 'Choose the right source', pending: 'Processing',
 saved: 'Saved', failed: 'Needs attention', cancelled: 'Cancelled', stale: 'Source changed',
};
const mergeMessages = (older: ConversationMessage[], newer: ConversationMessage[]) => [...new Map([...older, ...newer].map(message => [message.id, message])).values()].sort((a, b) => a.sequence - b.sequence);
const hasOutstandingAction = (message: ConversationMessage) => message.actions.some(action => ['pending','awaiting_confirmation','needs_source','failed'].includes(action.status));
const maxHistoryPages = 13; // A bounded 500-message segment contains at most thirteen 40-message pages.
const readableField = (field: string) => ({experience_months: 'Experience in months', start_date: 'Start date', end_date: 'End date', ongoing: 'Still ongoing'}[field] ?? field.replaceAll('_', ' '));

function ActionCard({action, busy, readOnly, decide}: {action: ConversationAction; busy: boolean; readOnly: boolean; decide: (id: string, decision: Omit<ConversationDecision, 'mutation_id' | 'expected_revision'>) => void}) {
 const [choice, setChoice] = useState('');
 const proposed = action.status === 'awaiting_confirmation' || action.status === 'needs_source';
 const matching = action.kind === 'add_capability' && action.choices.length > 0;
 const needsChoice = action.status === 'needs_source' || matching;
 function save() {
  const selected = action.choices.find(item => `${item.kind}:${item.id}` === choice);
  decide(action.id, {decision: 'save', ...(choice === 'distinct' ? {mode: 'distinct'} : selected ? {
   ...(selected.kind === 'declaration' ? {attach_to_id: selected.id} : {item_id: selected.id}),
   ...(matching ? {mode: 'attach'} : {}),
  } : {})});
 }
 if (action.kind === 'route' && action.status === 'saved') return null;
 if (action.kind === 'route' && action.status === 'pending') return <p className="cv-chat-working cv-chat-action-pending">Your message is saved. Understanding it now…</p>;
 if (action.status === 'cancelled') return <details className="cv-chat-receipt"><summary><span className="cv-chat-action-status">Cancelled</span> {action.title}</summary><p>{action.summary}</p></details>;
 if (action.status === 'saved' && ['clarify','skip'].includes(action.kind)) return <p className="cv-chat-receipt"><span className="cv-chat-action-status">Saved</span> {action.summary}</p>;
 return <article className={`cv-chat-action cv-chat-action-${action.status}`} aria-label={action.title}>
  <div className="cv-chat-action-heading"><strong>{action.title}</strong><span className="cv-chat-action-status">{statusLabel[action.status]}</span></div>
  {action.item_title && <p className="cv-chat-source">{action.item_title}</p>}
  <p>{action.summary}</p>
  {action.changes.length > 0 && <dl className="cv-chat-changes">{action.changes.map((change, index) => <div key={`${change.field}:${index}`}><dt>{readableField(change.field)}</dt><dd><span className="cv-chat-before">{change.before ?? 'Unknown'}</span><span aria-hidden="true">→</span><span>{change.after ?? 'Unknown'}</span></dd></div>)}</dl>}
  {proposed && needsChoice && <fieldset className="cv-chat-choices" disabled={busy || readOnly}><legend>{matching ? 'How should this capability be saved?' : 'Which item did you mean?'}</legend>{action.choices.map(option => <label key={`${option.kind}:${option.id}`}><input type="radio" name={`source-${action.id}`} value={`${option.kind}:${option.id}`} checked={choice === `${option.kind}:${option.id}`} onChange={event => setChoice(event.target.value)}/><span><strong>{option.label}</strong><span>{option.description}</span></span></label>)}{matching && <label><input type="radio" name={`source-${action.id}`} value="distinct" checked={choice === 'distinct'} onChange={() => setChoice('distinct')}/><span><strong>Keep as a separate capability</strong><span>Retain this explanation with its own source.</span></span></label>}</fieldset>}
  {action.error && <p className="cv-chat-action-error">{action.error}</p>}
  {!readOnly && proposed && <div className="row cv-chat-action-buttons"><button type="button" className="btn pri sm" disabled={busy || (needsChoice && !choice)} onClick={save}>{action.kind === 'remove' ? 'Remove item' : action.status === 'needs_source' ? 'Use this source' : action.kind === 'add_capability' ? 'Save capability' : 'Save change'}</button><button type="button" className="btn ghost sm" disabled={busy} onClick={() => decide(action.id, {decision: 'cancel'})}>Cancel change</button></div>}
  {!readOnly && action.status === 'failed' && <div className="row cv-chat-action-buttons"><button type="button" className="btn ghost sm" disabled={busy} onClick={() => decide(action.id, {decision: 'retry'})}>Retry this action</button><button type="button" className="btn ghost sm" disabled={busy} onClick={() => decide(action.id, {decision: 'cancel'})}>Cancel change</button></div>}
  {action.status === 'stale' && <p className="small">This proposal cannot change the newer saved details. Explain the correction again using the current source.</p>}
 </article>;
}

export function CvConversationPanel({cvId, detail, token, onChanged, onOpenSummary, unavailable = false}: {
 cvId: string | null; detail: CvDetail | null; token: string; onChanged: () => Promise<void>; onOpenSummary: () => void; unavailable?: boolean;
}) {
 const [conversation, setConversation] = useState<CvConversation | null>(null);
 const [draft, setDraft] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(''), [loading, setLoading] = useState(true), [historyLoading, setHistoryLoading] = useState(false), [announcement, setAnnouncement] = useState('');
 const lifetime = useRef(new AbortController()), openKey = useRef(crypto.randomUUID()), newestId = useRef<string | null>(null), scrollArea = useRef<HTMLDivElement>(null), chatPanel = useRef<HTMLElement>(null), composer = useRef<HTMLTextAreaElement>(null), nearBottom = useRef(true);
 const current = useRef(conversation); current.current = conversation;
 const onChangedRef = useRef(onChanged); onChangedRef.current = onChanged;
 const lastEvidence = useRef(`${cvId}:${detail?.version}:${detail?.extraction_version}`);
 const messageAttempts = useRef(new Map<string, {conversationId: string; body: ConversationInput}>());
 const actionAttempts = useRef(new Map<string, {signature: string; body: ConversationDecision}>());
 const displayedId = useRef<string | null>(null);
 const accept = useCallback((value: CvConversation, replace = false, older = false) => {
  const previous = current.current;
  if (!replace && previous?.id === value.id && value.revision < previous.revision) return false;
  const next = replace || previous?.id !== value.id ? value : {...value, messages: mergeMessages(previous.messages, value.messages), next_before: older ? previous.next_before === null || value.next_before === null ? null : Math.min(previous.next_before, value.next_before) : previous.next_before};
  current.current = next; setConversation(next); return true;
 }, []);
 const syncLoadedActions = useCallback(async (value: CvConversation) => {
  const controller = lifetime.current, id = value.id;
  const valid = () => !controller.signal.aborted && displayedId.current === id;
  const covered = new Set(value.messages.map(message => message.id));
  let pages = 1;
  // Full segments must reveal older outstanding work before offering continuation.
  while (valid() && current.current?.id === id && current.current.read_only && id === newestId.current && current.current.next_before !== null && pages < maxHistoryPages) {
   const before = current.current.next_before;
   const page = await cvApi.conversation(id, token, controller.signal, before); pages++;
   if (!valid()) return;
   if (!accept(page, false, true)) throw new Error('The conversation changed while checking earlier actions. Check saved messages again.');
   page.messages.forEach(message => covered.add(message.id));
   if (page.next_before !== null && page.next_before >= before) throw new Error('Could not finish checking earlier actions. Check saved messages again.');
  }
  // Mutation responses and polling contain only the latest page. Refresh loaded
  // older action cards explicitly, including lease expiry at the same revision.
  let outstanding = current.current?.messages.filter(message => hasOutstandingAction(message) && !covered.has(message.id)) ?? [];
  while (valid() && outstanding.length && pages < maxHistoryPages) {
   const anchor = outstanding[outstanding.length - 1];
   const page = await cvApi.conversation(id, token, controller.signal, anchor.sequence + 1); pages++;
   if (!valid()) return;
   if (!accept(page)) throw new Error('The conversation changed while checking earlier actions. Check saved messages again.');
   page.messages.forEach(message => covered.add(message.id));
   if (!covered.has(anchor.id)) throw new Error('Could not refresh an earlier action. Check saved messages again.');
   outstanding = current.current?.messages.filter(message => hasOutstandingAction(message) && !covered.has(message.id)) ?? [];
  }
  if (valid() && (outstanding.length || (current.current?.read_only && id === newestId.current && current.current.next_before !== null))) throw new Error('Could not finish checking earlier actions. Check saved messages again.');
 }, [token, accept]);
 const open = useCallback(async () => {
  const controller = lifetime.current;
  setLoading(true); setError('');
  try {
   const value = await cvApi.openConversation({cv_id: cvId, mutation_id: openKey.current}, token, controller.signal);
   if (controller.signal.aborted) return;
   newestId.current = value.id; displayedId.current = value.id; accept(value, true); await syncLoadedActions(value);
  } catch (cause) {if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not open your saved conversation.');}
  finally {if (!controller.signal.aborted) setLoading(false);}
 }, [cvId, token, accept, syncLoadedActions]);
 useEffect(() => {if (lifetime.current.signal.aborted) lifetime.current = new AbortController(); void open(); return () => lifetime.current.abort();}, [open]);

 const refresh = useCallback(async () => {
  const id = displayedId.current;
  if (!id) return;
  const value = await cvApi.conversation(id, token, lifetime.current.signal);
  if (!lifetime.current.signal.aborted && displayedId.current === id) {
   const previousRevision = current.current?.revision ?? -1;
   if (!accept(value)) return;
   await syncLoadedActions(value);
   if ((current.current?.revision ?? -1) > previousRevision) await onChangedRef.current();
  }
 }, [token, accept, syncLoadedActions]);
 useEffect(() => {
  function revalidate() {if (document.visibilityState !== 'hidden' && !busy) void refresh().catch(() => {if (!lifetime.current.signal.aborted) setError('Could not refresh the conversation. Your draft is still here.');});}
  window.addEventListener('focus', revalidate); window.addEventListener('online', revalidate);
  return () => {window.removeEventListener('focus', revalidate); window.removeEventListener('online', revalidate);};
 }, [busy, refresh]);
 useEffect(() => {
  const signature = `${cvId}:${detail?.version}:${detail?.extraction_version}`;
  if (lastEvidence.current !== signature && current.current && !busy && detail?.id === cvId) {lastEvidence.current = signature; void refresh().catch(() => {});}
 }, [detail?.version, detail?.extraction_version, detail?.id, cvId, busy, refresh]);
 const pending = conversation?.messages.some(message => message.actions.some(action => action.status === 'pending')) ?? false;
 useEffect(() => {
  if (!pending || busy || loading) return;
  let checking = false;
  const timer = setInterval(() => {if (checking) return; checking = true; void refresh().catch(() => {if (!lifetime.current.signal.aborted) setError('Connection interrupted while checking your saved message. Check saved messages to resume.');}).finally(() => {checking = false;});}, 1000);
  return () => clearInterval(timer);
 }, [pending, busy, loading, refresh]);
 useEffect(() => {if (nearBottom.current && scrollArea.current) scrollArea.current.scrollTop = scrollArea.current.scrollHeight;}, [conversation?.messages, busy]);

 async function send(text: string, command?: ConversationInput['command']) {
  const active = current.current;
  if (!active || busy || unavailable || active.read_only || active.id !== newestId.current || !text.trim()) return;
  if (Array.from(text).length > active.limits.max_message_chars) {setError(`Keep your message within ${active.limits.max_message_chars} characters. Your draft is still here.`); return;}
  const signature = JSON.stringify({text, command});
  // An interrupted response may already be saved. Other sends must not replace
  // its original receipt, revision or segment before that outcome is resolved.
  if (!messageAttempts.current.has(signature)) messageAttempts.current.set(signature, {conversationId: active.id, body: {expected_revision: active.revision, mutation_id: crypto.randomUUID(), text, ...(command ? {command} : {})}});
  const attempt = messageAttempts.current.get(signature)!;
  setBusy('message'); setError(''); setAnnouncement('Saving your message and checking what it means.'); nearBottom.current = true;
  if (command === 'review' && window.matchMedia?.('(max-width: 700px)').matches) chatPanel.current?.scrollIntoView?.({block:'start',behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  try {
   const value = await cvApi.sendMessage(attempt.conversationId, attempt.body, token, lifetime.current.signal);
   if (lifetime.current.signal.aborted || displayedId.current !== active.id) return;
   const currentSegment = attempt.conversationId === active.id;
   if (currentSegment) accept(value);
   if (!command) setDraft(previous => previous === text ? '' : previous); messageAttempts.current.delete(signature);
   setAnnouncement(currentSegment ? 'Your message is saved. Review the response for any changes or actions needing attention.' : 'Your earlier message is saved in the previous conversation.');
   if (currentSegment) await syncLoadedActions(value).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not refresh earlier actions. Check saved messages again.'));
   await onChangedRef.current();
  } catch (cause) {
   if (!lifetime.current.signal.aborted) {
    setError(`${cause instanceof Error ? cause.message : 'The response was interrupted.'} Your draft is still here. Check saved messages before retrying.`);
    if (cause instanceof CvApiError && cause.status === 409) {messageAttempts.current.delete(signature); await refresh().catch(() => {});}
   }
  } finally {if (!lifetime.current.signal.aborted) {setBusy(''); composer.current?.focus();}}
 }
 async function decide(actionId: string, decision: Omit<ConversationDecision, 'mutation_id' | 'expected_revision'>) {
  const active = current.current;
  if (!active || busy || active.id !== newestId.current) return;
  const signature = JSON.stringify(decision);
  if (actionAttempts.current.get(actionId)?.signature !== signature) actionAttempts.current.set(actionId, {signature, body: {expected_revision: active.revision, mutation_id: crypto.randomUUID(), ...decision}});
  const body = actionAttempts.current.get(actionId)!.body; setBusy(actionId); setError('');
  try {
   const value = await cvApi.conversationAction(active.id, actionId, body, token, lifetime.current.signal);
   if (lifetime.current.signal.aborted || displayedId.current !== active.id) return;
   accept(value); actionAttempts.current.delete(actionId); setAnnouncement(decision.decision === 'cancel' ? 'Change cancelled.' : 'Action checked. Its current saved status is shown in the conversation.');
   await syncLoadedActions(value).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not refresh earlier actions. Check saved messages again.'));
   await onChangedRef.current();
  } catch (cause) {if (!lifetime.current.signal.aborted) {setError(cause instanceof Error ? cause.message : 'Could not complete that action.'); if (cause instanceof CvApiError && cause.status === 409) {actionAttempts.current.delete(actionId); await refresh().catch(() => {});}}}
  finally {if (!lifetime.current.signal.aborted) setBusy('');}
 }
 async function history(id?: string) {
  const active = current.current;
  if (!active || historyLoading || busy) return;
  if (!id && active.next_before === null) return;
  setHistoryLoading(true); setError('');
  const area = scrollArea.current, previousHeight = area?.scrollHeight ?? 0;
  try {
   const value = await cvApi.conversation(id ?? active.id, token, lifetime.current.signal, id ? undefined : active.next_before!);
   if (lifetime.current.signal.aborted || displayedId.current !== active.id) return;
   nearBottom.current = false;
   if (id) {displayedId.current = id; accept(value, true); if (area) area.scrollTop = 0; await syncLoadedActions(value);}
   else if (!accept(value, false, true)) throw new Error('The conversation changed while loading earlier messages. Try again.');
   requestAnimationFrame(() => {if (area && !id) area.scrollTop += area.scrollHeight - previousHeight;});
  } catch (cause) {if (!lifetime.current.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load earlier messages.');}
  finally {if (!lifetime.current.signal.aborted) setHistoryLoading(false);}
 }
 function submit(event: FormEvent) {event.preventDefault(); void send(draft);}
 function keyboard(event: KeyboardEvent<HTMLTextAreaElement>) {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void send(draft);}}
 const historical = Boolean(conversation && conversation.id !== newestId.current);
 const started = conversation?.messages.some(message => message.role === 'user') ?? false;
 const unfinished = conversation?.messages.some(hasOutstandingAction) ?? false;
 const blocked = Boolean(busy || unavailable || !conversation || conversation.read_only || historical);
 const count = Array.from(draft).length, limit = conversation?.limits.max_message_chars ?? 4000;
 return <section ref={chatPanel} className="cv-chat" aria-label="CV conversation" data-unsaved={Boolean(draft)}>
  <header className="cv-chat-header"><div><span className="cv-chat-brand" aria-hidden="true">C</span><div><h2>Let’s talk about your experience</h2><p>{detail?.file_name ?? 'Your capabilities'}{conversation && <><span className="cv-chat-saved-dot" aria-hidden="true"/>Saved to your account</>}</p></div></div><button className="btn ghost sm" type="button" onClick={onOpenSummary} aria-label="View CV summary"><span className="cv-chat-summary-desktop">View CV summary</span><span className="cv-chat-summary-mobile">Summary</span></button></header>
  <div className="cv-chat-context">{conversation?.context_error ? <><span>{conversation.context_error}</span><button type="button" className="text-link" onClick={() => void refresh().catch(cause => setError(cause instanceof Error?cause.message:'Could not refresh the career context.'))}>Retry career context</button></> : conversation?.context ? <><span>Reviewing for <strong>{conversation.context.role}</strong></span><Link href="/career-goal" className="text-link">Open Career Goal</Link></> : <><span>You can review your experience now. A confirmed target helps focus the questions.</span><Link href="/career-goal" className="text-link">Open Career Goal</Link></>}</div>
  {historical && <div className="cv-chat-history-banner"><span>Earlier conversation · read only</span><button className="btn ghost sm" type="button" disabled={Boolean(busy) || historyLoading} onClick={() => void history(newestId.current!)}>Return to current conversation</button></div>}
  <div ref={scrollArea} className="cv-chat-messages" onScroll={() => {const area = scrollArea.current; if (area) nearBottom.current = area.scrollHeight - area.scrollTop - area.clientHeight < 90;}}>
   {loading && <p className="cv-chat-loading" role="status">Opening your saved conversation…</p>}
   {!loading && !conversation && <div className="cv-chat-welcome"><h3>Your conversation will be here.</h3><p>Retry to restore your messages. Your saved CV details are still available in the summary.</p><button className="btn ghost" type="button" onClick={() => void open()}>Retry conversation</button></div>}
   {conversation && <>
    <div className="cv-chat-history-controls">{conversation.next_before !== null && <button className="btn ghost sm" type="button" disabled={historyLoading || Boolean(busy)} onClick={() => void history()}>Show earlier messages</button>}{conversation.previous_conversation_id && <button className="btn ghost sm" type="button" disabled={historyLoading || Boolean(busy)} onClick={() => void history(conversation.previous_conversation_id!)}>Previous conversation</button>}</div>
    {!conversation.messages.length && <div className="cv-chat-welcome"><div className="cv-chat-mark" aria-hidden="true">C</div><h3>Your experience has a story.</h3><p>{cvId ? 'We’ll work through the details that matter, one question at a time. You can add context, correct something or ask a question whenever you like.' : 'Tell me about a capability you want to include, or upload a CV to start from what you already have.'}</p>{cvId && <button className="btn pri" type="button" disabled={blocked} onClick={() => void send('Review my CV with me.', 'review')}>Review with me</button>}</div>}
    <ol className="cv-chat-transcript" aria-label="Saved conversation messages">{conversation.messages.map(message => <li key={message.id} className={`cv-chat-message cv-chat-message-${message.role}`}><div className="cv-chat-speaker">{message.role === 'user' ? 'You' : 'Coachify'}<time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})}</time></div><div className="cv-chat-bubble"><p>{message.text}</p>{message.actions.map(action => <ActionCard key={`${action.id}:${action.status}`} action={action} busy={Boolean(busy)} readOnly={historical} decide={(id, decision) => void decide(id, decision)}/>)}</div></li>)}</ol>
   </>}
   {busy === 'message' && <p className="cv-chat-working">Checking your message…</p>}
  </div>
  <div className="cv-chat-composer-wrap">
   {conversation?.active_question && !historical && <div className="cv-chat-current-topic"><span>Current topic: <strong>{conversation.active_question.title}</strong></span><p>{conversation.active_question.question}</p><div className="cv-chat-quick-actions"><button type="button" disabled={blocked} onClick={() => void send('Why are you asking this question?')}>Why this question?</button><button type="button" disabled={blocked} onClick={() => void send('Skip this question.', 'skip')}>Skip this question</button></div></div>}
   {conversation && !conversation.active_question && conversation.messages.length > 0 && cvId && !historical && !conversation.read_only && <div className="cv-chat-quick-actions"><button type="button" disabled={blocked} onClick={() => void send(started ? 'Continue reviewing my CV.' : 'Review my CV with me.', started ? 'continue' : 'review')}>{started ? 'Continue review' : 'Review with me'}</button></div>}
   {error && <div role="alert" className="cv-error"><p>{error}</p>{conversation && <button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={() => void refresh().then(() => setError('')).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not refresh saved messages.'))}>Check saved messages</button>}</div>}
   {conversation?.read_only && !historical ? <div className="cv-chat-limit"><p>This part of your conversation is full. Its messages will stay available when you continue.{conversation.next_before !== null ? ' Checking earlier messages for outstanding actions.' : unfinished && ' Finish or cancel the outstanding actions above first.'}</p><button className="btn pri" type="button" disabled={Boolean(busy) || loading || historyLoading || conversation.next_before !== null || unfinished} onClick={() => {openKey.current = crypto.randomUUID(); void open();}}>Continue in a new conversation</button></div> : !historical && <form className="cv-chat-composer" onSubmit={submit} aria-busy={Boolean(busy)}><label className="cv-visually-hidden" htmlFor={`cv-chat-input-${cvId ?? 'manual'}`}>Message Coachify</label><textarea id={`cv-chat-input-${cvId ?? 'manual'}`} ref={composer} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={keyboard} placeholder="Add context, ask a question, or correct something…" rows={2} disabled={blocked} aria-invalid={count > limit} aria-describedby="cv-chat-input-help"/><div className="cv-chat-composer-footer"><p id="cv-chat-input-help">{count > limit * 0.8 ? `${count} / ${limit} characters` : 'Enter to send · Shift + Enter for a new line'}</p><button type="submit" className="btn pri" disabled={blocked || !draft.trim() || count > limit} aria-label="Send message">{busy === 'message' ? 'Sending…' : 'Send'}<span aria-hidden="true">↑</span></button></div></form>}
   <p className="cv-chat-footnote">Only what you share is used. Unknown details can stay unknown.</p>
  </div>
  <p className="cv-visually-hidden" role="status" aria-live="polite">{announcement}</p>
 </section>;
}

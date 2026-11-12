"use client";
import { reviewText } from './review-text';
import { BrandLogo } from '@/components/ui/brand-logo';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type Dispatch, type SetStateAction } from 'react';
import { cvApi, CvApiError } from '@/lib/api/cv';
import type { ActiveQuestion, ConversationAction, ConversationDecision, ConversationInput, ConversationMessage, CvConversation, CvDetail, InterviewTopic } from './types';
import { errorText } from '@/lib/errors';
import { humaniseText, formatDate } from '@/lib/format';
import { ChatSkeleton } from '@/components/ui/workspace-ui';
const RAIL_MIN = 220, RAIL_MAX = 520, RAIL_DEFAULT = 280;

const statusLabel: Record<ConversationAction['status'], string> = {
 awaiting_confirmation: 'Review before saving', needs_source: 'Choose the right source', pending: 'Processing',
 saved: 'Saved', failed: 'Needs attention', cancelled: 'Cancelled', stale: 'Source changed',
};
const mergeMessages = (older: ConversationMessage[], newer: ConversationMessage[]) => [...new Map([...older, ...newer].map(message => [message.id, message])).values()].sort((a, b) => a.sequence - b.sequence);
const hasOutstandingAction = (message: ConversationMessage) => message.actions.some(action => ['pending','awaiting_confirmation','needs_source','failed'].includes(action.status));
const maxHistoryPages = 13; // A bounded 500-message segment contains at most thirteen 40-message pages.
const readableField = (field: string) => ({experience_months: 'Experience in months', start_date: 'Start date', end_date: 'End date', ongoing: 'Still ongoing'}[field] ?? field.replaceAll('_', ' '));

function ActionCard({action, busy, readOnly, decide, review = false}: {review?: boolean; action: ConversationAction; busy: boolean; readOnly: boolean; decide: (id: string, decision: Omit<ConversationDecision, 'mutation_id' | 'expected_revision'>) => void}) {
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
 if (review && action.status === 'pending' && ['clarify','skip','route'].includes(action.kind)) return <p className="cv-chat-working cv-chat-action-pending" role="status">Reviewing your answer…</p>;
 if (review && ['clarify','skip','route'].includes(action.kind) && !['awaiting_confirmation','needs_source'].includes(action.status)) {
  if (action.status !== 'failed' && action.status !== 'stale') return null;
  return <div className="cv-chat-recovery" role="status"><p>{action.status==='stale'?'This experience changed. Please send your clarification again using the latest details.':'We couldn’t process your answer. It’s saved, so you can try again.'}</p>{!readOnly && action.status==='failed' && <button type="button" className="btn ghost sm" disabled={busy} onClick={() => decide(action.id, {decision: 'retry'})}>Try again</button>}</div>;
 }
 if (action.kind === 'route' && action.status === 'saved') return null;
 if (action.kind === 'route' && action.status === 'pending') return <p className="cv-chat-working cv-chat-action-pending">Your message is saved. Understanding it now…</p>;
 if (action.status === 'cancelled') return <details className="cv-chat-receipt"><summary><span className="cv-chat-action-status">Cancelled</span> {action.title}</summary><p>{action.summary}</p></details>;
 if (action.status === 'saved' && ['clarify','skip'].includes(action.kind)) return <p className="cv-chat-receipt"><span className="cv-chat-receipt-mark" aria-hidden="true"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10"/></svg></span><span><span className="cv-chat-action-status">Saved</span> {action.summary}</span></p>;
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

/** An assistant reply that only repeats the failure shown by its recovery card. */
const FAILURE_REPLY = /^(your answer is saved\. we couldn’t finish processing it|chat interpretation is unavailable)/i;
function failureReply(message: CvConversation['messages'][number]) {
 return FAILURE_REPLY.test(message.text.trim()) && message.actions.some(action => action.status === 'failed' || action.status === 'stale');
}

/** Plain status for a review topic; the current topic shows its question position when known. */
export function topicStatus(topic: InterviewTopic, question?: ActiveQuestion | null) {
 if (topic.status === 'deferred') return 'Skipped · CV used as written';
 if (topic.status === 'reviewed') return 'Done';
 if (topic.status === 'reviewed_with_gaps') return 'Done · some details uncertain';
 if (topic.status === 'current') return question?.item_id === topic.id && question.number && question.limit ? `Now · question ${question.number} of ${question.limit}` : 'Now';
 return 'Up next';
}
function QuestionLabel({question, sourceIds}: {question: ActiveQuestion; sourceIds: string[]}) {
 return <><p className="cv-question-topic">{reviewText(question.title, sourceIds)}</p>{question.number && question.limit ? <p className="cv-question-count">Question {question.number} of {question.limit}</p> : null}</>;
}
function AnswerHints({hints}: {hints?: string[]}) {
 if (!hints?.length) return null;
 return <div className="cv-answer-hints"><p>Your answer can cover</p><ul>{hints.map(hint => <li key={hint}>{hint}</li>)}</ul></div>;
}

export function CvConversationPanel({cvId, detail, token, onChanged, onOpenSummary, onReviewLater = onOpenSummary, unavailable = false, hidden = false, purpose, autoReview = false, onActivityChanged, draft: persistedDraft, onDraftChange}: {
 cvId: string | null; detail: CvDetail | null; token: string; onChanged: () => Promise<void>; onOpenSummary: () => void; unavailable?: boolean; hidden?: boolean; purpose?: 'skills_profile'; autoReview?: boolean; onActivityChanged?: (active: boolean) => void; draft?: string; onDraftChange?: Dispatch<SetStateAction<string>>;
 onReviewLater?: (unconfirmed: boolean) => void;
}) {
 const uploadedReview = Boolean(cvId && purpose === 'skills_profile');
 const [conversation, setConversation] = useState<CvConversation | null>(null);
 const [localDraft, setLocalDraft] = useState('');
 const draft = persistedDraft ?? localDraft, setDraft = onDraftChange ?? setLocalDraft;
 const [error, setError] = useState(''), [busy, setBusy] = useState(''), [loading, setLoading] = useState(true), [historyLoading, setHistoryLoading] = useState(false), [announcement, setAnnouncement] = useState('');
 const [unconfirmedMessage, setUnconfirmedMessage] = useState<ConversationInput | null>(null);
 const [checkingReturn, setCheckingReturn] = useState(false);
 // Skip confirmations: one topic in the rail, all remaining topics, or the composer shortcut in the chat.
 const [skipping, setSkipping] = useState<{scope: 'topic' | 'all' | 'chat'; id?: string} | null>(null);
 // Topics rail width: drag the divider or use the arrow keys; the choice is remembered in this browser.
 const [railWidth, setRailWidth] = useState(() => {try {const saved = Number(window.localStorage.getItem('elo-cv-rail-width')); return saved >= RAIL_MIN && saved <= RAIL_MAX ? saved : RAIL_DEFAULT;} catch {return RAIL_DEFAULT;}});
 const resizeRail = useCallback((width: number) => {const next = Math.min(RAIL_MAX, Math.max(RAIL_MIN, Math.round(width))); setRailWidth(next); try {window.localStorage.setItem('elo-cv-rail-width', String(next));} catch {}}, []);
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
   const value = await cvApi.openConversation({cv_id: cvId, mutation_id: openKey.current, ...(purpose?{purpose}:{})}, token, controller.signal);
   if (controller.signal.aborted) return;
   newestId.current = value.id; displayedId.current = value.id; accept(value, true); await syncLoadedActions(value);
  } catch (cause) {if (!controller.signal.aborted) setError(errorText(cause, 'Could not open your saved conversation.'));}
  finally {if (!controller.signal.aborted) setLoading(false);}
 }, [cvId, token, purpose, accept, syncLoadedActions]);
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
 const wasReviewOpen = useRef(autoReview);
 const reviewCheck = useRef(0);
 const returning = Boolean(uploadedReview && autoReview && !wasReviewOpen.current && conversation);
 const resumeBlocked = checkingReturn || returning;
 const checkSavedReview = useCallback(async () => {
  const check = ++reviewCheck.current;
  setCheckingReturn(true);
  try {
   await refresh();
   if (!lifetime.current.signal.aborted && reviewCheck.current === check) {
    setCheckingReturn(false);
    setError('');
   }
  } catch {
   if (!lifetime.current.signal.aborted && reviewCheck.current === check) setError('Could not refresh your saved review. Check saved messages to try again.');
  }
 }, [refresh]);
 useEffect(() => {
  wasReviewOpen.current = autoReview;
  if (returning) void checkSavedReview();
 }, [autoReview, returning, checkSavedReview]);
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

 async function send(text: string, command?: ConversationInput['command'], itemId?: string) {
  const active = current.current;
  const signature = JSON.stringify({text, command, itemId});
  const previousAttempt = messageAttempts.current.get(signature);
  const recovering = Boolean(unconfirmedMessage && previousAttempt?.body.mutation_id === unconfirmedMessage.mutation_id);
  if (!active || busy || unavailable || resumeBlocked || active.id !== newestId.current || !text.trim() || (unconfirmedMessage && !recovering)) return;
  if (!recovering && (active.read_only || active.messages.some(message => message.actions.some(action => action.status === 'pending')))) return;
  if (Array.from(text).length > active.limits.max_message_chars) {setError(`Keep your message within ${active.limits.max_message_chars} characters. Your draft is still here.`); return;}
  // An interrupted response may already be saved. Other sends must not replace
  // its original receipt, revision or segment before that outcome is resolved.
  const attempt = previousAttempt ?? {conversationId: active.id, body: {expected_revision: active.revision, mutation_id: crypto.randomUUID(), text, ...(command ? {command} : {}), ...(itemId ? {item_id: itemId} : {})}};
  messageAttempts.current.set(signature, attempt);
  if (command === 'review_topic') setReopening(true);
  setBusy('message'); setError(''); setAnnouncement('Saving your message and checking what it means.'); nearBottom.current = true;
  if (command === 'review' && window.matchMedia?.('(max-width: 700px)').matches) chatPanel.current?.scrollIntoView?.({block:'start',behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  try {
   const value = await cvApi.sendMessage(attempt.conversationId, attempt.body, token, lifetime.current.signal);
   if (lifetime.current.signal.aborted || displayedId.current !== active.id) return;
   const currentSegment = attempt.conversationId === active.id;
   if (currentSegment) accept(value);
   if (!command) setDraft(previous => previous === text ? '' : previous);
   messageAttempts.current.delete(signature);
   setUnconfirmedMessage(null);
   if (uploadedReview) setBusy('refreshing-message');
   setAnnouncement(currentSegment ? command === 'skip' ? 'Skipped. Unclarified details remain uncertain; the review can continue.' : command === 'skip_topic' ? 'Topic skipped. elo uses your CV as written for it.' : command === 'skip_remaining' ? 'Remaining topics skipped. elo uses your CV as written for them.' : 'Your message is saved. Review the response for any changes or actions needing attention.' : 'Your earlier message is saved in the previous conversation.');
   if (currentSegment) await syncLoadedActions(value).catch(cause => setError(errorText(cause, 'Could not refresh earlier actions. Check saved messages again.')));
   await onChangedRef.current().catch(cause => {
    if (!uploadedReview) throw cause;
    if (!lifetime.current.signal.aborted) setError('Your message is saved. Could not refresh Skills Profile.');
   });
  } catch (cause) {
   if (!lifetime.current.signal.aborted) {
    if (uploadedReview && !(cause instanceof CvApiError && [400,401,403,404,409,413,422].includes(cause.status))) {
     setUnconfirmedMessage(attempt.body);
    } else {
     setError(`${errorText(cause, 'The response was interrupted.')} Your draft is still here. Check saved messages before retrying.`);
     if (uploadedReview || cause instanceof CvApiError && cause.status === 409) {
      messageAttempts.current.delete(signature);
      setUnconfirmedMessage(null);
     }
     if (cause instanceof CvApiError && cause.status === 409) {
      await refresh().catch(() => {});
      const latest = current.current;
      if (uploadedReview && command === 'review' && latest && latest.revision > active.revision && (latest.active_question || latest.interview || latest.messages.some(message => message.role === 'user'))) setError('');
     }
    }
   }
  } finally {if (!lifetime.current.signal.aborted) {setReopening(false); setBusy(''); composer.current?.focus();}}
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
   await syncLoadedActions(value).catch(cause => setError(errorText(cause, 'Could not refresh earlier actions. Check saved messages again.')));
   await onChangedRef.current();
  } catch (cause) {if (!lifetime.current.signal.aborted) {setError(errorText(cause, 'Could not complete that action.')); if (cause instanceof CvApiError && cause.status === 409) {actionAttempts.current.delete(actionId); await refresh().catch(() => {});}}}
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
  } catch (cause) {if (!lifetime.current.signal.aborted) setError(errorText(cause, 'Could not load earlier messages.'));}
  finally {if (!lifetime.current.signal.aborted) setHistoryLoading(false);}
 }
 const upgrading = useRef(false);
 useEffect(()=>{if(!purpose||!conversation||loading||busy)return;if(conversation.purpose===purpose){upgrading.current=false;return;}if(conversation.purpose===null&&!conversation.messages.some(hasOutstandingAction)&&!upgrading.current){upgrading.current=true;void open();}},[purpose,conversation,loading,busy,open]);
 const started = conversation?.messages.some(message => message.role === 'user') ?? false;
 const unfinished = conversation?.messages.some(hasOutstandingAction) ?? false;
 const hasReviewHistory = Boolean(started || conversation?.interview || conversation?.previous_conversation_id || conversation?.next_before != null);
 const [reopening, setReopening] = useState(false);
 // Reviewing a skipped topic reopens a finished review at once, before the server answers.
 const reviewComplete = !reopening && Boolean(conversation?.interview && ['reviewed','reviewed_with_gaps'].includes(conversation.interview.status));
 const autoStarted = useRef(false);
 useEffect(() => {
  if (!autoReview) {autoStarted.current = false; return;}
  if (unavailable || autoStarted.current || !conversation || loading || busy || resumeBlocked || conversation.read_only || conversation.purpose === null || reviewComplete) return;
  if (uploadedReview && (hasReviewHistory || unconfirmedMessage)) return;
  function startWhenVisible() {
   if (autoStarted.current || (uploadedReview && document.visibilityState === 'hidden')) return;
   autoStarted.current = true;
   if (!conversation?.active_question && !unfinished) void send(cvId ? 'Review my CV.' : 'Help me build my skills profile.', 'review');
  }
  startWhenVisible();
  if (uploadedReview && !autoStarted.current) {
   document.addEventListener('visibilitychange', startWhenVisible);
   return () => document.removeEventListener('visibilitychange', startWhenVisible);
  }
 }, [autoReview, conversation, loading, busy, cvId, unavailable, uploadedReview, hasReviewHistory, unconfirmedMessage, unfinished, reviewComplete, resumeBlocked]);
 const recoveredActions = useRef(new Set<string>());
 useEffect(()=>{
  if(uploadedReview||!purpose||!conversation||loading||busy||unavailable||conversation.id!==newestId.current)return;
  const failed=conversation.messages.flatMap(m=>m.actions).find(a=>a.kind==='clarify'&&a.status==='failed'&&a.error?.startsWith('Some interpreted skill details are not supported')&&!recoveredActions.current.has(a.id));
  if(failed){recoveredActions.current.add(failed.id);void decide(failed.id,{decision:'retry'});}
 },[uploadedReview,purpose,conversation,loading,busy,unavailable]);
 const historical = Boolean(conversation && conversation.id !== newestId.current);
 const activeWork = Boolean(busy || unfinished || unconfirmedMessage);
 useEffect(()=>{onActivityChanged?.(activeWork);},[onActivityChanged,activeWork]);
 useEffect(()=>()=>onActivityChanged?.(false),[onActivityChanged]);
 // The first automatic turn owns the composer until its request starts.
 const awaitingFirstQuestion = uploadedReview && autoReview && !autoStarted.current && !hasReviewHistory &&
  !conversation?.active_question && !unfinished && !error && conversation?.purpose !== null;
 const blocked = Boolean(busy || unavailable || resumeBlocked || awaitingFirstQuestion || unconfirmedMessage || !conversation || conversation.read_only || historical);
 // Typing never waits on the AI. A message sent while elo is working is held and sent once it is free.
 const [queued, setQueued] = useState(false);
 const working = Boolean(busy) || pending || awaitingFirstQuestion;
 const canType = !(unavailable || resumeBlocked || !conversation || conversation.read_only || historical || unconfirmedMessage);
 function sendOrQueue() {if (!draft.trim()) return; if (working) setQueued(true); else void send(draft);}
 useEffect(() => {if (queued && !draft.trim()) setQueued(false);}, [queued, draft]);
 useEffect(() => {if (queued && !working && canType) {setQueued(false); void send(draft);}}); // eslint-disable-line react-hooks/exhaustive-deps
 function submit(event: FormEvent) {event.preventDefault(); sendOrQueue();}
 function keyboard(event: KeyboardEvent<HTMLTextAreaElement>) {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); sendOrQueue();}}
 const progress = conversation?.interview;
 const unverifiedTopics = progress?.topics?.filter(topic => topic.validation === 'unverified') ?? [];
 const question = conversation?.active_question;
 const sourceIds = [...(detail?.items.map(item => item.id) ?? []), ...(progress?.topics?.map(topic => topic.id) ?? []), ...(conversation?.active_question ? [conversation.active_question.item_id] : [])];
 const reviewPercent = reviewComplete ? 100 : progress?.total_items ? Math.round(100 * progress.reviewed_items / progress.total_items) : 0;
 const count = Array.from(draft).length, limit = conversation?.limits.max_message_chars ?? 4000;
 const exitBlocked = Boolean(busy && busy !== 'refreshing-message');
 const covered = (status: string) => ['reviewed', 'reviewed_with_gaps', 'deferred'].includes(status);
 const skippedCount = progress?.topics?.filter(topic => topic.status === 'deferred').length ?? 0;
 const remainingTopics = progress?.topics?.filter(topic => !covered(topic.status)) ?? [];
 const canSkip = uploadedReview && !historical && !blocked && !pending && !reviewComplete;
 function skipTopic(id: string) {const topic = progress?.topics?.find(item => item.id === id); setSkipping(null); if (topic) void send(`Skip ${topic.title}.`, 'skip_topic', id);}
 const progressBlock = purpose && progress && <div className="cv-review-progress">
  <p className="cv-review-count">{progress.reviewed_items} of {progress.total_items} topics covered</p>
  {progress.total_items>0&&<div className="cv-review-segments" role="progressbar" aria-label="Review progress" aria-valuemin={0} aria-valuemax={progress.total_items} aria-valuenow={progress.reviewed_items} aria-valuetext={`${progress.reviewed_items} of ${progress.total_items} topics covered${skippedCount?`, ${skippedCount} skipped`:''}`}>
   {Array.from({length:progress.total_items},(_,index)=>{const topic=progress.topics?.[index];const done=topic?covered(topic.status):index<progress.reviewed_items;return <span key={topic?.id??index} title={topic?`${topic.title}: ${topicStatus(topic, question)}`:undefined} className={topic?.status==='deferred'?'skipped':done?'covered':topic?.status==='current'?'current':''}/>;})}
  </div>}
  <p className="cv-review-percent">{`${reviewPercent}% of your experience reviewed`}{reviewComplete?' · Review complete':progress.status==='paused'?' · Paused':''}</p>
 </div>;
 const confirmSkip = (title: string, body: string, action: string, onConfirm: () => void) => <div className="cv-skip-confirm" role="group" aria-label={title}><p><strong>{title}</strong></p><p>{body}</p><div><button type="button" className="btn pri sm" disabled={!canSkip} onClick={onConfirm}>{action}</button><button type="button" className="btn sm" onClick={() => setSkipping(null)}>Keep reviewing</button></div></div>;
 const topicsBlock = progress?.topics ? <div className="cv-topic-checklist" role="group" aria-label="Review topics">
  <div className="cv-topic-head"><h3>Topics</h3>{canSkip && remainingTopics.length > 0 && <button type="button" className="cv-skip-link" aria-expanded={skipping?.scope === 'all'} onClick={() => setSkipping(skipping?.scope === 'all' ? null : {scope: 'all'})}>Skip all remaining</button>}</div>
  {skipping?.scope === 'all' && confirmSkip(remainingTopics.length === 1 ? 'Skip the last remaining topic?' : `Skip all ${remainingTopics.length} remaining topics?`, `elo will use your CV as written for ${remainingTopics.length === 1 ? 'it' : 'them'} and finish the review. Your saved answers stay.`, 'Skip all', () => {setSkipping(null); void send('Skip all remaining topics.', 'skip_remaining');})}
  {progressBlock}
  <ol>{progress.topics.map(topic=>{const done=covered(topic.status),now=topic.status==='current',skipped=topic.status==='deferred',warn=topic.validation==='unverified',confirming=skipping?.scope==='topic'&&skipping.id===topic.id;return <li key={topic.id} className={`${skipped?'is-skipped':done?'is-done':now?'is-now':''}${warn?' is-warning':''}${confirming?' is-confirming':''}`.trim()} aria-current={now?'step':undefined}>
   <span className="cv-topic-mark" aria-hidden="true">{warn?'!':done&&!skipped&&<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10"/></svg>}</span>
   <span><strong>{topic.title}</strong><small>{topicStatus(topic, question)}</small>{warn&&<small className="cv-topic-warning">Warning · could not be verified. Best explained in the chat.</small>}{warn&&<span className="cv-visually-hidden"> · warning, could not be verified</span>}</span>
   {canSkip && !done && !confirming && <button type="button" className="cv-skip-link" aria-label={`Skip ${topic.title}`} onClick={() => setSkipping({scope: 'topic', id: topic.id})}>Skip</button>}
   {skipped && uploadedReview && !historical && <button type="button" className="cv-skip-link" disabled={blocked || pending} aria-label={`Review ${topic.title} instead`} onClick={() => void send(`Review ${topic.title} instead.`, 'review_topic', topic.id)}>Review</button>}
   {confirming && confirmSkip('Skip this topic?', 'elo will use your CV as written and won’t ask about it. You can review it later.', 'Skip topic', () => skipTopic(topic.id))}
  </li>;})}</ol></div> : progressBlock;
 // What changed in the profile, read from the actions that were saved during the review.
 const savedActions = (kind: ConversationAction['kind']) => (conversation?.messages ?? []).flatMap(message => message.actions).filter(action => action.kind === kind && action.status === 'saved').map(action => action.item_title ?? action.title);
 const changes: [string, string[], boolean][] = [['Added', savedActions('add_capability'), false], ['Corrected', savedActions('correct'), false], ['Removed', savedActions('remove'), true]];
 const lastAssistant = [...(conversation?.messages ?? [])].reverse().find(message => message.role === 'assistant');
 return <section ref={chatPanel} className="cv-chat" style={{'--cv-rail-w': `${railWidth}px`} as React.CSSProperties} aria-label="CV conversation" hidden={hidden} data-unsaved={Boolean(draft || unconfirmedMessage || (uploadedReview && busy === 'message'))}>
  {(progress || (conversation && !conversation.context)) && <div className="cv-rail-resizer" role="separator" aria-orientation="vertical" aria-label="Resize topics sidebar" aria-valuemin={RAIL_MIN} aria-valuemax={RAIL_MAX} aria-valuenow={railWidth} tabIndex={0}
    onKeyDown={event => {if (event.key === 'ArrowLeft') {event.preventDefault(); resizeRail(railWidth - 16);} else if (event.key === 'ArrowRight') {event.preventDefault(); resizeRail(railWidth + 16);}}}
    onPointerDown={event => {event.preventDefault(); document.body.classList.add('cv-rail-dragging'); const left = chatPanel.current?.getBoundingClientRect().left ?? 0; const move = (e: PointerEvent) => resizeRail(e.clientX - left); const stop = () => {document.body.classList.remove('cv-rail-dragging'); window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop);}; window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop);}}/>}
  <header className="cv-chat-header"><div>{uploadedReview?<><span className="cv-chat-logo"><BrandLogo decorative/></span><span className="cv-chat-divider" aria-hidden="true"/></>:<span className="cv-chat-brand" aria-hidden="true"><BrandLogo compact decorative/></span>}<div><h2 tabIndex={uploadedReview ? -1 : undefined}>{uploadedReview ? 'Review your CV' : 'Let’s talk about your experience'}</h2><p>{detail?.display_name ?? detail?.file_name ?? 'Your capabilities'}{conversation && (!uploadedReview || started && !exitBlocked && !unconfirmedMessage) && <><span className="cv-chat-saved-dot" aria-hidden="true"/>{uploadedReview ? 'Sent messages saved' : 'Saved to your account'}</>}</p></div></div>
   {uploadedReview ? <button className="btn ghost sm" type="button" onClick={() => onReviewLater(Boolean(unconfirmedMessage))} disabled={exitBlocked}>{unconfirmedMessage ? 'Review later' : 'Save and review later'}</button> : <button className="btn ghost sm" type="button" onClick={onOpenSummary} aria-label="Back to Skills Profile"><span className="cv-chat-summary-desktop">Back to Skills Profile</span><span className="cv-chat-summary-mobile">Back</span></button>}
  </header>
  {(progress || (conversation && !conversation.context)) && <aside className="cv-review-rail" aria-label="Review progress and topics">
   {unverifiedTopics.length>0&&<p className="cv-rail-warning" role="status"><strong>Warning</strong> · {unverifiedTopics.length} {unverifiedTopics.length===1?'section':'sections'} could not be verified against your CV. {unverifiedTopics.length===1?'It is':'They are'} kept as unconfirmed, so explain {unverifiedTopics.length===1?'it':'them'} here in the chat.</p>}
   {topicsBlock}
  </aside>}
{(conversation?.context_error || conversation?.context) && <div className="cv-chat-context">{conversation?.context_error ? <><span>{conversation.context_error}</span><button type="button" className="text-link" onClick={() => void refresh().catch(cause => setError(errorText(cause, 'Could not refresh the career context.')))}>Retry career context</button></> : conversation?.context ? <><span>Reviewing for <strong>{conversation.context.role}</strong></span></> : null}</div>}
  {historical && <div className="cv-chat-history-banner"><span>Earlier conversation · read only</span><button className="btn ghost sm" type="button" disabled={Boolean(busy) || historyLoading} onClick={() => void history(newestId.current!)}>Return to current conversation</button></div>}
  <div ref={scrollArea} className="cv-chat-messages" onScroll={() => {const area = scrollArea.current; if (area) nearBottom.current = area.scrollHeight - area.scrollTop - area.clientHeight < 90;}}>
   {loading && <ChatSkeleton label="Opening your saved conversation…"/>}
   {resumeBlocked && !error && <ChatSkeleton label="Checking your saved review…"/>}
   {!loading && !conversation && <div className="cv-chat-welcome"><h3>Your conversation will be here.</h3><p>Retry to restore your messages. Your saved CV details are still available in the summary.</p><button className="btn ghost" type="button" onClick={() => void open()}>Retry conversation</button></div>}
   {conversation && <>
    <div className="cv-chat-history-controls">{conversation.next_before !== null && <button className="btn ghost sm" type="button" disabled={historyLoading || Boolean(busy)} onClick={() => void history()}>Show earlier messages</button>}{conversation.previous_conversation_id && <button className="btn ghost sm" type="button" disabled={historyLoading || Boolean(busy)} onClick={() => void history(conversation.previous_conversation_id!)}>Previous conversation</button>}</div>
    {!conversation.messages.length && <div className="cv-chat-welcome"><div className="cv-chat-mark" aria-hidden="true"><BrandLogo compact decorative/></div><h3>Your experience has a story.</h3><p>{cvId ? 'We’ll work through the details that matter, one question at a time. You can add context, correct something or ask a question whenever you like.' : 'Tell me about a capability you want to include, or upload a CV to start from what you already have.'}</p>{cvId && !purpose && <button className="btn pri" type="button" disabled={blocked} onClick={() => void send('Review my CV with me.', 'review')}>Review with me</button>}</div>}
    <ol className="cv-chat-transcript" aria-label="Saved conversation messages">{conversation.messages.map((message,index) => <li key={message.id} className={`cv-chat-message cv-chat-message-${message.role}${message === lastAssistant && question && !historical && message.text.includes(question.question) ? ' is-question' : ''}`}>{(index===0||message.created_at.slice(0,10)!==conversation.messages[index-1].created_at.slice(0,10))&&<p className="cv-chat-day">{formatDate(message.created_at.slice(0,10))}</p>}{message.role === 'assistant' && <span className="cv-chat-avatar" aria-hidden="true"><BrandLogo compact decorative/></span>}<div className="cv-chat-speaker">{message.role === 'user' ? 'You' : 'elo'}<time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})}</time></div><div className="cv-chat-bubble">{uploadedReview && question && message === lastAssistant && !historical && message.text.includes(question.question) && <QuestionLabel question={question} sourceIds={sourceIds}/>}{!(purpose && message.role === 'assistant' && failureReply(message)) && <p>{message.role === 'assistant' ? humaniseText(reviewText(message.text, sourceIds)) : message.text}</p>}{uploadedReview && question && message === lastAssistant && !historical && message.text.includes(question.question) && <AnswerHints hints={question.hints}/>}{message.actions.map(action => <ActionCard key={`${action.id}:${action.status}`} action={action} busy={Boolean(busy)} readOnly={historical} review={Boolean(purpose)} decide={(id, decision) => void decide(id, decision)}/>)}</div></li>)}</ol>
   </>}
   <div className="cv-chat-inline-actions">
   {conversation?.interview&&conversation.interview.status!=='reviewing'&&conversation.interview.status!=='reviewed'&&<p className="small" role="status">{conversation.interview.status==='paused'?'Review paused. Continue whenever you’re ready.':conversation.interview.status==='reviewed_with_gaps'?'Review complete with some details still uncertain.':'Experience review complete.'}</p>}
   {conversation?.interview?.estimates.filter(estimate=>estimate.level!=='insufficient_evidence').map(estimate=><details key={`${estimate.item_id}:${estimate.skill_name}`}><summary>{estimate.skill_name} · {detail?.items.find(item=>item.id===estimate.item_id)?.title??'Experience'} · {estimate.level.replaceAll('_',' ')}</summary><p className="small">{reviewText(estimate.explanation, sourceIds)}</p><p className="small">Based on your CV and conversation; practical proficiency has not been tested.</p></details>)}
   {uploadedReview && question && !historical && !conversation?.messages.some(message => message.role === 'assistant' && message.text.includes(question.question)) && <p className="cv-chat-current-question">{reviewText(question.question, sourceIds)}</p>}
   {question && !historical && <div className="cv-chat-quick-actions">
    <button type="button" disabled={blocked || (uploadedReview && pending)} onClick={() => void send('Skip this question.', 'skip')}>Skip this question</button>
    {["I didn't do this",'Not sure'].map(reply=><button type="button" key={reply} disabled={blocked} onClick={()=>setDraft(reply)}>{reply}</button>)}
    {uploadedReview&&<button type="button" disabled={!canSkip} aria-expanded={skipping?.scope==='chat'} onClick={()=>setSkipping(skipping?.scope==='chat'?null:{scope:'chat'})}>Skip this topic</button>}
   </div>}
   {skipping?.scope === 'chat' && question && uploadedReview && !historical && <div className="cv-chat-message cv-chat-message-assistant cv-skip-chat"><span className="cv-chat-avatar" aria-hidden="true"><BrandLogo compact decorative/></span><div className="cv-chat-speaker">elo</div><div className="cv-chat-bubble is-confirm">{confirmSkip(`Skip ${reviewText(question.title, sourceIds)}?`, 'I’ll use what your CV says about it, as written, and won’t ask you questions about it. You can come back and review it later.', 'Skip topic', () => skipTopic(question.item_id))}</div></div>}
   {uploadedReview && conversation && !question && !blocked && !loading && !reviewComplete && !unfinished && conversation.purpose !== null && (hasReviewHistory || !autoReview || Boolean(error)) && <div className="cv-chat-quick-actions"><button type="button" onClick={() => void send(hasReviewHistory ? 'Continue reviewing my CV.' : 'Review my CV.', hasReviewHistory ? 'continue' : 'review')}>{hasReviewHistory ? 'Continue review' : 'Start review'}</button></div>}
   {purpose && cvId && conversation && !conversation.active_question && !historical && conversation.interview?.topics?.some(topic=>topic.status==='current') && conversation.messages.some(message=>message.actions.some(action=>action.kind==='route'&&action.status==='failed'&&action.error?.startsWith('The interview could not choose a valid next step.'))) && <div className="cv-chat-quick-actions"><button type="button" disabled={blocked} onClick={()=>void send('Skip remaining questions for this experience.', 'skip')}>Skip and continue</button></div>}
   {!purpose && conversation && !conversation.active_question && conversation.messages.length > 0 && (cvId || purpose) && !historical && !conversation.read_only && <div className="cv-chat-quick-actions"><button type="button" disabled={blocked} onClick={() => void send(cvId?(started ? 'Continue reviewing my CV.' : 'Review my CV with me.'):'Continue building my skills profile.', started ? 'continue' : 'review')}>{started ? 'Continue review' : 'Review with me'}</button></div>}
   {purpose&&reviewComplete&&!historical&&<section className="cv-chat-done" aria-labelledby="cv-done-title">
    <div className="cv-chat-done-head"><span aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10"/></svg></span><div><h3 id="cv-done-title">Your CV review is complete</h3><p>{(sent => `You sent ${sent} ${sent === 1 ? 'answer' : 'answers'} across ${progress!.total_items} ${progress!.total_items === 1 ? 'topic' : 'topics'}.`)(conversation!.messages.filter(message => message.role === 'user').length)}</p></div></div>
    {changes.some(([, items]) => items.length) && <div className="cv-chat-done-changes">{changes.filter(([, items]) => items.length).map(([label, items, out]) => <div key={label}><p>{label} ({items.length})</p><p>{items.map((item, index) => <span key={`${item}:${index}`} className={`cv-chat-pill${out ? ' is-out' : ''}`}>{item}</span>)}</p></div>)}</div>}
    <div className="cv-chat-done-actions"><button className="btn pri" type="button" disabled={blocked||unfinished} onClick={onOpenSummary}>View Skills Profile</button><Link className="btn" href="/roadmap">Generate roadmap</Link></div>
   </section>}
   </div>
   {busy === 'message' && <p className="cv-chat-working" role="status">{uploadedReview && !hasReviewHistory ? 'Preparing your first question…' : 'Checking your message…'}</p>}
  </div>
  <div className="cv-chat-composer-wrap">
   {(error || unconfirmedMessage) && <div role="alert" className="cv-error"><p>{unconfirmedMessage ? 'We couldn’t confirm your last message was sent.' : error}</p>
    {/* One action per failure. Resending reuses the same message ID, so it also confirms a send that did arrive. */}
    {unconfirmedMessage ? <button type="button" className="btn ghost sm" disabled={Boolean(busy) || unavailable || historical || resumeBlocked} onClick={() => void send(unconfirmedMessage.text, unconfirmedMessage.command, unconfirmedMessage.item_id)}>Try again</button>
    : conversation && <button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={() => uploadedReview ? void checkSavedReview() : void refresh().then(() => setError('')).catch(cause => setError(errorText(cause, 'Could not refresh saved messages.')))}>Check saved messages</button>}
   </div>}
   {conversation?.read_only && !historical ? <div className="cv-chat-limit"><p>This part of your conversation is full. Its messages will stay available when you continue.{conversation.next_before !== null ? ' Checking earlier messages for outstanding actions.' : unfinished && ' Finish or cancel the outstanding actions above first.'}</p><button className="btn pri" type="button" disabled={Boolean(busy) || loading || historyLoading || conversation.next_before !== null || unfinished} onClick={() => {openKey.current = crypto.randomUUID(); void open();}}>Continue in a new conversation</button></div> : !historical && <form className="cv-chat-composer" onSubmit={submit} aria-busy={Boolean(busy)}><label className="cv-visually-hidden" htmlFor={`cv-chat-input-${cvId ?? 'manual'}`}>Message elo</label><textarea id={`cv-chat-input-${cvId ?? 'manual'}`} ref={composer} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={keyboard} placeholder="Add context, ask a question, or correct something…" rows={2} disabled={!canType} aria-invalid={count > limit} aria-describedby="cv-chat-input-help"/><div className="cv-chat-composer-footer"><p id="cv-chat-input-help" className={conversation?.active_question && count <= limit * 0.8 && !queued ? 'cv-visually-hidden' : undefined}>{queued ? 'Your message will send as soon as elo finishes.' : count > limit * 0.8 ? `${count} / ${limit} characters` : 'Enter to send · Shift + Enter for a new line'}</p><button type="submit" className="btn pri" disabled={!canType || queued || !draft.trim() || count > limit} aria-label="Send message">{busy === 'message' ? 'Sending…' : queued ? 'Queued' : 'Send'}<span aria-hidden="true">↑</span></button></div></form>}
   <p className="cv-chat-footnote">{uploadedReview ? 'Sent answers save automatically. You can return to this CV from Skills Profile.' : 'Only what you share is used. Unknown details can stay unknown.'}</p>
  </div>
  <p className="cv-visually-hidden" role="status" aria-live="polite">{announcement}</p>
 </section>;
}

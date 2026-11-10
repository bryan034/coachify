"use client";
import { InlineGoalConfirmation } from '@/features/career/inline-goal-confirmation';
import { reviewText } from './review-text';
import { BrandLogo } from '@/components/ui/brand-logo';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type Dispatch, type SetStateAction } from 'react';
import { cvApi, CvApiError } from '@/lib/api/cv';
import type { ConversationAction, ConversationDecision, ConversationInput, ConversationMessage, CvConversation, CvDetail } from './types';
import { errorText } from '@/lib/errors';
import { humaniseText, formatDate } from '@/lib/format';
import { ChatSkeleton } from '@/components/ui/workspace-ui';

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

/** An assistant reply that only repeats the failure shown by its recovery card. */
const FAILURE_REPLY = /^(your answer is saved\. we couldn’t finish processing it|chat interpretation is unavailable)/i;
function failureReply(message: CvConversation['messages'][number]) {
 return FAILURE_REPLY.test(message.text.trim()) && message.actions.some(action => action.status === 'failed' || action.status === 'stale');
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
 const [hintFor, setHintFor] = useState<string | null>(null);
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

 async function send(text: string, command?: ConversationInput['command']) {
  const active = current.current;
  const signature = JSON.stringify({text, command});
  const previousAttempt = messageAttempts.current.get(signature);
  const recovering = Boolean(unconfirmedMessage && previousAttempt?.body.mutation_id === unconfirmedMessage.mutation_id);
  if (!active || busy || unavailable || resumeBlocked || active.id !== newestId.current || !text.trim() || (unconfirmedMessage && !recovering)) return;
  if (!recovering && (active.read_only || active.messages.some(message => message.actions.some(action => action.status === 'pending')))) return;
  if (Array.from(text).length > active.limits.max_message_chars) {setError(`Keep your message within ${active.limits.max_message_chars} characters. Your draft is still here.`); return;}
  // An interrupted response may already be saved. Other sends must not replace
  // its original receipt, revision or segment before that outcome is resolved.
  const attempt = previousAttempt ?? {conversationId: active.id, body: {expected_revision: active.revision, mutation_id: crypto.randomUUID(), text, ...(command ? {command} : {})}};
  messageAttempts.current.set(signature, attempt);
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
   setAnnouncement(currentSegment ? command === 'skip' ? 'Skipped. Unclarified details remain uncertain; the review can continue.' : 'Your message is saved. Review the response for any changes or actions needing attention.' : 'Your earlier message is saved in the previous conversation.');
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
 function submit(event: FormEvent) {event.preventDefault(); void send(draft);}
 function keyboard(event: KeyboardEvent<HTMLTextAreaElement>) {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void send(draft);}}
 const upgrading = useRef(false);
 useEffect(()=>{if(!purpose||!conversation||loading||busy)return;if(conversation.purpose===purpose){upgrading.current=false;return;}if(conversation.purpose===null&&!conversation.messages.some(hasOutstandingAction)&&!upgrading.current){upgrading.current=true;void open();}},[purpose,conversation,loading,busy,open]);
 const started = conversation?.messages.some(message => message.role === 'user') ?? false;
 const unfinished = conversation?.messages.some(hasOutstandingAction) ?? false;
 const hasReviewHistory = Boolean(started || conversation?.interview || conversation?.previous_conversation_id || conversation?.next_before != null);
 const reviewComplete = Boolean(conversation?.interview && ['reviewed','reviewed_with_gaps'].includes(conversation.interview.status));
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
 const progress = conversation?.interview;
 const question = conversation?.active_question;
 const sourceIds = [...(detail?.items.map(item => item.id) ?? []), ...(progress?.topics?.map(topic => topic.id) ?? []), ...(conversation?.active_question ? [conversation.active_question.item_id] : [])];
 const reviewPercent = reviewComplete ? 100 : progress?.total_items ? Math.round(100 * progress.reviewed_items / progress.total_items) : 0;
 const count = Array.from(draft).length, limit = conversation?.limits.max_message_chars ?? 4000;
 const exitBlocked = Boolean(busy && busy !== 'refreshing-message');
 const hintOpen = Boolean(question && hintFor === question.id);
 return <section ref={chatPanel} className="cv-chat" aria-label="CV conversation" hidden={hidden} data-unsaved={Boolean(draft || unconfirmedMessage || (uploadedReview && busy === 'message'))}>
  <header className="cv-chat-header"><div><span className="cv-chat-brand" aria-hidden="true"><BrandLogo compact decorative/></span><div><h2 tabIndex={uploadedReview ? -1 : undefined}>{uploadedReview ? 'Review your CV' : 'Let’s talk about your experience'}</h2><p>{detail?.display_name ?? detail?.file_name ?? 'Your capabilities'}{conversation && (!uploadedReview || started && !exitBlocked && !unconfirmedMessage) && <><span className="cv-chat-saved-dot" aria-hidden="true"/>{uploadedReview ? 'Sent messages saved' : 'Saved to your account'}</>}</p></div></div>
   {uploadedReview ? <button className="btn ghost sm" type="button" onClick={() => onReviewLater(Boolean(unconfirmedMessage))} disabled={exitBlocked}>{unconfirmedMessage ? 'Review later' : 'Save and review later'}</button> : <button className="btn ghost sm" type="button" onClick={onOpenSummary} aria-label="Back to Skills Profile"><span className="cv-chat-summary-desktop">Back to Skills Profile</span><span className="cv-chat-summary-mobile">Back</span></button>}
  </header>
  {(progress || (conversation && !conversation.context)) && <aside className="cv-review-rail" aria-label="Review progress and topics">
   {purpose && progress && <div className="cv-review-progress">
   <div className="row between"><span>{progress.reviewed_items} of {progress.total_items} topics covered</span><span>{reviewPercent}% · {reviewComplete?'Review complete':progress.status==='paused'?'Paused':'Experience review'}</span></div>
   {progress.total_items>0&&<div className="cv-review-segments" role="progressbar" aria-label="Review progress" aria-valuemin={0} aria-valuemax={progress.total_items} aria-valuenow={progress.reviewed_items} aria-valuetext={`${progress.reviewed_items} of ${progress.total_items} topics covered`}>
    {Array.from({length:progress.total_items},(_,index)=>{const topic=progress.topics?.[index];const covered=topic?['reviewed','reviewed_with_gaps','deferred'].includes(topic.status):index<progress.reviewed_items;return <span key={topic?.id??index} title={topic?`${topic.title}: ${topic.status.replaceAll('_',' ')}`:undefined} className={covered?'covered':topic?.status==='current'?'current':''}/>;})}
   </div>}
  </div>}
   {progress?.topics&&<div className="cv-topic-checklist" role="group" aria-label="Review topics"><h3>Topics</h3><ol>{progress.topics.map(topic=>{const done=['reviewed','reviewed_with_gaps','deferred'].includes(topic.status),now=topic.status==='current';return <li key={topic.id} className={done?'is-done':now?'is-now':''} aria-current={now?'step':undefined}><span className="cv-topic-mark" aria-hidden="true">{done?'✓':''}</span><span><strong>{topic.title}</strong><small>{done?'Done':now?'Now':'Up next'}</small></span><span className="cv-visually-hidden"> · {topic.status.replaceAll('_',' ')}</span></li>;})}</ol></div>}
   {conversation && !conversation.context && <details className="cv-inline-confirmation"><summary>Focus on your goal?</summary><InlineGoalConfirmation token={token} onConfirmed={() => { void refresh().catch(() => {}); }}/></details>}
  </aside>}
<div className="cv-chat-context">{conversation?.context_error ? <><span>{conversation.context_error}</span><button type="button" className="text-link" onClick={() => void refresh().catch(cause => setError(errorText(cause, 'Could not refresh the career context.')))}>Retry career context</button></> : conversation?.context ? <><span>Reviewing for <strong>{conversation.context.role}</strong></span><Link href="/career-goal" className="text-link">Open Career Goal</Link></> : <><span>You can review your experience now. A confirmed target helps focus the questions.</span><Link href="/career-goal" className="text-link">Open Career Goal</Link></>}</div>
  {historical && <div className="cv-chat-history-banner"><span>Earlier conversation · read only</span><button className="btn ghost sm" type="button" disabled={Boolean(busy) || historyLoading} onClick={() => void history(newestId.current!)}>Return to current conversation</button></div>}
  <div ref={scrollArea} className="cv-chat-messages" onScroll={() => {const area = scrollArea.current; if (area) nearBottom.current = area.scrollHeight - area.scrollTop - area.clientHeight < 90;}}>
   {loading && <ChatSkeleton label="Opening your saved conversation…"/>}
   {resumeBlocked && !error && <ChatSkeleton label="Checking your saved review…"/>}
   {!loading && !conversation && <div className="cv-chat-welcome"><h3>Your conversation will be here.</h3><p>Retry to restore your messages. Your saved CV details are still available in the summary.</p><button className="btn ghost" type="button" onClick={() => void open()}>Retry conversation</button></div>}
   {conversation && <>
    <div className="cv-chat-history-controls">{conversation.next_before !== null && <button className="btn ghost sm" type="button" disabled={historyLoading || Boolean(busy)} onClick={() => void history()}>Show earlier messages</button>}{conversation.previous_conversation_id && <button className="btn ghost sm" type="button" disabled={historyLoading || Boolean(busy)} onClick={() => void history(conversation.previous_conversation_id!)}>Previous conversation</button>}</div>
    {!conversation.messages.length && <div className="cv-chat-welcome"><div className="cv-chat-mark" aria-hidden="true"><BrandLogo compact decorative/></div><h3>Your experience has a story.</h3><p>{cvId ? 'We’ll work through the details that matter, one question at a time. You can add context, correct something or ask a question whenever you like.' : 'Tell me about a capability you want to include, or upload a CV to start from what you already have.'}</p>{cvId && !purpose && <button className="btn pri" type="button" disabled={blocked} onClick={() => void send('Review my CV with me.', 'review')}>Review with me</button>}</div>}
    <ol className="cv-chat-transcript" aria-label="Saved conversation messages">{conversation.messages.map((message,index) => <li key={message.id} className={`cv-chat-message cv-chat-message-${message.role}`}>{(index===0||message.created_at.slice(0,10)!==conversation.messages[index-1].created_at.slice(0,10))&&<p className="cv-chat-day">{formatDate(message.created_at.slice(0,10))}</p>}<div className="cv-chat-speaker">{message.role === 'user' ? 'You' : 'elo'}<time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'})}</time></div><div className="cv-chat-bubble">{!(purpose && message.role === 'assistant' && failureReply(message)) && <p>{message.role === 'assistant' ? humaniseText(reviewText(message.text, sourceIds)) : message.text}</p>}{message.actions.map(action => <ActionCard key={`${action.id}:${action.status}`} action={action} busy={Boolean(busy)} readOnly={historical} review={Boolean(purpose)} decide={(id, decision) => void decide(id, decision)}/>)}</div></li>)}</ol>
   </>}
   <div className="cv-chat-inline-actions">
   {conversation?.interview&&conversation.interview.status!=='reviewing'&&<p className="small" role="status">{conversation.interview.status==='paused'?'Review paused. Continue whenever you’re ready.':conversation.interview.status==='reviewed_with_gaps'?'Review complete with some details still uncertain.':'Experience review complete.'}</p>}
   {conversation?.interview?.estimates.filter(estimate=>estimate.level!=='insufficient_evidence').map(estimate=><details key={`${estimate.item_id}:${estimate.skill_name}`}><summary>{estimate.skill_name} · {detail?.items.find(item=>item.id===estimate.item_id)?.title??'Experience'} · {estimate.level.replaceAll('_',' ')}</summary><p className="small">{reviewText(estimate.explanation, sourceIds)}</p><p className="small">Based on your CV and conversation; practical proficiency has not been tested.</p></details>)}
   {uploadedReview && question && !historical && !conversation?.messages.some(message => message.role === 'assistant' && message.text.includes(question.question)) && <p className="cv-chat-current-question">{reviewText(question.question, sourceIds)}</p>}
   {question && !historical && <div className="cv-chat-quick-actions">
    {uploadedReview ? <button type="button" aria-expanded={hintOpen} onClick={() => setHintFor(hintOpen ? null : question.id)}>Why this question?</button> : <button type="button" disabled={blocked} onClick={() => void send('Why are you asking this question?')}>Why this question?</button>}
    <button type="button" disabled={blocked || (uploadedReview && pending)} onClick={() => void send('Skip this question.', 'skip')}>Skip this question</button>
   </div>}
   {hintOpen && uploadedReview && question && !historical && <p className="small cv-chat-hint">Your answer helps clarify what you personally did in {reviewText(question.title, sourceIds)}. You can skip if you’re unsure.</p>}
   {uploadedReview && conversation && !question && !blocked && !loading && !reviewComplete && !unfinished && conversation.purpose !== null && (hasReviewHistory || !autoReview || Boolean(error)) && <div className="cv-chat-quick-actions"><button type="button" onClick={() => void send(hasReviewHistory ? 'Continue reviewing my CV.' : 'Review my CV.', hasReviewHistory ? 'continue' : 'review')}>{hasReviewHistory ? 'Continue review' : 'Start review'}</button></div>}
   {purpose && cvId && conversation && !conversation.active_question && !historical && conversation.interview?.topics?.some(topic=>topic.status==='current') && conversation.messages.some(message=>message.actions.some(action=>action.kind==='route'&&action.status==='failed'&&action.error?.startsWith('The interview could not choose a valid next step.'))) && <div className="cv-chat-quick-actions"><button type="button" disabled={blocked} onClick={()=>void send('Skip remaining questions for this experience.', 'skip')}>Skip and continue</button></div>}
   {!purpose && conversation && !conversation.active_question && conversation.messages.length > 0 && (cvId || purpose) && !historical && !conversation.read_only && <div className="cv-chat-quick-actions"><button type="button" disabled={blocked} onClick={() => void send(cvId?(started ? 'Continue reviewing my CV.' : 'Review my CV with me.'):'Continue building my skills profile.', started ? 'continue' : 'review')}>{started ? 'Continue review' : 'Review with me'}</button></div>}
   {purpose&&reviewComplete&&!historical&&<div className="cv-chat-quick-actions"><button className="btn pri" type="button" disabled={blocked||unfinished} onClick={onOpenSummary}>Review profile</button></div>}
   </div>
   {busy === 'message' && <p className="cv-chat-working" role="status">{uploadedReview && !hasReviewHistory ? 'Preparing your first question…' : 'Checking your message…'}</p>}
  </div>
  <div className="cv-chat-composer-wrap">
   {(error || unconfirmedMessage) && <div role="alert" className="cv-error"><p>{unconfirmedMessage ? 'We couldn’t confirm your last message was sent.' : error}</p>
    {/* One action per failure. Resending reuses the same message ID, so it also confirms a send that did arrive. */}
    {unconfirmedMessage ? <button type="button" className="btn ghost sm" disabled={Boolean(busy) || unavailable || historical || resumeBlocked} onClick={() => void send(unconfirmedMessage.text, unconfirmedMessage.command)}>Try again</button>
    : conversation && <button type="button" className="btn ghost sm" disabled={Boolean(busy)} onClick={() => uploadedReview ? void checkSavedReview() : void refresh().then(() => setError('')).catch(cause => setError(errorText(cause, 'Could not refresh saved messages.')))}>Check saved messages</button>}
   </div>}
   {conversation?.read_only && !historical ? <div className="cv-chat-limit"><p>This part of your conversation is full. Its messages will stay available when you continue.{conversation.next_before !== null ? ' Checking earlier messages for outstanding actions.' : unfinished && ' Finish or cancel the outstanding actions above first.'}</p><button className="btn pri" type="button" disabled={Boolean(busy) || loading || historyLoading || conversation.next_before !== null || unfinished} onClick={() => {openKey.current = crypto.randomUUID(); void open();}}>Continue in a new conversation</button></div> : !historical && <form className="cv-chat-composer" onSubmit={submit} aria-busy={Boolean(busy)}><label className="cv-visually-hidden" htmlFor={`cv-chat-input-${cvId ?? 'manual'}`}>Message elo</label><textarea id={`cv-chat-input-${cvId ?? 'manual'}`} ref={composer} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={keyboard} placeholder="Add context, ask a question, or correct something…" rows={2} disabled={blocked} aria-invalid={count > limit} aria-describedby="cv-chat-input-help"/><div className="cv-chat-composer-footer">{conversation?.active_question&&<div className="cv-quick-replies">{["I didn't do this",'Not sure'].map(reply=><button type="button" className="chip" key={reply} disabled={blocked} onClick={()=>setDraft(reply)}>{reply}</button>)}</div>}<p id="cv-chat-input-help" className={conversation?.active_question && count <= limit * 0.8 ? 'cv-visually-hidden' : undefined}>{count > limit * 0.8 ? `${count} / ${limit} characters` : 'Enter to send · Shift + Enter for a new line'}</p><button type="submit" className="btn pri" disabled={blocked || pending || !draft.trim() || count > limit} aria-label="Send message">{busy === 'message' ? 'Sending…' : 'Send'}<span aria-hidden="true">↑</span></button></div></form>}
   <p className="cv-chat-footnote">{uploadedReview ? 'Sent answers save automatically. You can return to this CV from Skills Profile.' : 'Only what you share is used. Unknown details can stay unknown.'}</p>
  </div>
  <p className="cv-visually-hidden" role="status" aria-live="polite">{announcement}</p>
 </section>;
}

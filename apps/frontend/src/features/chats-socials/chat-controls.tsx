"use client";

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { errorText } from '@/lib/errors';
import type { ChatStatus } from '@/lib/api/socials';

const singaporeTime = new Intl.DateTimeFormat('en-SG', {
 weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Singapore',
});

export const chatTime = (value: string) => `${singaporeTime.format(Date.parse(value))} SGT`;
export const chatStatus: Record<ChatStatus, string> = {
 submitting: 'Sending request', requested: 'Waiting for reply', accepted: 'Confirmed', declined: 'Declined · credit returned',
 expired: 'Expired · credit returned', slot_unavailable: 'Time unavailable · credit returned',
};

export function useChatCommand<T extends object, R>(submit: (body: T & { mutation_id: string }) => Promise<R>) {
 const [busy, setBusy] = useState(false);
 const [error, setError] = useState('');
 const attempt = useRef<{ payload: string; id: string } | null>(null);
 const running = useRef(false);

 async function run(body: T, saved: (value: R) => void, failed?: (cause: unknown) => void) {
  if (running.current) return;
  running.current = true;
  setBusy(true);
  setError('');
  const payload = JSON.stringify(body);
  if (attempt.current?.payload !== payload) attempt.current = { payload, id: crypto.randomUUID() };
  try {
   const result = await submit({ ...body, mutation_id: attempt.current.id });
   attempt.current = null;
   saved(result);
  } catch (cause) {
   setError(errorText(cause, 'The change could not be confirmed. Try again.'));
   failed?.(cause);
  } finally {
   running.current = false;
   setBusy(false);
  }
 }

 return { busy, error, run };
}

export function ChatDialog({ title, children, close, busy }: { title: string; children: ReactNode; close: () => void; busy: boolean }) {
 const dialog = useRef<HTMLDialogElement>(null);
 useEffect(() => {
  const node = dialog.current;
  node?.showModal();
  return () => { node?.close(); };
 }, []);

 return <dialog ref={dialog} className="socials-dialog" aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) close(); }}>
  <header><h2>{title}</h2><button type="button" className="btn ghost sm" disabled={busy} onClick={close}>Close</button></header>
  {children}
 </dialog>;
}

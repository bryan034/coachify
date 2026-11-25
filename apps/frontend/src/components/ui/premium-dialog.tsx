"use client";
import { useEffect, useRef, useState } from 'react';
import { PREMIUM_REQUIRED_EVENT, type PremiumFeature } from '@/lib/api/premium';

const COPY: Record<PremiumFeature, { title: string; free: string }> = {
 career: { title: 'Changing your career goal', free: 'You can keep refining your current goal and asking questions about it.' },
 cv: { title: 'Analysing another CV', free: 'Your first CV stays available, and you can retry its analysis if it fails.' },
 roadmap: { title: 'Task breakdowns after your first two weeks', free: 'Every week keeps its goal, and you can add your own tasks to any week.' },
};

function feature(value: unknown): PremiumFeature | null {
 const detail = value && typeof value === 'object' && 'feature' in value ? value.feature : null;
 return detail === 'career' || detail === 'cv' || detail === 'roadmap' ? detail : null;
}

export function PremiumDialog() {
 const [open, setOpen] = useState<PremiumFeature | null>(null);
 const close = useRef<HTMLButtonElement>(null);
 const returnTo = useRef<HTMLElement | null>(null);
 useEffect(() => {
  const show = (event: Event) => {
   const next = feature((event as CustomEvent).detail);
   if (!next) return;
   if (document.activeElement instanceof HTMLElement && !document.activeElement.closest('.premium-dialog')) returnTo.current = document.activeElement;
   setOpen(next);
  };
  window.addEventListener(PREMIUM_REQUIRED_EVENT, show);
  return () => window.removeEventListener(PREMIUM_REQUIRED_EVENT, show);
 }, []);
 useEffect(() => { if (open) close.current?.focus(); }, [open]);
 if (!open) return null;
 const dismiss = () => { setOpen(null); returnTo.current?.focus(); returnTo.current = null; };
 const copy = COPY[open];
 return <div className="premium-dialog-veil" onClick={event => { if (event.target === event.currentTarget) dismiss(); }}>
  <div className="premium-dialog" role="dialog" aria-modal="true" aria-labelledby="premium-dialog-title" aria-describedby="premium-dialog-description"
   onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); dismiss(); } else if (event.key === 'Tab') { event.preventDefault(); close.current?.focus(); } }}>
   <p className="premium-dialog-tag">Premium feature</p>
   <h2 id="premium-dialog-title">{copy.title}</h2>
   <p id="premium-dialog-description">{copy.title} is part of elo Premium. Upgrades are coming soon.</p>
   <p className="small">{copy.free}</p>
   <div className="premium-dialog-actions"><button ref={close} type="button" className="btn pri" onClick={dismiss}>Close</button></div>
  </div>
 </div>;
}

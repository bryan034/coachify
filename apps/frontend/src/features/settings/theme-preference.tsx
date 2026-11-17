"use client";
import { useEffect } from 'react';
export type Appearance = 'system' | 'light' | 'dark';
export function applyAppearance(mode: Appearance) {
 const dark = mode === 'dark' || (mode === 'system' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
 document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}
export function ThemePreference() {
 useEffect(() => {
  const read = () => { let saved = 'system'; try { saved = localStorage.getItem('elo-appearance') || saved; } catch {} applyAppearance(saved === 'light' || saved === 'dark' ? saved : 'system'); };
  const media = window.matchMedia?.('(prefers-color-scheme: dark)'); read(); media?.addEventListener('change', read); window.addEventListener('storage', read); window.addEventListener('elo-appearance', read);
  return () => {media?.removeEventListener('change', read); window.removeEventListener('storage', read); window.removeEventListener('elo-appearance', read);};
 }, []);
 return null;
}

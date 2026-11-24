"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

export function useToast(): [ReactNode, (message: string) => void] {
 const [message, setMessage] = useState(''), [shown, setShown] = useState(false);
 const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
 useEffect(() => () => clearTimeout(timer.current), []);
 const show = useCallback((text: string) => {
  setMessage(text); setShown(true);
  clearTimeout(timer.current);
  timer.current = setTimeout(() => setShown(false), 2600);
 }, []);
 return [<div key="toast" className={`ws-toast${shown ? ' show' : ''}`} role="status" aria-live="polite">{message}</div>, show];
}

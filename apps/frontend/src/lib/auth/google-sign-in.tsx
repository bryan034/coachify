"use client";
import Script from 'next/script';
import { useCallback, useRef, useState } from 'react';

type GoogleIdentity = { accounts: { id: {
  initialize: (options: { client_id: string; nonce?: string; callback: (response: { credential: string }) => void }) => void;
  renderButton: (element: HTMLElement, options: { theme: string; size: string }) => void;
  disableAutoSelect: () => void;
} } };
declare global { interface Window { google?: GoogleIdentity } }

export function GoogleSignIn({ onCredential, nonce }: { nonce: string; onCredential: (credential: string) => void }) {
  const button = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const render = useCallback(() => {
    if (!clientId || !button.current || !window.google) return;
    window.google.accounts.id.initialize({ client_id: clientId, nonce, callback: response => onCredential(response.credential) });
    button.current.replaceChildren();
    window.google.accounts.id.renderButton(button.current, { theme: 'outline', size: 'large' });
  }, [clientId, onCredential, nonce]);
  if (!clientId) return <p role="status">Sign-in is not configured yet. Contact your Coachify administrator to enable saving.</p>;
  return <>
    <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" onReady={render}
      onError={() => setError('Google sign-in could not load. Check your connection and reload.')} />
    <div ref={button} />{error && <p role="alert">{error}</p>}
  </>;
}

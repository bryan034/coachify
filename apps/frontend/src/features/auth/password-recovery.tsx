"use client";
import Link from 'next/link';
import { useRef, useState, type FormEvent } from 'react';
import { profileApi } from '@/lib/api/profile';
import { AccessFrame } from './access-screen';

export function PasswordRecovery() {
 const [email, setEmail] = useState('');
 const [challenge, setChallenge] = useState('');
 const [code, setCode] = useState('');
 const [password, setPassword] = useState('');
 const [message, setMessage] = useState('');
 const [error, setError] = useState('');
 const [busy, setBusy] = useState(false);
 const [done, setDone] = useState(false);
 const locked = useRef(false);
 async function submit(event: FormEvent) {
  event.preventDefault();
  if (locked.current) return;
  locked.current = true; setBusy(true); setError('');
  try {
   if (challenge) {
    await profileApi('/auth/reset-password', { method: 'POST', body: JSON.stringify({ challenge_id: challenge, code, password }) });
    setPassword(''); setCode(''); setChallenge(''); setDone(true);
    setMessage('Your password has been reset. Sign in with your new password.');
   } else {
    const receipt = await profileApi<{challenge_id: string; message: string}>('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) });
    setChallenge(receipt.challenge_id); setMessage(receipt.message);
   }
  } catch (e) { setError(e instanceof Error ? e.message : 'Could not reset your password. Please retry.'); }
  finally { locked.current = false; setBusy(false); }
 }
 return <AccessFrame><p className="k">Account recovery</p><h2>{done ? 'Password reset.' : 'Forgot your password?'}</h2>
 <p className="muted">{challenge ? 'Enter the six-digit code from your email and choose a new password. The code expires in 10 minutes.' : !done ? 'Enter your account’s email address to receive a password reset code.' : 'Your saved details are ready when you sign in.'}</p>
 {message && <p role="status">{message}</p>}
 {!done && <form className="access-form" onSubmit={submit}>
 {!challenge ? <><label htmlFor="reset-email">Email address</label><input id="reset-email" type="email" autoComplete="email" maxLength={254} value={email} onChange={e=>setEmail(e.target.value)} required disabled={busy}/></> : <>
 <label htmlFor="reset-code">Reset code</label><input id="reset-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/[^0-9]/g, ''))} required disabled={busy}/>
 <label htmlFor="reset-password">New password</label><input id="reset-password" type="password" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} required disabled={busy}/>
 <p className="small">Use 8–128 characters. A long, unique passphrase works well.</p></>}
 <button className="btn pri" disabled={busy}>{busy ? 'Please wait…' : challenge ? 'Reset password' : 'Send reset code'}</button>
 </form>}
 {error && <p className="error" role="alert">{error}</p>}
 {challenge && <button className="btn ghost" disabled={busy} onClick={()=>{setChallenge('');setCode('');setPassword('');setMessage('');setError('');}}>Request another code or change email</button>}
 <p className="small access-switch"><Link className="text-link" href="/login">Back to sign in</Link></p></AccessFrame>;
}

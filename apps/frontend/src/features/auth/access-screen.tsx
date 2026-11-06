"use client";
import Link from 'next/link';
import { BrandLogo } from '@/components/ui/brand-logo';
import { JourneyVisual } from '@/components/ui/journey-visual';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useProfile } from '@/features/profile/profile-provider';
import { ApiError, profileApi } from '@/lib/api/profile';
import { GoogleSignIn } from '@/lib/auth/google-sign-in';
export function AccessFrame({ children, entry = false }: { children: ReactNode; entry?: boolean }) {
 return <div className={`access-page${entry ? ' access-entry' : ''}`}>
  <a href="#access-content" className="skip-link">Skip to content</a>
  <header className="access-header"><Link href="/" className="brand" aria-label="Elo home"><BrandLogo/></Link><span className="access-header-note">Your career, moving forward.</span><Link href="/login" className="btn ghost">Sign in</Link></header>
  <main id="access-content" className="access-main" tabIndex={-1}>
   <section className="access-intro"><h1>A clearer path<br/>to your next<br/>career move.</h1><p>Bring your experience and ambitions together. Find a direction that feels like you.</p>{entry && <div className="entry-content">{children}</div>}</section>
   {entry ? <JourneyVisual/> : <section className="access-card card">{children}</section>}
  </main>
  {entry && <section className="access-foundations" aria-label="Your career workspace"><div><span className="foundation-dot"/><div><h2>Start with you</h2><p>Your background, in one place.</p></div></div><div><span className="foundation-dot"/><div><h2>Find your direction</h2><p>Explore roles and set your career goal.</p></div></div><div><span className="foundation-dot"/><div><h2>Tell your story</h2><p>Upload and work through your CV.</p></div></div></section>}
  <footer className="access-footer"><span>Your next chapter starts here.</span><span>Built around your ambition.</span></footer>
 </div>;
}
function AccessStatus() {
 const { logoutError, retryLogout, configError, reload } = useProfile();
 return <>{configError && <div role="alert"><p className="error">Account access unavailable: {configError}</p><button className="btn ghost" onClick={reload}>Retry connection</button></div>}{logoutError && <div role="alert"><p className="error">{logoutError}</p><button className="btn ghost" onClick={retryLogout}>Retry sign-out</button></div>}</>;
}
export function EntryPage() {
 const session = useProfile(); const router = useRouter(); const pathname=usePathname();
 useEffect(() => { if (pathname==='/' && session.account && session.profile && !session.loading) router.replace(session.profile.onboarding_complete ? '/dashboard' : '/onboarding'); }, [session.account, session.profile, session.loading, pathname, router]);
 return <AccessFrame entry><AccessStatus/>{session.loading ? <p role="status">Checking account access…</p> : session.account ? <><p role="status">{session.loadError || 'Opening your workspace…'}</p>{session.loadError && <button className="btn ghost" onClick={session.reload}>Retry profile</button>}<button className="btn ghost" onClick={session.signOut}>Sign out</button></> : <div className="access-actions"><Link href="/register" className="btn pri">Create account <span aria-hidden="true">↗</span></Link><Link href="/login" className="btn ghost">Sign in to your account</Link></div>}</AccessFrame>;
}
export function AccessScreen({ intent }: { intent: 'login' | 'register' }) {
 const { mode, googleEnabled, verification, account, profile, loading, configError, loadError, beginAccess, completeAccess, cancelAccess, reload, signOut } = useProfile();
 const router = useRouter(); const pathname=usePathname(); const accessPath=intent==='login'?'/login':'/register'; const [nonce, setNonce] = useState(''); const [name, setName] = useState(''); const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
 const [accounts, setAccounts] = useState<{ id: string; name: string; email: string }[]>([]); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [revision, setRevision] = useState(0); const locked = useRef(false);
 const [accountNotFound, setAccountNotFound] = useState(false);
 useEffect(() => {
  if (pathname!==accessPath || account || !mode || configError) return;
  let active = true; setNonce(''); setError(''); setAccountNotFound(false);
  beginAccess(intent).then(access => { if (active) setNonce(access.nonce); }).catch(e => { if (active) setError(e.message); });
  if (mode === 'local_test' && intent === 'login') profileApi<{ id: string; name: string; email: string }[]>('/auth/local-accounts').then(list => { if (active) setAccounts(list); }).catch(e => { if (active) setError(e.message); });
  return () => { active = false; cancelAccess(); };
 }, [mode, configError, intent, beginAccess, cancelAccess, revision, account, pathname, accessPath]);
 useEffect(() => { if (pathname===accessPath && account && profile && !loading) router.replace(profile.onboarding_complete ? '/dashboard' : '/onboarding'); }, [account, profile, loading, pathname, accessPath, router]);
 const finish = useCallback(async (credential?: string) => {
  if (locked.current) return; locked.current = true; setBusy(true); setError(''); setAccountNotFound(false);
  try { await completeAccess(credential ? { credential } : { ...(intent === 'register' ? { name } : {}), email, password }); setPassword(''); }
  catch (e) { setError(e instanceof Error ? e.message : 'Could not finish. Please retry.'); setAccountNotFound(intent === 'login' && e instanceof ApiError && e.status === 404); }
  finally { locked.current = false; setBusy(false); }
 }, [intent, name, email, password, completeAccess]);
 function submit(event: FormEvent) { event.preventDefault(); void finish(); }
 return <AccessFrame><p className="k">{verification ? 'Check your inbox' : intent === 'register' ? 'Your first step' : 'Welcome back'}</p><h2>{verification ? 'Verify your email.' : intent === 'register' ? 'Create your account.' : 'Good to see you again.'}</h2><p className="muted">{verification ? 'One small step to make this account yours.' : intent === 'register' ? 'A fresh start for your next career move.' : 'Your next chapter is right where you left it.'}</p><AccessStatus/>
 {account ? <><p role="status">{loadError || 'Opening your workspace…'}</p>{loadError && <button className="btn ghost" onClick={reload}>Retry profile</button>}<button className="btn ghost" onClick={signOut}>Sign out</button></> : verification ? <VerificationForm/> : loading || !mode ? <p role="status">Checking account access…</p> : !configError && <>
 {mode === 'local_test' && <p className="access-note">Development mode · use a test email and password. Verification messages appear in your local test inbox.</p>}
 {!nonce && !error && <p role="status">Preparing secure access…</p>}
 <form onSubmit={submit} className="access-form">
 {intent === 'register' && <><label htmlFor="account-name">Display name (optional)</label><input id="account-name" autoComplete="nickname" maxLength={80} value={name} onChange={e => setName(e.target.value)} disabled={busy}/></>}
 {mode === 'local_test' && intent === 'login' && accounts.length > 0 && <><label htmlFor="local-account">Choose your development account (optional)</label><select id="local-account" value="" disabled={busy} onChange={e => { const choice=accounts.find(a=>a.id===e.target.value); if(choice) setEmail(choice.email); }}><option value="">Prefill an email</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.name} · {a.email}</option>)}</select></>}
 <label htmlFor="account-email">Email address</label><input id="account-email" type="email" autoComplete="email" maxLength={254} value={email} onChange={e=>setEmail(e.target.value)} required disabled={busy}/>
 <label htmlFor="account-password">Password</label><input id="account-password" type="password" autoComplete={intent === 'register' ? 'new-password' : 'current-password'} minLength={8} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} required disabled={busy}/>
 {intent === 'register' && <p className="small">We’ll email a code to verify your address. Use 8–128 characters for your password. A long, unique passphrase works well.</p>}
 <button className="btn pri" disabled={busy || !nonce || !email || password.length < 8}>{busy ? 'Please wait…' : intent === 'register' ? 'Create account' : 'Sign in'}<span aria-hidden="true">↗</span></button></form>
 {googleEnabled && nonce && <div className="access-google"><p className="small">Or continue with Google</p><GoogleSignIn key={nonce} nonce={nonce} onCredential={credential => { void finish(credential); }}/></div>}
 {intent === 'login' && <Link className="text-link small" href="/forgot-password">Forgot password?</Link>}
 {busy && <p role="status">Finishing account access…</p>}{error && <div role="alert"><p className="error">{error}</p>{accountNotFound ? <Link className="btn pri" href="/register" onClick={cancelAccess}>Create new account</Link> : <button className="btn ghost sm" onClick={() => setRevision(n => n + 1)}>Start again</button>}</div>}
 <p className="small access-switch">{intent === 'register' ? 'Already have an account?' : 'New to elo?'} <Link className="text-link" href={intent === 'register' ? '/login' : '/register'}>{intent === 'register' ? 'Sign in' : 'Create account'}</Link></p><Link href="/" className="small text-link" onClick={cancelAccess}>Cancel and return home</Link></>}
 </AccessFrame>;
}
function VerificationForm() {
 const { verification, verifyEmail, resendVerification, cancelAccess }=useProfile();
 const [code,setCode]=useState(''); const [error,setError]=useState(''); const [message,setMessage]=useState(''); const [busy,setBusy]=useState(false); const [clock,setClock]=useState(Date.now()); const locked=useRef(false);
 useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[]);
 if(!verification)return null;
 const seconds=Math.max(0,Math.ceil((Date.parse(verification.resend_at)-clock)/1000));
 const expired=Date.parse(verification.expires_at)<=clock;
 async function verify(event:FormEvent) {event.preventDefault();if(locked.current)return;locked.current=true;setBusy(true);setError('');try{await verifyEmail(code);}catch(e){setError((e as Error).message);}finally{locked.current=false;setBusy(false);}}
 async function resend(){if(locked.current)return;locked.current=true;setBusy(true);setError('');try{await resendVerification();setCode('');setMessage('A new code was sent. Use the latest email.');}catch(e){setError((e as Error).message);}finally{locked.current=false;setBusy(false);}}
 return <><p>We sent a six-digit code to <strong>{verification.masked_email}</strong>.</p><form className="access-form" onSubmit={verify}>
 <label htmlFor="verification-code">Verification code</label><input id="verification-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/[^0-9]/g,''))} required disabled={busy}/>
 <p className="small">{expired ? 'This code has expired. Request another code.' : 'Your code is valid for 10 minutes.'}</p>
 <button className="btn pri" disabled={busy||code.length!==6||expired}>{busy?'Please wait…':'Verify email'}</button></form>
 <button type="button" className="btn ghost" disabled={busy||seconds>0} onClick={()=>void resend()}>{seconds>0?`Resend code in ${seconds}s`:'Resend code'}</button>
 {error&&<p role="alert" className="error">{error}</p>}{message&&<p role="status" className="success">{message}</p>}
 <p className="small access-switch"><Link href="/login" className="text-link" onClick={cancelAccess}>Cancel and sign in again</Link></p></>;
}

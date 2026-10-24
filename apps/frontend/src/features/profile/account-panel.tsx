"use client";
import { GoogleSignIn } from '@/lib/auth/google-sign-in';
import { useProfile } from './profile-provider';
export function AccountPanel({ busy = false }: { busy?: boolean }) {
 const { mode, token, loading, configError, loadError, onCredential, signOut, reload } = useProfile();
 return <section className="card account-panel" aria-label="Account">
  <div className="account-status">
   <span className={`status-light ${mode ? 'connected' : ''}`} aria-hidden="true"/>
   <div>{mode === 'local_test' ? <><strong>Local test profile</strong><p className="small">Your changes are saved to the local database.</p></> : !mode ? <p>Connecting to your profile…</p> : token ? <><strong>Google account connected</strong><p className="small">Your profile stays with your account.</p></> : <><strong>Welcome to Coachify</strong><p className="small">Sign in to save and return to your profile.</p></>}</div>
  </div>
  {mode === 'google' && (token ? <button className="btn ghost sm" type="button" disabled={busy || loading} onClick={signOut}>Sign out</button> : <GoogleSignIn onCredential={onCredential}/>)}
  {(configError || loadError) && <div className="account-error"><p role="alert" className="error">{configError || loadError}</p><button type="button" className="btn ghost sm" onClick={reload}>Retry loading</button></div>}
 </section>;
}

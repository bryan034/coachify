"use client";
import { useProfile } from './profile-provider';
export function AccountPanel({ busy = false }: { busy?: boolean }) {
 const { account, mode, loading, configError, loadError, signOut, reload } = useProfile();
 return <section className="card account-panel" aria-label="Account">
  <div className="account-status"><span className="status-light connected" aria-hidden="true"/>
   <div><strong>{account?.name || 'Your account'}</strong><p className="small">{mode === 'local_test' ? 'Development account · saved in your local database' : 'Your profile stays with your account.'}</p></div>
  </div>
  <button className="btn ghost sm" type="button" disabled={busy || loading} onClick={signOut}>Sign out</button>
  {(configError || loadError) && <div className="account-error"><p role="alert" className="error">{configError || loadError}</p><button type="button" className="btn ghost sm" onClick={reload}>Retry loading</button></div>}
 </section>;
}

"use client";
import { useProfile } from './profile-provider';
export function AccountPanel() {
 const { mode, configError, loadError, reload } = useProfile();
 const error = configError || loadError;
 if (!error && mode !== 'local_test') return null;
 return <section className="card account-panel" aria-label="Account">
  {mode === 'local_test' && <p className="small">Development account, saved in your local database.</p>}
  {error && <div className="account-error"><p role="alert" className="error">{error}</p><button type="button" className="btn ghost sm" onClick={reload}>Retry loading</button></div>}
 </section>;
}

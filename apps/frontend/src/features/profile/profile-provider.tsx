"use client";
import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
import { ApiError, profileApi } from '@/lib/api/profile';
import type { Category, Profile } from './types';
export type Account = { id: string; name: string; email?: string; email_verified?: boolean; provider: 'google' | 'local_test' | 'email'; expires_at?: string };
type Access = { flow_id: string; attempt_id: string; session_token: string; nonce: string; epoch: string };
type Mode = 'google' | 'email' | 'local_test';
export type Verification = { verification_required: true; challenge_id: string; masked_email: string; expires_at: string; resend_at: string };
type Credentials = { name?: string; email?: string; password?: string; credential?: string };
type Session = {
 mode: Mode | null; googleEnabled: boolean; developmentToolsEnabled: boolean; verification: Verification | null; token?: string; account: Account | null; profile: Profile | null; categories: Category[];
 loading: boolean; configError: string; loadError: string; logoutError: string;
 beginAccess: (intent: 'login' | 'register') => Promise<Access>;
 completeAccess: (input: Credentials) => Promise<boolean>;
 verifyEmail: (code: string) => Promise<boolean>; resendVerification: () => Promise<void>;
 cancelAccess: () => void;
 signOut: () => void; retryLogout: () => void; reload: () => void; setProfile: (profile: Profile) => boolean;
};
const Context = createContext<Session | null>(null);
const SESSION = 'coachify.session';
const EPOCH = 'coachify.access-epoch';
const PENDING = 'coachify.pending-logout';
function secret() { return crypto.randomUUID().replaceAll('-', '') + crypto.randomUUID().replaceAll('-', ''); }
function nextEpoch() {
 const previous = Number(localStorage.getItem(EPOCH) || 0);
 const value = String(Math.max(Date.now() * 1000, (Number.isSafeInteger(previous) && previous >= 0 ? previous : 0) + 1));
 localStorage.setItem(EPOCH, value); return value;
}
export function ProfileProvider({ children }: { children: ReactNode }) {
 const [mode, setMode] = useState<Mode | null>(null);
 const [googleEnabled, setGoogleEnabled] = useState(false);
 const [developmentToolsEnabled, setDevelopmentToolsEnabled] = useState(false);
 const [verification, setVerification] = useState<Verification | null>(null);
 const latestProfile = useRef<Profile | null>(null);
 const currentAccount = useRef<Account | null>(null);
 const [token, setToken] = useState<string>();
 const activeToken = useRef<string | undefined>(undefined);
 const attempt = useRef<Access | null>(null);
 const operation = useRef(0);
 const [account, setAccount] = useState<Account | null>(null);
 const [profile, setProfile] = useState<Profile | null>(null);
 const [categories, setCategories] = useState<Category[]>([]);
 const [loading, setLoading] = useState(true);
 const [configError, setConfigError] = useState('');
 const [loadError, setLoadError] = useState('');
 const [logoutError, setLogoutError] = useState('');
 const [retry, setRetry] = useState(0);
 const reload = useCallback(() => setRetry(n => n + 1), []);
 const clear = useCallback(() => {
  operation.current++; latestProfile.current = null; currentAccount.current = null; activeToken.current = undefined; setToken(undefined); setAccount(null); setProfile(null); setLoadError('');
  sessionStorage.removeItem(SESSION);
 }, []);
 const cancelAccess = useCallback(() => {
  const old = attempt.current; attempt.current = null; setVerification(null);
  if (old) void profileApi('/auth/attempts/cancel', { method: 'POST', body: JSON.stringify({ flow_id: old.flow_id, attempt_id: old.attempt_id }) }).catch(() => {});
 }, []);
 const retryLogout = useCallback(async () => {
  const pending = sessionStorage.getItem(PENDING);
  if (!pending) return;
  try {
   await profileApi('/auth/logout', { method: 'POST' }, pending);
   if (sessionStorage.getItem(PENDING) === pending) { sessionStorage.removeItem(PENDING); setLogoutError(''); }
  } catch {
   if (sessionStorage.getItem(PENDING) === pending) setLogoutError('Server sign-out could not be confirmed. This browser remains locked. Retry sign-out or explicitly sign in again.');
  }
 }, []);
 const signOut = useCallback(() => {
  const old = activeToken.current;
  cancelAccess(); clear(); nextEpoch();
  window.google?.accounts.id.disableAutoSelect();
  if (old) { sessionStorage.setItem(PENDING, old); void retryLogout(); }
 }, [cancelAccess, clear, retryLogout]);
 useEffect(() => {
  function changed(event: StorageEvent) {
   if (event.key === EPOCH) { cancelAccess(); clear(); setLoading(false); }
   if (event.key === 'coachify.setup-completed' && event.newValue && currentAccount.current && !latestProfile.current?.onboarding_complete) {
    try { const hint = JSON.parse(event.newValue); if (hint.account_id === currentAccount.current.id) reload(); } catch { /* Ignore malformed non-secret hints. */ }
   }
  }
  function expired(event: Event) {
   if ((event as CustomEvent).detail === activeToken.current) signOut();
  }
  // BFCache restoration and background tabs must revalidate before showing private content.
  function hidden() { if (!activeToken.current) return; if (document.visibilityState === 'hidden') { setProfile(null); setLoading(true); } else reload(); }
  function restored(event: PageTransitionEvent) { if (event.persisted && activeToken.current) { setProfile(null); setLoading(true); reload(); } }
  window.addEventListener('storage', changed); window.addEventListener('coachify:expired', expired);
  document.addEventListener('visibilitychange', hidden); window.addEventListener('pageshow', restored);
  return () => { window.removeEventListener('storage', changed); window.removeEventListener('coachify:expired', expired); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pageshow', restored); };
 }, [cancelAccess, clear, reload, signOut]);
 useEffect(() => {
  const controller = new AbortController(); const id = ++operation.current;
  setDevelopmentToolsEnabled(false); setLoading(true); setConfigError(''); setLoadError(''); setProfile(null);
  async function load() {
   try {
    const [options, auth] = await Promise.all([
     profileApi<Category[]>('/school-categories', { signal: controller.signal }),
     profileApi<{ mode: Mode; google_enabled?: boolean; development_tools_enabled?: boolean }>('/auth-config', { signal: controller.signal }),
    ]);
    if (controller.signal.aborted || id !== operation.current) return;
    if (!['google', 'email', 'local_test'].includes(auth.mode)) throw new Error('Invalid account configuration.');
    setCategories(options); setMode(auth.mode); setGoogleEnabled(auth.google_enabled === true); setDevelopmentToolsEnabled(auth.development_tools_enabled === true);
    if (sessionStorage.getItem(PENDING)) { setLogoutError('Sign-out is pending. Retry sign-out or explicitly sign in again.'); return; }
    let stored: { token: string; epoch: string } | null;
    try { stored = JSON.parse(sessionStorage.getItem(SESSION) || 'null'); }
    catch { clear(); return; }
    if (!stored || stored.epoch !== localStorage.getItem(EPOCH)) { clear(); return; }
    let who: Account;
    try { who = await profileApi<Account>('/auth/session', { signal: controller.signal }, stored.token); }
    catch (error) {
     if (controller.signal.aborted || id !== operation.current) return;
     if (error instanceof ApiError && error.status === 401) { clear(); nextEpoch(); return; } throw error;
    }
    if (controller.signal.aborted || id !== operation.current) return;
    activeToken.current = stored.token; setToken(stored.token); currentAccount.current = who; setAccount(who);
    try {
     const saved = await profileApi<Profile>('', { signal: controller.signal }, stored.token);
     if (!controller.signal.aborted && id === operation.current && (!latestProfile.current || saved.version >= latestProfile.current.version)
         && !(latestProfile.current?.onboarding_complete && !saved.onboarding_complete)) { latestProfile.current = saved; setProfile(saved); }
     else if (!controller.signal.aborted && id === operation.current && latestProfile.current) setProfile(latestProfile.current);
    } catch (error) { if (!controller.signal.aborted && id === operation.current) setLoadError(error instanceof Error ? error.message : 'Profile unavailable. Retry loading.'); }
   } catch (error) { if (!controller.signal.aborted && id === operation.current) setConfigError(error instanceof Error ? error.message : 'Account access unavailable. Please retry.'); }
   finally { if (!controller.signal.aborted) setLoading(false); }
  }
  void load(); return () => controller.abort();
 }, [retry, clear]);
 const beginAccess = useCallback(async (intent: 'login' | 'register') => {
  cancelAccess(); clear();
  const epoch = nextEpoch();
  let flow = localStorage.getItem('coachify.flow');
  if (!flow) { flow = secret(); localStorage.setItem('coachify.flow', flow); }
  const access: Access = { flow_id: flow, attempt_id: secret(), session_token: secret(), nonce: '', epoch };
  attempt.current = access;
  const result = await profileApi<{ nonce: string }>('/auth/attempts', { method: 'POST', body: JSON.stringify({ flow_id: flow, attempt_id: access.attempt_id, generation: Number(epoch), intent }) });
  if (attempt.current !== access || localStorage.getItem(EPOCH) !== epoch) {
   void profileApi('/auth/attempts/cancel', { method: 'POST', body: JSON.stringify({ flow_id: flow, attempt_id: access.attempt_id }) }).catch(() => {});
   throw new Error('Access attempt cancelled. Please start again.');
  }
  access.nonce = result.nonce; return access;
 }, [cancelAccess, clear]);
 const installAccount = useCallback((who: Account, access: Access) => {
  if (attempt.current !== access || localStorage.getItem(EPOCH) !== access.epoch) return false;
  attempt.current = null; setVerification(null); sessionStorage.removeItem(PENDING); setLogoutError('');
  sessionStorage.setItem(SESSION, JSON.stringify({ token: access.session_token, epoch: access.epoch }));
  activeToken.current = access.session_token; currentAccount.current = who; setToken(access.session_token); setAccount(who); setProfile(null); reload();
  return true;
 }, [reload]);
 const completeAccess = useCallback(async (input: Credentials) => {
  const access = attempt.current;
  if (!access) throw new Error('Start a new access attempt.');
  const result = await profileApi<Account | Verification>('/auth/complete', { method: 'POST', body: JSON.stringify({ flow_id: access.flow_id, attempt_id: access.attempt_id, session_token: access.session_token, ...input }) });
  if (attempt.current !== access || localStorage.getItem(EPOCH) !== access.epoch) return false;
  if ('verification_required' in result) { setVerification(result); return false; }
  return installAccount(result, access);
 }, [installAccount]);
 const verifyEmail = useCallback(async (code: string) => {
  const access = attempt.current;
  if (!access || !verification) throw new Error('Start a new verification attempt.');
  const who = await profileApi<Account>('/auth/verify-email', { method: 'POST', body: JSON.stringify({ flow_id: access.flow_id, attempt_id: access.attempt_id, session_token: access.session_token, challenge_id: verification.challenge_id, code }) });
  return installAccount(who, access);
 }, [verification, installAccount]);
 const resendVerification = useCallback(async () => {
  const access = attempt.current;
  if (!access) throw new Error('Start a new verification attempt.');
  const result = await profileApi<Verification>('/auth/resend-verification', { method: 'POST', body: JSON.stringify({ flow_id: access.flow_id, attempt_id: access.attempt_id, session_token: access.session_token }) });
  if (attempt.current === access && localStorage.getItem(EPOCH) === access.epoch) setVerification(result);
 }, []);
 const acceptProfile = useCallback((value: Profile) => {
  if (!token || activeToken.current !== token || (latestProfile.current && value.version < latestProfile.current.version)
      || (latestProfile.current?.onboarding_complete && !value.onboarding_complete)) return false;
  const completed = !latestProfile.current?.onboarding_complete && value.onboarding_complete;
  latestProfile.current = value; setProfile(value);
  if (completed && currentAccount.current) localStorage.setItem('coachify.setup-completed', JSON.stringify({ account_id: currentAccount.current.id, version: value.version, at: Date.now() }));
  return true;
 }, [token]);
 useEffect(() => {
  if (!token || !account) return;
  const controller = new AbortController();
  async function validate() {
   try { await profileApi<Account>('/auth/session', { signal: controller.signal }, token); }
   catch (error) {
    if (controller.signal.aborted || activeToken.current !== token) return;
    if (error instanceof ApiError && error.status === 401) signOut();
    else { setProfile(null); setConfigError('Session validation unavailable. Retry connection before continuing.'); }
   }
  }
  const poll = window.setInterval(() => { void validate(); }, 30_000);
  const expiry = account.expires_at ? Date.parse(account.expires_at) - Date.now() : null;
  const timer = expiry === null ? undefined : window.setTimeout(() => { if (activeToken.current === token) signOut(); }, Math.max(0, expiry));
  return () => { controller.abort(); clearInterval(poll); if (timer !== undefined) clearTimeout(timer); };
 }, [token, account, signOut]);
 return <Context.Provider value={{ mode, googleEnabled, developmentToolsEnabled, verification, token, account, profile, categories, loading, configError, loadError, logoutError, beginAccess, completeAccess, verifyEmail, resendVerification, cancelAccess, signOut, retryLogout, reload, setProfile: acceptProfile }}>{children}</Context.Provider>;
}
export function useProfile() {
 const session = useContext(Context); if (!session) throw new Error('ProfileProvider is required.'); return session;
}

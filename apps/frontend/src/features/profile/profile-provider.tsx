"use client";
import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { profileApi } from '@/lib/api/profile';
import type { Category, Profile } from './types';
type Mode = 'google' | 'local_test';
type ProfileSession = {
 mode: Mode | null; token?: string; profile: Profile | null; categories: Category[];
 loading: boolean; configError: string; loadError: string;
 onCredential: (credential: string) => void; signOut: () => void;
 reload: () => void; setProfile: (profile: Profile) => void;
};
const Context = createContext<ProfileSession | null>(null);
export function ProfileProvider({ children }: { children: ReactNode }) {
 const [mode, setMode] = useState<Mode | null>(null);
 const [token, setToken] = useState<string>();
 const [profile, setProfile] = useState<Profile | null>(null);
 const [categories, setCategories] = useState<Category[]>([]);
 const [loading, setLoading] = useState(false);
 const [configError, setConfigError] = useState('');
 const [loadError, setLoadError] = useState('');
 const [retry, setRetry] = useState(0);
 const onCredential = useCallback((credential: string) => { setProfile(null); setToken(credential); }, []);
 const reload = useCallback(() => setRetry(n => n + 1), []);
 useEffect(() => {
  const controller = new AbortController();
  setConfigError('');
  Promise.all([
   profileApi<Category[]>('/school-categories', { signal: controller.signal }),
   profileApi<{ mode: Mode }>('/auth-config', { signal: controller.signal }),
  ]).then(([options, auth]) => {
   if (auth.mode !== 'google' && auth.mode !== 'local_test') throw new Error('Invalid authentication configuration.');
   setCategories(options); setMode(auth.mode);
  }).catch(e => { if (e.name !== 'AbortError') setConfigError('We could not connect to your profile. Please retry.'); });
  return () => controller.abort();
 }, [retry]);
 useEffect(() => {
  if (mode !== 'local_test' && !(mode === 'google' && token)) return;
  const controller = new AbortController();
  setLoading(true); setLoadError(''); setProfile(null);
  profileApi<Profile>('', { signal: controller.signal }, token).then(setProfile)
   .catch(e => { if (e.name !== 'AbortError') setLoadError(e.message || 'Profile could not load. Please retry.'); })
   .finally(() => { if (!controller.signal.aborted) setLoading(false); });
  return () => controller.abort();
 }, [mode, token, retry]);
 function signOut() {
  window.google?.accounts.id.disableAutoSelect();
  setToken(undefined); setProfile(null); setLoadError('');
 }
 return <Context.Provider value={{ mode, token, profile, categories, loading, configError, loadError, onCredential, signOut, reload, setProfile }}>{children}</Context.Provider>;
}
export function useProfile() {
 const session = useContext(Context);
 if (!session) throw new Error('ProfileProvider is required.');
 return session;
}

"use client";
import { useEffect, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useProfile } from '@/features/profile/profile-provider';
export function WorkspaceGuard({ children }: { children: ReactNode }) {
 const { account, token, profile, loading, configError, loadError, reload, signOut } = useProfile();
 const router = useRouter(); const pathname=usePathname();
 const setup=pathname==='/onboarding';
 useEffect(() => {
  if(loading||configError||loadError)return;
  if(!account||!token){router.replace('/');return;}
  if(!profile)return;
  if(!profile.onboarding_complete&&!setup)router.replace('/onboarding');
  if(profile.onboarding_complete&&setup)router.replace('/dashboard');
 }, [loading,account,token,profile,setup,configError,loadError,router]);
 const unavailable=configError||loadError;
 if(loading||!account||!token||!profile||unavailable||(!profile.onboarding_complete&&!setup)||(profile.onboarding_complete&&setup))
  return <main><p role={unavailable?'alert':'status'}>{unavailable||'Checking your session and setup…'}</p>{unavailable&&<><button className="btn ghost" onClick={reload}>{loadError?'Retry profile':'Retry connection'}</button><button className="btn ghost" onClick={signOut}>Sign out</button></>}</main>;
 return children;
}

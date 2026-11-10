"use client";
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useProfile } from '@/features/profile/profile-provider';
import { Skeleton, SkeletonLine } from '@/components/ui/workspace-ui';
/** `inShell` keeps the sidebar on screen while the session is checked, so pages don't flash blank. */
export function WorkspaceGuard({ children, inShell = false }: { children: ReactNode; inShell?: boolean }) {
 const { account, token, profile, loading, configError, loadError, sessionError, sessionChecking, retrySession, reload, signOut, developmentToolsEnabled } = useProfile();
 const router = useRouter(); const pathname=usePathname();
 const setup=pathname==='/onboarding';
 const preview=pathname==='/onboarding/preview';
 const allowedPreview=preview&&developmentToolsEnabled&&!!profile?.onboarding_complete;
 const locked=!!(sessionChecking||sessionError);
 const recovery=useRef<HTMLDivElement>(null);
 const previousFocus=useRef<HTMLElement|null>(null);
 useLayoutEffect(()=>{
  if(locked){
   previousFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
   recovery.current?.focus();
  }else{
   if(previousFocus.current?.isConnected)previousFocus.current.focus();
   previousFocus.current=null;
  }
 },[locked]);
 useEffect(() => {
  if(loading||configError||loadError||locked)return;
  if(!account||!token){router.replace('/');return;}
  if(!profile)return;
  if(preview&&!allowedPreview){router.replace(profile.onboarding_complete?'/profile':'/onboarding');return;}
  if(allowedPreview)return;
  if(!profile.onboarding_complete&&!setup)router.replace('/onboarding');
  if(profile.onboarding_complete&&setup)router.replace('/getting-started');
 }, [loading,account,token,profile,setup,preview,allowedPreview,configError,loadError,locked,router]);
 const unavailable=configError||loadError;
 if(loading||!account||!token||!profile||unavailable||(preview&&!allowedPreview)||(!profile.onboarding_complete&&!setup)||(profile.onboarding_complete&&setup))
  {
  const body=unavailable?<><p role="alert">{unavailable}</p><button className="btn ghost" onClick={reload}>{loadError?'Retry profile':'Retry connection'}</button><button className="btn ghost" onClick={signOut}>Sign out</button></>
   :<Skeleton label="Checking your session and setup…" className="workspace-loading"><SkeletonLine width="38%" height={30}/><SkeletonLine width="62%"/><div className="skeleton-grid"><div className="skeleton-card"><SkeletonLine width="50%"/><SkeletonLine/><SkeletonLine width="80%"/></div><div className="skeleton-card"><SkeletonLine width="40%"/><SkeletonLine/><SkeletonLine width="70%"/></div></div></Skeleton>;
  return inShell?<div className="workspace-guard-pending">{body}</div>:<main>{body}</main>;
 }
 return <>
  <div hidden={locked} inert={locked} aria-hidden={locked||undefined} style={locked?undefined:{display:'contents'}}>{children}</div>
  {locked&&<div ref={recovery} role="dialog" aria-modal="true" aria-labelledby="session-recovery-title" aria-describedby="session-recovery-description" tabIndex={-1} className="card" style={{maxWidth:560,margin:'48px auto',padding:24}} onKeyDown={event=>{
   if(event.key!=='Tab')return;
   const buttons=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
   const first=buttons[0];const last=buttons[buttons.length-1];
   if(event.shiftKey&&(document.activeElement===first||document.activeElement===event.currentTarget)){event.preventDefault();last?.focus();}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }}>
   <h1 id="session-recovery-title">{sessionChecking?'Checking your session':'Connection interrupted'}</h1>
   <p id="session-recovery-description" role="status">{sessionChecking?'Please wait while we check your access. Your unsaved work is still in this tab.':sessionError}</p>
   <button className="btn pri" disabled={sessionChecking} onClick={()=>void retrySession()}>Retry session</button>{' '}
   <button className="btn ghost" onClick={signOut}>Sign out</button>
  </div>}
 </>;
}

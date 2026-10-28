"use client";
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
export const IDLE_LIMIT=5*60*1000;
export function WorkspaceActivity({children}:{children:ReactNode}){
 const {token,sessionError,signOut}=useProfile();const [expired,setExpired]=useState(false);
 const refresh=useRef<HTMLButtonElement|null>(null);
 useEffect(()=>{
  let last=Date.now(),locked=false;
  setExpired(false);
  function check(){if(!locked&&Date.now()-last>=IDLE_LIMIT){locked=true;setExpired(true);}return locked;}
  function activity(){if(document.visibilityState==='visible'&&!check())last=Date.now();}
  function visibility(){check();}
  const events=['pointerdown','keydown','input','scroll'];
  events.forEach(event=>window.addEventListener(event,activity,{passive:true,capture:true}));
  document.addEventListener('visibilitychange',visibility);
  const timer=window.setInterval(check,1000);
  return()=>{clearInterval(timer);events.forEach(event=>window.removeEventListener(event,activity,true));document.removeEventListener('visibilitychange',visibility);};
 },[token]);
 const blocked=expired||!!sessionError;
 useEffect(()=>{if(blocked)refresh.current?.focus();},[blocked]);
 return <><div inert={blocked}>{children}</div>{blocked&&<div className="workspace-lock" role="alertdialog" aria-modal="true" aria-labelledby="workspace-lock-title"><div className="card pad"><h1 id="workspace-lock-title">{expired?'Refresh required':'Connection check required'}</h1><p>{expired?'You have been inactive for five minutes. Refresh before continuing.':sessionError}</p><p className="small">Your unsaved work remains in this tab until refresh. Refreshing discards temporary inputs. Saved account data is kept.</p><button ref={refresh} className="btn pri" onClick={()=>window.location.reload()}>Refresh application</button><button className="btn ghost" onClick={signOut}>Sign out</button></div></div>}</>;
}

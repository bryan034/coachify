"use client";
import {useEffect,useState} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {JobsError,saveApplication,updateApplication,type Posting} from '@/lib/api/jobs';

export const APPLICATION_RECORDED='elo:job-application-recorded';
const VISITED='elo:job-apply-visit';
const MAX_VISITS=20;

type Visit={id:string;title:string;company:string};
const storageKey=(accountId:string)=>`elo.job-apply-visits.${accountId}`;
const isVisit=(value:Visit)=>typeof value?.id==='string'&&typeof value?.title==='string'&&typeof value?.company==='string';

function readVisits(accountId:string):Visit[]{
 try{
  const value=JSON.parse(localStorage.getItem(storageKey(accountId))||'[]');
  return Array.isArray(value)?value.filter(isVisit):[];
 }catch{return [];}
}
function writeVisits(accountId:string,visits:Visit[]){
 try{
  if(visits.length)localStorage.setItem(storageKey(accountId),JSON.stringify(visits));
  else localStorage.removeItem(storageKey(accountId));
 }catch{/* Without storage the question still appears while this page stays open. */}
}
const adding=(visits:Visit[],visit:Visit)=>[...visits.filter(other=>other.id!==visit.id),visit].slice(-MAX_VISITS);

/** Remembers that the user left for an employer's form. Opening the form says nothing about whether they applied. */
export function noteApplyVisit(accountId:string,{id,title,company}:Posting){
 const visit={id,title,company};
 writeVisits(accountId,adding(readVisits(accountId),visit));
 window.dispatchEvent(new CustomEvent(VISITED,{detail:visit}));
}

export function JobApplicationCheck(){
 const {account,token}=useProfile();
 if(!account||!token)return null;
 return <Check key={`${account.id}:${token}`} accountId={account.id} token={token}/>;
}

function Check({accountId,token}:{accountId:string;token:string}){
 const [visits,setVisits]=useState<Visit[]>([]);const [away,setAway]=useState(false);
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');

 useEffect(()=>{
  setVisits(readVisits(accountId));
  const visited=(event:Event)=>{setVisits(current=>adding(current,(event as CustomEvent<Visit>).detail));setAway(true);};
  const returned=()=>{if(document.visibilityState==='visible')setAway(false);};
  const otherTab=(event:StorageEvent)=>{if(event.key===storageKey(accountId))setVisits(readVisits(accountId));};
  window.addEventListener(VISITED,visited);window.addEventListener('focus',returned);window.addEventListener('storage',otherTab);
  document.addEventListener('visibilitychange',returned);
  return ()=>{
   window.removeEventListener(VISITED,visited);window.removeEventListener('focus',returned);window.removeEventListener('storage',otherTab);
   document.removeEventListener('visibilitychange',returned);
  };
 },[accountId]);

 const visit=visits[0];
 if(away||!visit)return null;

 function finish(){
  writeVisits(accountId,readVisits(accountId).filter(other=>other.id!==visit.id));
  setVisits(current=>current.filter(other=>other.id!==visit.id));setError('');
 }
 async function confirm(){
  setBusy(true);setError('');
  try{
   const publish=(detail:unknown)=>window.dispatchEvent(new CustomEvent(APPLICATION_RECORDED,{detail}));
   const item=await saveApplication(token,visit.id);publish(item);
   if(item.status==='saved')publish(await updateApplication(token,item,'applied'));
   finish();
  }catch(problem){setError(problem instanceof JobsError?problem.message:'The job service is temporarily unavailable. Retry shortly.');}
  finally{setBusy(false);}
 }

 return <section className="job-application-check" aria-label="Application check" aria-live="polite">
  <p>Did you apply to <strong>{visit.title}</strong> at {visit.company}?</p>
  {error&&<p className="small" role="alert">{error}</p>}
  <div className="job-application-check-actions">
   <button type="button" className="btn pri" disabled={busy} onClick={()=>void confirm()}>Yes, I applied</button>
   <button type="button" className="btn ghost" disabled={busy} onClick={finish}>No</button>
  </div>
 </section>;
}

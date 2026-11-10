"use client";
import Link from 'next/link';
import { useProfile } from '@/features/profile/profile-provider';
import { loadGoal, loadRoadmap, useSection } from '@/lib/api/workspace-summary';
import { careerApi } from '@/lib/api/career';
import { cvApi } from '@/lib/api/cv';
import '@/styles/chats.css';
const loadDiscoveries=(token:string,signal:AbortSignal)=>careerApi<{items:{id:string;title:string;last_message:string}[]}>('/discoveries',token,{signal});
const loadCvChats=async(token:string,signal:AbortSignal)=>{
 const list=await cvApi.conversations(null,token,signal);
 return Promise.all(list.conversations.slice(0,20).map(async item=>{
  const chat=await cvApi.conversation(item.id,token,signal);
  return {...item,last_message:chat.messages.at(-1)?.text??''};
 }));
};
export function ChatsPreview(){
 const {token}=useProfile();
 const goal=useSection(loadGoal,token),roadmap=useSection(loadRoadmap,token),discoveries=useSection(loadDiscoveries,token),reviews=useSection(loadCvChats,token);
 const available=[
  ...(goal.state.status==='ready'&&goal.state.data.goal?[{key:'goal',kind:'Career Goal chat',title:goal.state.data.goal.role,body:'',href:'/career-goal/chat'}]:[]),
  ...(discoveries.state.status==='ready'?(discoveries.state.data.items??[]).map(item=>({key:item.id,kind:'Career discovery',title:item.title,body:item.last_message,href:`/career-goal/discovery?session=${item.id}`})):[]),
  ...(reviews.state.status==='ready'?reviews.state.data.map(item=>({key:item.id,kind:item.cv_id?'CV review':'Skills Profile chat',title:item.cv_id?'CV review':'Skills Profile conversation',body:item.last_message,href:item.cv_id?`/cv?review=${item.cv_id}&conversation=${item.id}`:'/cv?chat=manual'})):[]),
  ...(roadmap.state.status==='ready'&&roadmap.state.data.messages.length?[{key:'roadmap',kind:'Roadmap',title:'Plan helper',body:roadmap.state.data.messages.at(-1)!.content,href:'/roadmap?chat=1'}]:[]),
 ];
 return <section className="page on chats-page"><h1>Conversations</h1><p>Every chat you’ve had with elo. Pick up where you left off.</p>
 {[goal,roadmap,discoveries,reviews].map((source,index)=>source.state.status==='error'?<div key={index} role="alert"><p>{source.state.message}</p><button className="btn ghost" onClick={source.retry}>Retry conversations</button></div>:source.state.status==='loading'?<p key={index} role="status">Loading conversations…</p>:null)}
 {available.length>0&&<section className="card conversation-list" aria-label="Your conversations">{available.map(item=><div className="conversation-row" key={item.key}><div><p><strong>{item.title}</strong> <span className="small">{item.kind}</span></p><p className="small">{item.body||'No messages yet.'}</p></div><Link className="btn ghost sm" href={item.href}>Resume</Link></div>)}</section>}
 {!available.length&&[goal,roadmap,discoveries,reviews].every(source=>source.state.status==='ready')&&<p>No saved conversations yet. Start with your career direction or Skills Profile.</p>}
 <div className="row"><Link className="btn pri" href="/career-goal/discovery">Explore careers</Link><Link className="btn ghost" href="/cv?chat=manual">Talk through my skills</Link></div>
 <section className="card pad socials-teaser" aria-labelledby="socials-title"><h2 id="socials-title">Socials are on the way</h2><p>Soon you’ll be able to talk to peers and mentors here. Nothing to set up yet.</p></section></section>;
}

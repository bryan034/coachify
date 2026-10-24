"use client";
import { useState } from 'react';
import { EmptyState, EmptyTable, PageTitle, FeatureNotice, PendingAction, SectionTitle } from '@/components/ui/workspace-ui';
export function ChatsPreview() {
 const [filter,setFilter]=useState('For you');
 return <section className="page on"><PageTitle title="Chats & Socials"><span className="chip">Find your people</span></PageTitle><FeatureNotice>Expert discovery, chat requests and social connections are not available yet.</FeatureNotice>
 <div className="chips filter-row" aria-label="Expert filters">{['For you','Product','Finance','Tech'].map(f=><button key={f} type="button" className={`chip ${f===filter?'on':''}`} aria-pressed={f===filter} onClick={()=>setFilter(f)}>{f}</button>)}</div>
 <div className="grid c3">{[['chat','Career conversations','Learn from people who have walked the path.'],['brief','Industry perspectives','Explore what a role looks like from the inside.'],['user','Connections that count','Find people who understand your next step.']].map(([icon,title,body])=><div className="card pad" key={title}><EmptyState compact icon={icon} title={title}>{body}</EmptyState><PendingAction>Request · 20 min</PendingAction></div>)}</div>
 <p className="small filter-caption">{filter==='For you'?'Expert suggestions':`${filter} experts`} will appear here once discovery is available.</p>
 <div className="grid network-grid"><div><SectionTitle title="Upcoming"/><div className="card"><EmptyState icon="cal" title="Space for your next chat" compact>Confirmed conversations will appear here.</EmptyState></div></div><div><SectionTitle title="Your conversation network"/><EmptyTable columns={['Person','Field','Relationship','Recommendation']} message="Your connections will appear when networking is available."/></div></div>
 <SectionTitle title="Socials on Coachify"><span className="small">People on a similar path</span></SectionTitle><div className="card"><EmptyState icon="user" title="Grow together">Peer and professional connections will appear here when socials are ready.</EmptyState></div>
 </section>;
}

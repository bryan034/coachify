"use client";
import { useState } from 'react';
import { EmptyState, PageTitle, FeatureNotice, PendingAction, SectionTitle } from '@/components/ui/workspace-ui';
export function RoadmapPreview() {
 const [filter, setFilter] = useState('All');
 return <section className="page on"><PageTitle title="Roadmap"><span className="chip">Your path to job-ready</span></PageTitle>
 <FeatureNotice>Roadmap planning and progress tracking are not available yet.</FeatureNotice>
 <div className="card tf row timeframe"><div className="grow"><p className="k">Your desired timeframe</p><h2>When do you want to be job-ready?</h2><p className="small">Choose a pace for courses, projects and applications when planning becomes available.</p></div><div className="chips" aria-label="Timeframe options">{[6,9,12,18].map(m => <PendingAction key={m}>{m} months</PendingAction>)}</div></div>
 <div className="card split roadmap-stats">{[['Your target role','Not set'],['Progress','No roadmap yet'],['Target · Weekly load','To be planned']].map(([title,value]) => <div key={title}><p className="k">{title}</p><p className="stat-value">{value}</p><div className="bar"><i style={{width:0}}/></div></div>)}</div>
 <div className="chips filter-row" aria-label="Roadmap filters">{['All','Courses','Skills','People','Jobs'].map(f => <button key={f} type="button" className={`chip ${filter===f?'on':''}`} aria-pressed={filter===f} onClick={()=>setFilter(f)}>{f}</button>)}</div>
 <SectionTitle title={filter==='All'?'Your milestones':filter}/><div className="card"><EmptyState icon="road" title={filter==='All'?'Your roadmap starts here':`No ${filter.toLowerCase()} to show yet`}>Your personalised steps will appear here when roadmap planning is ready.</EmptyState></div>
 <div className="grid c3 roadmap-outline">{[['book','Build your capabilities','Courses and practical skills for your target role.'],['chat','Find your people','Conversations to help you understand the path ahead.'],['brief','Make your next move','Projects, internships and applications along the way.']].map(([icon,title,body])=><div className="card" key={title}><EmptyState compact icon={icon} title={title}>{body}</EmptyState></div>)}</div>
 </section>;
}
